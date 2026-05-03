"""
Harmonic API Client
====================

Shared REST client for Harmonic.ai company intelligence API.

Endpoints implemented:
- POST /companies - Lookup company by domain/LinkedIn URL
- GET /companies/{id} - Get full company details
- GET /companies/{id}/employees - Get employees (founders, executives)
- GET /search/search_agent - Natural language company search

Reference: https://console.harmonic.ai/docs/api-reference/introduction

Usage:
    from core.clients import HarmonicClient

    client = HarmonicClient()
    company = client.lookup_company(domain="stripe.com")
"""

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin

import requests

from core.resilience import (
    retry_with_backoff,
    is_retryable_error,
    get_circuit_breaker,
    RateLimitHandler,
)

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_BASE_URL = "https://api.harmonic.ai"
DEFAULT_TIMEOUT = 30  # seconds
RATE_LIMIT_RPS = 10  # requests per second
MAX_RETRIES = 3  # Maximum retry attempts for transient failures


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class HarmonicCompany:
    """Parsed company data from Harmonic API."""
    id: str
    name: str
    description: Optional[str] = None
    domain: Optional[str] = None
    website_url: Optional[str] = None
    logo_url: Optional[str] = None

    # Location
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    # Founding info
    founded_date: Optional[str] = None
    founded_year: Optional[int] = None

    # Metrics
    headcount: Optional[int] = None
    headcount_change_90d: Optional[float] = None  # % change
    web_traffic: Optional[int] = None
    web_traffic_change_30d: Optional[float] = None  # % change

    # Funding
    funding_total: Optional[float] = None
    funding_stage: Optional[str] = None
    funding_last_amount: Optional[float] = None
    funding_last_date: Optional[str] = None
    funding_rounds: list[dict] = field(default_factory=list)
    investors: list[str] = field(default_factory=list)

    # Social
    linkedin_url: Optional[str] = None

    # Tags/Categories
    tags: list[str] = field(default_factory=list)
    customer_type: Optional[str] = None  # B2B, B2C, etc.

    # Raw data for additional fields
    raw_data: dict = field(default_factory=dict)

    # Metadata
    fetched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @classmethod
    def from_api_response(cls, data: dict) -> "HarmonicCompany":
        """Parse Harmonic API response into HarmonicCompany."""
        # Extract nested fields safely
        website = data.get("website", {}) or {}
        funding = data.get("funding", {}) or {}
        traction = data.get("traction_metrics", {}) or data.get("tractionMetrics", {}) or {}
        founding = data.get("founding_date", {}) or {}
        socials = data.get("socials", {}) or {}
        location = data.get("location", {}) or {}

        # Parse headcount changes from traction_metrics.headcount
        headcount_change = None
        headcount_data = traction.get("headcount", {}) or {}
        if headcount_data.get("90d_ago"):
            headcount_change = headcount_data["90d_ago"].get("percent_change")

        # Parse web traffic changes from traction_metrics.web_traffic
        traffic_change = None
        web_traffic_data = traction.get("web_traffic", {}) or {}
        if web_traffic_data.get("30d_ago"):
            traffic_change = web_traffic_data["30d_ago"].get("percent_change")

        # Parse funding rounds and investors
        funding_rounds = funding.get("funding_rounds", []) or funding.get("fundingRounds", []) or []
        investors = []
        # Parse investors from funding.investors array (Harmonic format)
        for investor in funding.get("investors", []) or []:
            name = investor.get("name") or investor.get("investor_name")
            if name and name not in investors:
                investors.append(name)
        # Also check funding rounds for investors
        for round_data in funding_rounds:
            for investor in round_data.get("investors", []):
                name = investor.get("investor_name") or investor.get("investorName") or investor.get("name")
                if name and name not in investors:
                    investors.append(name)

        # Parse tags
        tags = []
        for tag in data.get("tags_v2", []) or data.get("tagsV2", []) or []:
            if tag.get("display_value") or tag.get("displayValue"):
                tags.append(tag.get("display_value") or tag.get("displayValue"))

        # Parse founding year from founding_date object
        founded_year = None
        founded_date_str = None
        if founding:
            founded_date_str = founding.get("date")
            if founded_date_str:
                try:
                    founded_year = int(founded_date_str[:4])
                except (ValueError, TypeError):
                    pass

        # Parse LinkedIn URL from socials
        linkedin_url = None
        linkedin_data = socials.get("LINKEDIN", {}) or {}
        if linkedin_data:
            linkedin_url = linkedin_data.get("url")

        # Extract company ID from entity_urn if needed
        company_id = data.get("id")
        if not company_id:
            entity_urn = data.get("entity_urn", "")
            if "company:" in entity_urn:
                company_id = entity_urn.split("company:")[-1]

        # Extract location info
        city = location.get("city")
        state = location.get("state")
        country = location.get("country")

        # Extract funding last round info - Harmonic uses last_funding_at and last_funding_total
        funding_last_date = (
            funding.get("last_funding_at") or
            funding.get("lastFundingAt") or
            funding.get("last_date") or
            funding.get("lastDate")
        )
        funding_last_amount = (
            funding.get("last_funding_total") or
            funding.get("lastFundingTotal") or
            funding.get("last_amount") or
            funding.get("lastAmount")
        )

        return cls(
            id=str(company_id or ""),
            name=data.get("name") or "Unknown",
            description=data.get("description"),
            domain=website.get("domain"),
            website_url=website.get("url"),
            logo_url=data.get("logo_url"),
            city=city,
            state=state,
            country=country,
            founded_date=founded_date_str,
            founded_year=founded_year,
            headcount=data.get("headcount"),
            headcount_change_90d=headcount_change,
            web_traffic=data.get("web_traffic"),
            web_traffic_change_30d=traffic_change,
            funding_total=funding.get("funding_total") or funding.get("fundingTotal"),
            funding_stage=funding.get("funding_stage") or funding.get("fundingStage") or funding.get("current_stage") or funding.get("currentStage"),
            funding_last_amount=funding_last_amount,
            funding_last_date=funding_last_date,
            funding_rounds=funding_rounds,
            investors=investors,
            linkedin_url=linkedin_url,
            tags=tags,
            customer_type=data.get("customer_type"),
            raw_data=data,
        )


@dataclass
class HarmonicPerson:
    """Parsed person/employee data from Harmonic API."""
    id: str
    name: str
    title: Optional[str] = None
    linkedin_url: Optional[str] = None
    is_founder: bool = False
    is_executive: bool = False
    start_date: Optional[str] = None
    current_company: Optional[str] = None
    raw_data: dict = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: dict) -> "HarmonicPerson":
        """Parse Harmonic API person response."""
        # Extract name
        name = data.get("full_name") or data.get("fullName") or data.get("name", "Unknown")

        # Extract LinkedIn from socials
        linkedin_url = None
        socials = data.get("socials", {}) or {}
        linkedin_data = socials.get("LINKEDIN", {}) or {}
        if linkedin_data:
            linkedin_url = linkedin_data.get("url")

        # Get current position from experience
        title = None
        current_company = None
        is_founder = False
        is_executive = False
        start_date = None

        experience = data.get("experience", []) or []
        for exp in experience:
            if exp.get("is_current_position"):
                title = exp.get("title")
                current_company = exp.get("company_name")
                start_date = exp.get("start_date")
                role_type = exp.get("role_type", "")
                if role_type == "FOUNDER":
                    is_founder = True
                if role_type in ("EXECUTIVE", "FOUNDER"):
                    is_executive = True
                break  # Use first current position

        # Fallback for id
        person_id = data.get("id")
        if not person_id:
            entity_urn = data.get("entity_urn", "")
            if "person:" in entity_urn:
                person_id = entity_urn.split("person:")[-1]

        return cls(
            id=str(person_id or ""),
            name=name,
            title=title,
            linkedin_url=linkedin_url,
            is_founder=is_founder,
            is_executive=is_executive,
            start_date=start_date,
            current_company=current_company,
            raw_data=data,
        )


# =============================================================================
# HARMONIC API CLIENT
# =============================================================================

class HarmonicAPIError(Exception):
    """Custom exception for Harmonic API errors."""
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[dict] = None,
        retry_after: Optional[float] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response
        self.retry_after = retry_after  # Seconds to wait before retrying (from Retry-After header)


class HarmonicClient:
    """
    REST client for Harmonic.ai API.

    Usage:
        client = HarmonicClient(api_key="your_key")

        # Lookup company by domain
        company = client.lookup_company(domain="stripe.com")

        # Get company by ID
        company = client.get_company(company_id="123456")

        # Get founders
        founders = client.get_company_employees(
            company_id="123456",
            employee_type="founders"
        )

        # Search companies
        results = client.search_companies("AI startups in healthcare")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
    ):
        """
        Initialize Harmonic API client.

        Args:
            api_key: Harmonic API key. Falls back to HARMONIC_API_KEY env var.
            base_url: API base URL (default: https://api.harmonic.ai)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for transient failures
        """
        raw_key = api_key or os.getenv("HARMONIC_API_KEY")
        if not raw_key:
            raise ValueError(
                "Harmonic API key required. Set HARMONIC_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.api_key = raw_key.strip()

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_request_time = 0.0

        # Resilience components
        self._circuit_breaker = get_circuit_breaker(
            "harmonic",
            failure_threshold=5,
            timeout=60.0,
        )
        self._rate_limiter = RateLimitHandler(default_rps=RATE_LIMIT_RPS)
        self._rate_limiter.set_limit("harmonic", RATE_LIMIT_RPS)

        self.session = requests.Session()
        self.session.headers.update({
            "apikey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _rate_limit(self):
        """Enforce rate limiting between requests."""
        self._rate_limiter.wait_if_needed("harmonic")

    def _parse_retry_after(self, response: requests.Response) -> Optional[float]:
        """Parse Retry-After header from response."""
        retry_after = response.headers.get("Retry-After")
        if not retry_after:
            return None
        try:
            return float(retry_after)
        except ValueError:
            # Could be HTTP-date format, default to 60s
            return 60.0

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
    ) -> dict:
        """Make an API request with error handling and retries."""
        return self._request_with_retry(method, endpoint, params, json_data)

    @retry_with_backoff(max_retries=MAX_RETRIES, base_delay=1.0, max_delay=30.0)
    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
    ) -> dict:
        """Make an API request with automatic retry on transient failures."""
        # Check circuit breaker
        if not self._circuit_breaker.allow_request():
            raise HarmonicAPIError(
                "Circuit breaker open - Harmonic API temporarily unavailable",
                status_code=503,
            )

        self._rate_limit()
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=self.timeout,
            )

            # Log for debugging
            logger.debug(f"Harmonic API {method} {url} -> {response.status_code}")

            # Record response for rate limiting
            self._rate_limiter.record_response(
                "harmonic",
                response.status_code,
                dict(response.headers),
            )

            if response.status_code in (401, 403):
                # Permanent auth error - don't retry
                self._circuit_breaker.record_failure()
                error_data = response.json() if response.content else {}
                msg = error_data.get("message", "Invalid or missing API key")
                raise HarmonicAPIError(msg, status_code=response.status_code)
            elif response.status_code == 404:
                # Not found is not a failure, just no data
                return {}
            elif response.status_code == 429:
                # Rate limit - retry with backoff
                retry_after = self._parse_retry_after(response)
                self._circuit_breaker.record_failure()
                raise HarmonicAPIError(
                    "Rate limit exceeded",
                    status_code=429,
                    retry_after=retry_after,
                )
            elif response.status_code >= 500:
                # Server error - transient, retry
                self._circuit_breaker.record_failure()
                error_data = response.json() if response.content else {}
                raise HarmonicAPIError(
                    f"Server error: {error_data.get('message', response.text)}",
                    status_code=response.status_code,
                    response=error_data,
                )
            elif response.status_code >= 400:
                # Client error - likely permanent
                error_data = response.json() if response.content else {}
                raise HarmonicAPIError(
                    f"API error: {error_data.get('message', response.text)}",
                    status_code=response.status_code,
                    response=error_data,
                )

            # Success
            self._circuit_breaker.record_success()
            return response.json() if response.content else {}

        except requests.exceptions.Timeout:
            self._circuit_breaker.record_failure()
            raise HarmonicAPIError(
                f"Request timed out after {self.timeout}s",
                status_code=408,
            )
        except requests.exceptions.ConnectionError as e:
            self._circuit_breaker.record_failure()
            raise HarmonicAPIError(
                f"Connection error: {e}",
                status_code=503,
            )

    # =========================================================================
    # COMPANY ENDPOINTS
    # =========================================================================

    def _extract_company_id(self, entity_urn: str) -> Optional[str]:
        """Extract company ID from entity URN."""
        if entity_urn and "company:" in entity_urn:
            return entity_urn.split("company:")[-1]
        return None

    def lookup_company(
        self,
        domain: Optional[str] = None,
        linkedin_url: Optional[str] = None,
    ) -> Optional[HarmonicCompany]:
        """Lookup company by domain or LinkedIn URL."""
        if not domain and not linkedin_url:
            raise ValueError("Either domain or linkedin_url required")

        query = domain or linkedin_url
        try:
            data = self._request("GET", "/search/typeahead", params={"query": query})
            results = data.get("results", [])

            if not results:
                return None

            for result in results:
                if result.get("type") == "COMPANY":
                    entity_urn = result.get("entity_urn")
                    company_id = self._extract_company_id(entity_urn)
                    if company_id:
                        return self.get_company(company_id)

            return None
        except HarmonicAPIError as e:
            if e.status_code == 404:
                return None
            raise

    def get_company(self, company_id: str) -> Optional[HarmonicCompany]:
        """Get company by Harmonic ID."""
        try:
            data = self._request("GET", f"/companies/{company_id}")
            if data:
                return HarmonicCompany.from_api_response(data)
            return None
        except HarmonicAPIError as e:
            if e.status_code == 404:
                return None
            raise

    def _extract_person_id(self, entity_urn: str) -> Optional[str]:
        """Extract person ID from entity URN."""
        if entity_urn and "person:" in entity_urn:
            return entity_urn.split("person:")[-1]
        return None

    def get_company_employees(
        self,
        company_id: str,
        employee_type: str = "all",
        limit: int = 50,
        fetch_details: bool = True,
    ) -> list[HarmonicPerson]:
        """Get company employees/team members."""
        params = {"size": limit}

        type_map = {
            "founders": "FOUNDERS",
            "executives": "EXECUTIVES",
            "engineering": "ENGINEERING",
            "all": None,
        }
        if employee_type in type_map and type_map[employee_type]:
            params["employeeGroupType"] = type_map[employee_type]

        try:
            data = self._request("GET", f"/companies/{company_id}/employees", params=params)
            results = data.get("results", [])

            employees = []
            for item in results[:limit]:
                if isinstance(item, str):
                    person_id = self._extract_person_id(item)
                    if person_id:
                        if fetch_details:
                            person = self.get_person(person_id)
                            if person:
                                employees.append(person)
                        else:
                            employees.append(HarmonicPerson(id=person_id, name="Unknown"))
                elif isinstance(item, dict):
                    employees.append(HarmonicPerson.from_api_response(item))

            return employees
        except HarmonicAPIError as e:
            if e.status_code == 404:
                return []
            raise

    # =========================================================================
    # SEARCH ENDPOINTS
    # =========================================================================

    def search_companies(self, query: str, limit: int = 20) -> list[HarmonicCompany]:
        """Search companies using natural language query."""
        params = {"query": query, "size": limit}

        try:
            data = self._request("GET", "/search/search_agent", params=params)
            results = data.get("results", data.get("companies", []))
            return [HarmonicCompany.from_api_response(c) for c in results]
        except HarmonicAPIError:
            return []

    def search_typeahead(self, query: str, limit: int = 10) -> list[HarmonicCompany]:
        """Quick autocomplete search by company name or domain."""
        params = {"query": query}

        try:
            data = self._request("GET", "/search/typeahead", params=params)
            results = data.get("results", [])

            companies = []
            seen_ids = set()

            for result in results[:limit]:
                if result.get("type") == "COMPANY":
                    entity_urn = result.get("entity_urn")
                    company_id = self._extract_company_id(entity_urn)

                    if company_id and company_id not in seen_ids:
                        seen_ids.add(company_id)
                        companies.append(HarmonicCompany(
                            id=company_id,
                            name=result.get("text", "Unknown"),
                            raw_data=result,
                        ))

            return companies
        except HarmonicAPIError:
            return []

    def find_similar_companies(self, company_id: str, limit: int = 10) -> list[HarmonicCompany]:
        """Find companies similar to a given company."""
        params = {"size": limit}

        try:
            data = self._request("GET", f"/search/similar_companies/{company_id}", params=params)
            results = data.get("results", data.get("companies", []))
            return [HarmonicCompany.from_api_response(c) for c in results]
        except HarmonicAPIError:
            return []

    # =========================================================================
    # PERSON ENDPOINTS
    # =========================================================================

    def lookup_person(self, linkedin_url: str) -> Optional[HarmonicPerson]:
        """Lookup person by LinkedIn URL."""
        try:
            data = self._request("POST", "/persons", json_data={"linkedinUrl": linkedin_url})
            if data:
                return HarmonicPerson.from_api_response(data)
            return None
        except HarmonicAPIError as e:
            if e.status_code == 404:
                return None
            raise

    def get_person(self, person_id: str) -> Optional[HarmonicPerson]:
        """Get person by Harmonic ID."""
        try:
            data = self._request("GET", f"/persons/{person_id}")
            if data:
                return HarmonicPerson.from_api_response(data)
            return None
        except HarmonicAPIError as e:
            if e.status_code == 404:
                return None
            raise
