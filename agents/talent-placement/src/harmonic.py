"""All Harmonic API calls live here. No Harmonic calls anywhere else."""
from __future__ import annotations

import os
import logging
from datetime import date
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


def _compute_tenure_years(start_date: str | None) -> float | None:
    if not start_date:
        return None
    try:
        parts = str(start_date).split("-")
        year, month = int(parts[0]), int(parts[1]) if len(parts) > 1 else 1
        delta = date.today() - date(year, month, 1)
        return round(delta.days / 365.25, 1)
    except Exception:
        return None


def find_company_id(query: str) -> str | None:
    """Look up Harmonic company ID by name or domain."""
    try:
        data = _get("/search/typeahead", params={"query": query})
        for result in data.get("results", []):
            if result.get("type") == "COMPANY":
                urn = result.get("entity_urn", "")
                if "company:" in urn:
                    return urn.split("company:")[-1]
    except Exception as e:
        logger.error("find_company_id failed for %s: %s", query, e)
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
        tenure_years=_compute_tenure_years(start_date),
    )


_ROLE_RANK = {"FOUNDER": 0, "EXECUTIVE": 1, "EMPLOYEE": 2}


def get_company_employees(company_identifier: str, limit: int = 30) -> list[Employee]:
    """Pull current employees for a portfolio company.

    company_identifier can be a company name, domain, or Harmonic company ID.
    Uses the company record's `people` field so founders/executives surface first.
    """
    if not company_identifier.isdigit():
        company_id = find_company_id(company_identifier)
        if not company_id:
            logger.warning("Could not find Harmonic company ID for: %s", company_identifier)
            return []
    else:
        company_id = company_identifier

    try:
        company_data = _get(f"/companies/{company_id}")
    except Exception as e:
        logger.error("Could not fetch company %s: %s", company_id, e)
        return []

    company_name = company_data.get("name", company_identifier)

    # `people` has role-typed current and past employees; filter to current only
    people_records = [
        p for p in (company_data.get("people") or [])
        if p.get("is_current_position") and "person:" in p.get("person", "")
    ]
    # Sort: founders first, then executives, then everyone else
    people_records.sort(key=lambda p: _ROLE_RANK.get(p.get("role_type", ""), 2))

    employees: list[Employee] = []
    seen_ids: set[str] = set()
    for record in people_records[:limit * 2]:  # fetch extra to absorb any 404s
        if len(employees) >= limit:
            break
        person_id = record["person"].split("person:")[-1]
        if person_id in seen_ids:
            continue
        seen_ids.add(person_id)
        try:
            person_data = _get(f"/persons/{person_id}")
            employees.append(_parse_person(person_data, company_name))
        except Exception as e:
            logger.debug("Could not fetch person %s: %s", person_id, e)

    return employees


def get_person_by_linkedin(linkedin_url: str) -> Employee | None:
    """Look up a person in Harmonic by their LinkedIn URL."""
    try:
        data = _get("/search/typeahead", params={"query": linkedin_url, "numResults": 5})
        person_id = None
        for result in data.get("results", []):
            if result.get("type") == "PERSON" and "person:" in result.get("entity_urn", ""):
                person_id = result["entity_urn"].split("person:")[-1]
                break
        if not person_id:
            logger.warning("No Harmonic record found for: %s", linkedin_url)
            return None
        person_data = _get(f"/persons/{person_id}")
        current_company = ""
        for exp in person_data.get("experience", []) or []:
            if exp.get("is_current_position"):
                c = exp.get("company")
                current_company = c.get("name") if isinstance(c, dict) else (exp.get("company_name") or "")
                break
        return _parse_person(person_data, current_company or "Unknown")
    except Exception as e:
        logger.error("get_person_by_linkedin failed for %s: %s", linkedin_url, e)
        return None


def _parse_destination_person(data: dict) -> dict:
    name = data.get("full_name") or data.get("name") or "Unknown"

    linkedin_url = None
    socials = data.get("socials", {}) or {}
    li = socials.get("LINKEDIN", {}) or {}
    linkedin_url = li.get("url")

    current_company = None
    current_title = None
    for exp in data.get("experience", []) or []:
        if exp.get("is_current_position"):
            c = exp.get("company")
            current_company = c.get("name") if isinstance(c, dict) else exp.get("company_name")
            current_title = exp.get("title")
            break

    return {
        "name": name,
        "current_company": current_company,
        "title": current_title,
        "linkedin_url": linkedin_url,
    }


def find_destinations(employee: Employee) -> list[dict]:
    """Return top 10 similar people at other companies via Harmonic.

    Tries the /persons/{id}/similar endpoint first; falls back to a
    title-keyword search via /search/persons.
    """
    results: list[dict] = []

    # Try the similar-persons endpoint if we have a Harmonic person ID
    if employee.id:
        try:
            data = _get(f"/persons/{employee.id}/similar", params={"size": 10})
            for item in data.get("results", [])[:10]:
                if isinstance(item, dict):
                    results.append(_parse_destination_person(item))
                elif isinstance(item, str):
                    person_id = item.split("person:")[-1] if "person:" in item else item
                    try:
                        person_data = _get(f"/persons/{person_id}")
                        results.append(_parse_destination_person(person_data))
                    except Exception as e:
                        logger.debug("Could not fetch similar person %s: %s", person_id, e)
            if results:
                return results[:10]
        except Exception as e:
            logger.debug("similar endpoint failed for %s, falling back to search: %s", employee.name, e)

    # Fallback: typeahead search on title → fetch each matching person.
    # Try progressively shorter title fragments until we get PERSON hits.
    if not employee.title:
        return results

    # Build candidate queries: full title, then each comma/slash segment, then first two words
    raw = employee.title
    segments = [s.strip() for s in raw.replace("/", ",").split(",") if s.strip()]
    candidates: list[str] = [raw] + segments
    if raw.split():
        candidates.append(" ".join(raw.split()[:2]))

    person_ids: list[str] = []
    for query in dict.fromkeys(candidates):  # dedupe, preserve order
        try:
            typeahead = _get("/search/typeahead", params={"query": query, "numResults": 25})
            ids = [
                r["entity_urn"].split("person:")[-1]
                for r in typeahead.get("results", [])
                if r.get("type") == "PERSON" and "person:" in r.get("entity_urn", "")
            ]
            if ids:
                person_ids = ids
                logger.debug("find_destinations typeahead hit on %r (%d results)", query, len(ids))
                break
        except Exception as e:
            logger.error("find_destinations typeahead failed for %s: %s", employee.name, e)
            return results

    if not person_ids:
        logger.debug("find_destinations: no typeahead hits for %s (%r)", employee.name, raw)
        return results

    source_company_lower = employee.company.lower()
    seen_linkedin: set[str] = set()
    for person_id in dict.fromkeys(person_ids):  # dedupe IDs
        if len(results) >= 10:
            break
        try:
            person_data = _get(f"/persons/{person_id}")
        except Exception as e:
            logger.debug("Could not fetch person %s: %s", person_id, e)
            continue
        dest = _parse_destination_person(person_data)

        # Skip nameless, placeholder, and same-company profiles
        if not dest["name"] or dest["name"] == "Unknown":
            continue
        name_lower = dest["name"].lower()
        if name_lower == (dest["title"] or "").lower():
            continue
        # Drop profiles whose name is composed entirely of job-title keywords
        _TITLE_WORDS = {
            "co", "co-", "founder", "co-founder", "cofounder", "manager", "officer",
            "director", "engineer", "developer", "analyst", "executive", "president",
            "administrator", "consultant", "head", "lead", "chief", "vp", "ceo",
            "cto", "coo", "cfo", "partner", "associate", "intern", "staff", "senior",
            "junior", "founders",
        }
        name_words = set(name_lower.replace("-", " ").split())
        if name_words and name_words.issubset(_TITLE_WORDS):
            continue
        if dest["current_company"] and dest["current_company"].lower() == source_company_lower:
            continue
        # Dedupe by LinkedIn URL
        li = dest["linkedin_url"] or ""
        if li and li in seen_linkedin:
            continue
        if li:
            seen_linkedin.add(li)

        results.append(dest)

    return results[:10]


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    company = sys.argv[1] if len(sys.argv) > 1 else "Stripe"
    print(f"\n--- Employees at {company} ---")
    employees = get_company_employees(company, limit=5)
    for emp in employees:
        print(f"  {emp.name} | {emp.title} | {emp.tenure_years}y | {emp.linkedin_url}")

    if employees:
        target = employees[0]
        print(f"\n--- Destinations for {target.name} ({target.title}) ---")
        dests = find_destinations(target)
        print(json.dumps(dests, indent=2))
