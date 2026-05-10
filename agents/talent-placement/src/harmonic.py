"""All Harmonic API calls live here. No Harmonic calls anywhere else."""
from __future__ import annotations

import os
import logging
import requests
from dotenv import load_dotenv
from .models import Employee

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.harmonic.ai"


def _headers() -> dict[str, str]:
    key = os.environ["HARMONIC_API_KEY"].strip()
    return {"apikey": key, "Content-Type": "application/json"}


def _get(endpoint: str, params: dict | None = None) -> dict:
    resp = requests.get(f"{_BASE_URL}{endpoint}", headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(endpoint: str, body: dict) -> dict:
    resp = requests.post(f"{_BASE_URL}{endpoint}", headers=_headers(), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def find_company_id(domain: str) -> str | None:
    """Look up Harmonic company ID from a domain name."""
    try:
        data = _get("/search/typeahead", params={"query": domain})
        for result in data.get("results", []):
            if result.get("type") == "COMPANY":
                urn = result.get("entity_urn", "")
                if "company:" in urn:
                    return urn.split("company:")[-1]
    except Exception as e:
        logger.error("find_company_id failed for %s: %s", domain, e)
    return None


def _parse_person(data: dict, company_name: str) -> Employee:
    name = data.get("full_name") or data.get("name") or "Unknown"

    linkedin_url = None
    socials = data.get("socials", {}) or {}
    li = socials.get("LINKEDIN", {}) or {}
    if li:
        linkedin_url = li.get("url")

    title = None
    is_founder = False
    is_executive = False
    start_date = None
    for exp in data.get("experience", []) or []:
        if exp.get("is_current_position"):
            title = exp.get("title")
            start_date = exp.get("start_date")
            role_type = exp.get("role_type", "")
            is_founder = role_type == "FOUNDER"
            is_executive = role_type in ("EXECUTIVE", "FOUNDER")
            break

    person_id = data.get("id") or ""
    if not person_id:
        urn = data.get("entity_urn", "")
        if "person:" in urn:
            person_id = urn.split("person:")[-1]

    return Employee(
        id=str(person_id),
        name=name,
        title=title,
        company=company_name,
        linkedin_url=linkedin_url,
        is_founder=is_founder,
        is_executive=is_executive,
        start_date=start_date,
    )


def get_company_employees(company_identifier: str, limit: int = 30) -> list[Employee]:
    """Pull current employees for a portfolio company.

    company_identifier can be a domain (stripe.com) or a Harmonic company ID.
    Fetches founders and executives first, then fills up to limit with all employees.
    """
    # Resolve to a Harmonic ID if given a domain
    if not company_identifier.isdigit():
        company_id = find_company_id(company_identifier)
        if not company_id:
            logger.warning("Could not find Harmonic company ID for: %s", company_identifier)
            return []
    else:
        company_id = company_identifier

    # Get company name for context
    company_name = company_identifier
    try:
        company_data = _get(f"/companies/{company_id}")
        company_name = company_data.get("name", company_identifier)
    except Exception:
        pass

    employees: list[Employee] = []
    seen_ids: set[str] = set()

    def _fetch_group(group_type: str | None, n: int) -> None:
        params: dict = {"size": n}
        if group_type:
            params["employeeGroupType"] = group_type
        try:
            data = _get(f"/companies/{company_id}/employees", params=params)
            for item in data.get("results", []):
                if isinstance(item, str):
                    # item is a person URN or ID — fetch details
                    person_id = item.split("person:")[-1] if "person:" in item else item
                    if person_id in seen_ids:
                        continue
                    seen_ids.add(person_id)
                    try:
                        person_data = _get(f"/persons/{person_id}")
                        employees.append(_parse_person(person_data, company_name))
                    except Exception as e:
                        logger.debug("Could not fetch person %s: %s", person_id, e)
                elif isinstance(item, dict):
                    person_id = str(item.get("id", ""))
                    if person_id and person_id not in seen_ids:
                        seen_ids.add(person_id)
                        employees.append(_parse_person(item, company_name))
        except Exception as e:
            logger.error("Error fetching %s employees for %s: %s", group_type, company_id, e)

    # Prioritize founders and executives
    _fetch_group("FOUNDERS", 10)
    _fetch_group("EXECUTIVES", 20)
    if len(employees) < limit:
        _fetch_group(None, limit)

    # Dedupe preserving order
    seen: set[str] = set()
    unique: list[Employee] = []
    for e in employees:
        if e.id not in seen:
            seen.add(e.id)
            unique.append(e)

    return unique[:limit]
