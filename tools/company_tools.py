"""
Shared Company Tools
====================

Tools for fetching, storing, and retrieving company data.
Used by multiple agents for company intelligence.

Implemented Sources:
- Harmonic: Company profiles, founders, person backgrounds
- Tavily: Website intelligence/updates
- Parallel Search: News articles, event signals

Usage:
    from tools.company_tools import (
        get_company_profile,
        get_founders,
        get_recent_news,
        get_key_signals,
        enrich_founder_backgrounds,
        ingest_company,
        get_company_bundle,
    )

    # Ingest all data for a company
    result = ingest_company("stripe.com")

    # Enrich founder backgrounds with Harmonic data
    enriched = enrich_founder_backgrounds("stripe.com")

    # Get complete bundle for briefing
    bundle = get_company_bundle("stripe.com")
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.database import (
    CompanyCore,
    Founder,
    NewsArticle,
    KeySignal,
    CompanyBundle,
    CompetitorSnapshot,
    sync_founders_to_supabase,
    sync_company_to_supabase,
    sync_news_to_supabase,
    sync_competitors_to_supabase,
    sync_signals_to_supabase,
    read_company_from_supabase,
    read_founders_from_supabase,
    get_company_bundle_from_supabase,
    patch_company_website_update,
)
from core.clients.harmonic import HarmonicClient, HarmonicCompany, HarmonicPerson, HarmonicAPIError
from core.clients.tavily import TavilyClient, TavilyAPIError
# Swarm integration disabled - using Harmonic for all person data
# from core.clients.swarm import SwarmClient, SwarmAPIError, FounderProfile
from core.clients.parallel_search import (
    ParallelSearchClient,
    ParallelSearchError,
    _classify_signal_type,
)
import re
from core.tracking import get_tracker

logger = logging.getLogger(__name__)


# =============================================================================
# EXCERPT CLEANING
# =============================================================================

# Patterns to skip when cleaning excerpts
BOILERPLATE_PATTERNS = [
    r"cookie", r"accept all", r"reject all", r"privacy policy", r"terms of service",
    r"subscribe", r"sign up", r"log in", r"menu", r"navigation", r"toggle",
    r"share this", r"follow us", r"copyright", r"all rights reserved",
    r"skip to content", r"skip to main", r"read more", r"learn more", r"click here",
    r"manage cookies", r"cookie settings", r"we use cookies",
    r"section title:", r"oops, something went wrong", r"go to hub",
    r"futures & commodities", r"prediction markets", r"yahoo finance",
    r"published \w+,", r"updated \w+,",  # Skip date lines like "Published Fri, Feb"
    r"^\[.*\]\(.*\)$",  # Skip markdown links that are the entire line
    r"^>\s*",  # Skip blockquotes
]

def _clean_excerpt(excerpt: str, max_chars: int = 200) -> str:
    """
    Clean an excerpt by removing boilerplate content.

    Args:
        excerpt: Raw excerpt text
        max_chars: Maximum characters to return

    Returns:
        Cleaned excerpt or empty string if all content is boilerplate
    """
    if not excerpt:
        return ""

    # Pre-clean: remove common junk patterns
    excerpt = re.sub(r'\[Skip to [^\]]+\]\([^)]*\)', '', excerpt)  # [Skip to X](url)
    excerpt = re.sub(r'\[[^\]]*\]\(\s*\)', '', excerpt)  # Empty links [text]()
    excerpt = re.sub(r'\[?\s*\]\([^)]+\)', '', excerpt)  # [](url) empty text links
    excerpt = re.sub(r'Section Title:\s*', '', excerpt, flags=re.IGNORECASE)
    excerpt = re.sub(r'>\s*Content:', '', excerpt)
    excerpt = re.sub(r'Published \w+, \w+ \d+.*?(?=\.|$)', '', excerpt)
    excerpt = re.sub(r'Updated \w+, \w+ \d+.*?(?=\.|$)', '', excerpt)

    # Split into sentences/lines
    lines = excerpt.replace("\n", ". ").split(". ")
    clean_lines = []

    for line in lines:
        line = line.strip()
        if not line or len(line) < 20:
            continue

        # Skip lines matching boilerplate patterns
        line_lower = line.lower()
        if any(re.search(pattern, line_lower) for pattern in BOILERPLATE_PATTERNS):
            continue

        # Skip lines that are mostly URLs or markdown links
        if line.count("http") > 1 or line.count("](") > 2:
            continue

        # Skip lines that start with navigation-like content
        if re.match(r'^[\[\(]', line) and '](/' in line:
            continue

        # Clean markdown artifacts
        clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', line)  # [text](url) -> text
        clean = re.sub(r'[#*_`>\[\]]', '', clean).strip()

        # Skip if mostly punctuation or very short after cleaning
        if len(clean) < 25:
            continue

        # Skip if it looks like a nav menu (multiple slashes, pipes)
        if clean.count('/') > 2 or clean.count('|') > 1:
            continue

        clean_lines.append(clean)

    if not clean_lines:
        return ""

    # Join and truncate
    result = ". ".join(clean_lines)
    if len(result) > max_chars:
        result = result[:max_chars].rsplit(" ", 1)[0] + "..."

    return result


# =============================================================================
# CONFIGURATION
# =============================================================================

# Singleton Harmonic client
_harmonic_client: Optional[HarmonicClient] = None


def get_harmonic_client() -> HarmonicClient:
    """Get or create Harmonic client instance."""
    global _harmonic_client
    if _harmonic_client is None:
        _harmonic_client = HarmonicClient()
    return _harmonic_client


# Singleton Tavily client
_tavily_client: Optional[TavilyClient] = None


def get_tavily_client() -> Optional[TavilyClient]:
    """Get or create Tavily client instance. Returns None if API key not set."""
    global _tavily_client
    if _tavily_client is None:
        try:
            _tavily_client = TavilyClient()
        except ValueError:
            logger.info("TAVILY_API_KEY not set - website intelligence disabled")
            return None
    return _tavily_client


# Singleton Swarm client
_swarm_client: Optional[SwarmClient] = None


def get_swarm_client() -> Optional[SwarmClient]:
    """Get or create Swarm client instance. Returns None if API key not set."""
    global _swarm_client
    if _swarm_client is None:
        try:
            _swarm_client = SwarmClient()
        except ValueError:
            logger.info("SWARM_API_KEY not set - founder background enrichment disabled")
            return None
    return _swarm_client


# Singleton Parallel Search client
_parallel_client: Optional[ParallelSearchClient] = None


def get_parallel_client() -> Optional[ParallelSearchClient]:
    """Get or create Parallel Search client instance. Returns None if API key not set."""
    global _parallel_client
    if _parallel_client is None:
        try:
            _parallel_client = ParallelSearchClient()
        except ValueError:
            logger.info("PARALLEL_API_KEY not set - news research disabled")
            return None
    return _parallel_client


# =============================================================================
# URL PARSING UTILITIES
# =============================================================================

def parse_company_url(url: str) -> tuple[str, str]:
    """
    Parse company URL to determine type and normalize.

    Args:
        url: Company website URL or LinkedIn URL

    Returns:
        Tuple of (url_type, normalized_url) where url_type is:
        - "company_domain": Company website (e.g., stripe.com)
        - "company_linkedin": Company LinkedIn URL
        - "person_linkedin": Person LinkedIn URL
    """
    from urllib.parse import urlparse

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.rstrip("/")

    if "linkedin.com" in host:
        if "/company/" in path:
            return ("company_linkedin", url)
        elif "/in/" in path:
            return ("person_linkedin", url)
        else:
            return ("company_linkedin", url)
    else:
        domain = host
        return ("company_domain", domain)


def normalize_company_id(url: str) -> str:
    """
    Normalize URL to a consistent company_id.

    Args:
        url: Any form of company URL

    Returns:
        Normalized company_id (domain without protocol)
    """
    url_type, normalized = parse_company_url(url)
    if url_type == "company_domain":
        return normalized
    return normalized


# =============================================================================
# TOOL 1: get_company_profile
# =============================================================================

def get_company_profile(company_id: str) -> CompanyCore:
    """
    Fetch company snapshot data from Harmonic and write to company_core table.

    STATUS: IMPLEMENTED (Harmonic)

    Args:
        company_id: Company URL or domain

    Returns:
        CompanyCore object with populated fields

    Raises:
        ValueError: If company not found
    """
    client = get_harmonic_client()

    url_type, normalized = parse_company_url(company_id)
    normalized_id = normalize_company_id(company_id)

    company: Optional[HarmonicCompany] = None

    try:
        if url_type == "company_domain":
            company = client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            company = client.lookup_company(linkedin_url=normalized)
        elif url_type == "person_linkedin":
            person = client.lookup_person(normalized)
            if person and person.raw_data:
                experience = person.raw_data.get("experience", []) or []
                for exp in experience:
                    if exp.get("is_current_position"):
                        company_urn = exp.get("company_urn")
                        if company_urn and "company:" in company_urn:
                            company_id_from_urn = company_urn.split("company:")[-1]
                            company = client.get_company(company_id_from_urn)
                            break
    except HarmonicAPIError as e:
        logger.error(f"Harmonic API error for {company_id}: {e}")
        raise ValueError(f"Failed to fetch company from Harmonic: {e}")

    if not company:
        raise ValueError(f"Company not found in Harmonic for: {company_id}")

    # Build source map
    source_map = {
        "company_name": "harmonic",
        "founding_date": "harmonic",
        "hq": "harmonic",
        "employee_count": "harmonic",
        "total_funding": "harmonic",
        "products": "harmonic",
        "customers": "harmonic",
        "last_round_date": "harmonic",
        "last_round_funding": "harmonic",
        "web_traffic_trend": "pending_key_signals",
        "hiring_firing": "pending_key_signals",
        "website_update": "pending_tavily",
        "arr_apr": "not_available",
    }

    # Build HQ from location components
    hq = None
    hq_parts = []
    if company.city:
        hq_parts.append(company.city)
    if company.state:
        hq_parts.append(company.state)
    if company.country and company.country not in ("United States", "US", "USA"):
        hq_parts.append(company.country)
    if hq_parts:
        hq = ", ".join(hq_parts)

    # Format web traffic
    web_traffic_trend = None
    if company.web_traffic_change_30d is not None:
        sign = "+" if company.web_traffic_change_30d > 0 else ""
        web_traffic_trend = f"{sign}{company.web_traffic_change_30d:.1f}% (30d)"

    # Format headcount change
    hiring_firing = None
    if company.headcount_change_90d is not None:
        sign = "+" if company.headcount_change_90d > 0 else ""
        hiring_firing = f"{sign}{company.headcount_change_90d:.1f}% (90d)"

    # Use description for products
    products = company.description
    customers = company.customer_type

    # Preserve existing website_update from Supabase (populated by Tavily during signal ingestion)
    existing_website_update = None
    try:
        existing = read_company_from_supabase(normalized_id)
        if existing and existing.website_update:
            existing_website_update = existing.website_update
    except Exception:
        pass

    # Create CompanyCore object
    company_core = CompanyCore(
        company_id=normalized_id,
        company_name=company.name,
        founding_date=company.founded_date,
        hq=hq,
        employee_count=company.headcount,
        total_funding=company.funding_total,
        products=products,
        customers=customers,
        arr_apr=None,
        last_round_date=company.funding_last_date,
        last_round_funding=company.funding_last_amount,
        investors=company.investors[:10] if company.investors else [],
        web_traffic_trend=web_traffic_trend,
        website_update=existing_website_update,
        hiring_firing=hiring_firing,
        observed_at=datetime.utcnow().isoformat(),
        source_map=source_map,
    )

    logger.info(f"Fetched company profile: {company.name} ({normalized_id})")
    return company_core


# =============================================================================
# TOOL 2: get_founders
# =============================================================================

def get_founders(company_id: str) -> list[Founder]:
    """
    Fetch founders from Harmonic and write to founders table.

    STATUS: IMPLEMENTED (Harmonic) - background pending Swarm

    Args:
        company_id: Company URL or domain

    Returns:
        List of Founder objects

    Raises:
        ValueError: If company not found
    """
    client = get_harmonic_client()

    normalized_id = normalize_company_id(company_id)

    url_type, normalized = parse_company_url(company_id)
    company: Optional[HarmonicCompany] = None

    try:
        if url_type == "company_domain":
            company = client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            company = client.lookup_company(linkedin_url=normalized)
        elif url_type == "person_linkedin":
            person = client.lookup_person(normalized)
            if person and person.raw_data:
                experience = person.raw_data.get("experience", []) or []
                for exp in experience:
                    if exp.get("is_current_position"):
                        company_urn = exp.get("company_urn")
                        if company_urn and "company:" in company_urn:
                            company_id_from_urn = company_urn.split("company:")[-1]
                            company = client.get_company(company_id_from_urn)
                            break
    except HarmonicAPIError as e:
        logger.error(f"Harmonic API error for {company_id}: {e}")
        raise ValueError(f"Failed to fetch company from Harmonic: {e}")

    if not company:
        raise ValueError(f"Company not found in Harmonic for: {company_id}")

    founders_list: list[Founder] = []
    seen_names: set[str] = set()

    # Get founders from company's 'people' array
    people_array = company.raw_data.get("people", [])

    founder_urns = []
    executive_urns = []

    for p in people_array:
        role_type = p.get("role_type")
        person_urn = p.get("person", "")
        title = p.get("title", "")

        if role_type == "FOUNDER" and person_urn:
            founder_urns.append((person_urn, title))
        elif role_type == "EXECUTIVE" and person_urn:
            # Check if this is a founding-level executive
            title_lower = title.lower()
            is_founder_title = any(t in title_lower for t in ["co-founder", "cofounder", "founder"])
            is_top_exec = title_lower in ["ceo", "president"]  # Exact match only
            if is_founder_title or is_top_exec:
                executive_urns.append((person_urn, title))

    # Use founders if available, otherwise fall back to key executives
    urns_to_fetch = founder_urns if founder_urns else executive_urns

    # Fetch details for each person
    for person_urn, title in urns_to_fetch:
        if "person:" in person_urn:
            person_id = person_urn.split("person:")[-1]
            try:
                person = client.get_person(person_id)
                if person and person.name not in seen_names:
                    founder = Founder(
                        company_id=normalized_id,
                        name=person.name,
                        role_title=title or person.title,
                        linkedin_url=person.linkedin_url,
                        background=None,
                        observed_at=datetime.utcnow().isoformat(),
                        source="harmonic",
                    )
                    founders_list.append(founder)
                    seen_names.add(person.name)
            except HarmonicAPIError as e:
                logger.warning(f"Could not fetch person {person_id}: {e}")

    if founders_list:
        logger.info(f"Fetched {len(founders_list)} founders for {normalized_id}")
    else:
        logger.warning(f"No founders found for {normalized_id}")

    return founders_list


# =============================================================================
# HELPER: Summarize founder background with LLM
# =============================================================================

def _summarize_website_updates(raw_content: str, company_name: str) -> str:
    """
    Use OpenAI to summarize website updates into 1-2 VC-relevant sentences.
    """
    import os
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage

    if not os.getenv("ANTHROPIC_API_KEY"):
        return raw_content[:200]

    system_prompt = """You are a VC research assistant. Summarize website updates into 1-2 sentences.
Focus on what matters to investors: product launches, partnerships, funding, growth signals, market expansion.
Skip technical details, API changes, and developer documentation.
If the content is mostly technical/irrelevant, say "No significant business updates detected."
Be concise and factual."""

    user_prompt = f"""Summarize these recent website updates for {company_name} in 1-2 sentences for a VC investor:

{raw_content}

Summary:"""

    try:
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        return response.content.strip()
    except Exception as e:
        logger.warning(f"LLM summarization failed for website updates: {e}")
        return raw_content[:200]


def _summarize_news_article(
    headline: str,
    excerpts: str,
    outlet: str,
    company_name: str,
) -> str:
    """
    Use OpenAI to summarize a news article into 1-2 VC-relevant sentences.

    Args:
        headline: Article headline
        excerpts: Article excerpts/content
        outlet: News outlet name
        company_name: Company the article is about

    Returns:
        1-2 sentence VC-relevant summary
    """
    import os
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage

    if not os.getenv("ANTHROPIC_API_KEY"):
        return headline[:200] if headline else excerpts[:200]

    system_prompt = """You are a VC research assistant. Summarize news articles into 1-2 sentences.
Focus on what matters to investors: funding, acquisitions, product launches, partnerships, executive changes, market expansion, competitive moves.
Skip generic company descriptions and boilerplate content.
Be concise and factual. Start with the key news, not the company name."""

    user_prompt = f"""Summarize this news article about {company_name} in 1-2 sentences for a VC investor:

Headline: {headline}
Source: {outlet}

Content:
{excerpts}

Summary:"""

    try:
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        return response.content.strip()
    except Exception as e:
        logger.warning(f"LLM summarization failed for news article: {e}")
        return headline[:200] if headline else excerpts[:200]


def _summarize_founder_background(
    name: str,
    role_title: str,
    raw_background: str,
    company_name: str,
) -> str:
    """
    Use OpenAI to create a concise founder background summary.

    Args:
        name: Founder name
        role_title: Current role at the company
        raw_background: Raw background text from Swarm
        company_name: Current company name (to exclude from summary)

    Returns:
        Concise 2-4 sentence summary focused on prior experience
    """
    import os
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage
    from core.llm_validation import validate_founder_summary, LLMResponseError

    # Skip if no Anthropic key
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set - skipping LLM summarization")
        return raw_background

    system_prompt = """You are a VC research assistant creating concise founder backgrounds.
Your task is to summarize a founder's background as 2-3 short bullet points.

Rules:
- Focus on PRIOR experience (not their current role - that's already displayed elsewhere)
- Each bullet = one key fact (notable employer, education, prior exit, etc.)
- Skip: current role details, generic skills lists, redundant info
- Be terse — 5-10 words per bullet
- If they were at notable companies (Google, Meta, OpenAI, etc.), mention it
- If they have a technical background (PhD, engineering), mention it
- If they previously founded or exited a company, mention it
- Output ONLY the bullet points, no intro text"""

    user_prompt = f"""Summarize this founder's background for a VC meeting brief.

Founder: {name}
Current Role: {role_title} at {company_name}

Raw Background Data:
{raw_background}

Write 2-3 bullet points (•) focusing on their PRIOR experience and credentials (not their current role at {company_name}). Each bullet should be 5-10 words."""

    try:
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)

        # Validate the LLM output before returning
        # This catches empty, echoed, or error responses
        validated_summary = validate_founder_summary(
            response.content,
            founder_name=name,
            raw_background=raw_background,
        )
        return validated_summary

    except LLMResponseError as e:
        # Validation failed - fall back to raw background
        logger.warning(
            f"LLM summary validation failed for {name} ({e.error_type}): {e}. "
            "Using raw background."
        )
        return raw_background
    except Exception as e:
        logger.warning(f"LLM summarization failed for {name}: {e}")
        return raw_background


# =============================================================================
# TOOL 2b: enrich_founder_backgrounds (Harmonic)
# =============================================================================

def _format_harmonic_background(person_data: dict, current_company: Optional[str] = None) -> str:
    """
    Format a founder background from Harmonic person data.

    Converts experience, education, and highlights into readable text.

    Args:
        person_data: Raw Harmonic person API response
        current_company: Name of current company to exclude from background

    Returns:
        Formatted background string
    """
    sections = []

    # Extract experience (skip current position at current_company)
    experience = person_data.get("experience", []) or []
    prior_experience = []

    for exp in experience:
        company_name = exp.get("company_name", exp.get("companyName", ""))
        title = exp.get("title", "")
        is_current = exp.get("is_current_position", False)

        # Skip if this is current role at the company we're analyzing
        if is_current and current_company and company_name and current_company.lower() in company_name.lower():
            continue

        if title and company_name:
            date_range = []
            start = exp.get("start_date", exp.get("startDate"))
            end = exp.get("end_date", exp.get("endDate"))

            if start:
                date_range.append(start)
            if end:
                date_range.append(end)
            elif is_current:
                date_range.append("Present")

            date_str = " - ".join(date_range) if date_range else ""
            exp_line = f"{title} at {company_name}"
            if date_str:
                exp_line += f" ({date_str})"

            prior_experience.append(exp_line)

    if prior_experience:
        # Limit to top 3-4 most recent positions
        sections.append("Experience:\n" + "\n".join(f"• {exp}" for exp in prior_experience[:4]))

    # Extract education
    education = person_data.get("education", []) or []
    education_lines = []

    for edu in education:
        school = edu.get("school", "")
        degree = edu.get("degree", "")
        field = edu.get("field", edu.get("field_of_study", ""))

        if school:
            edu_parts = []
            if degree:
                edu_parts.append(degree)
            if field:
                edu_parts.append(field)

            edu_line = ", ".join(edu_parts) if edu_parts else "Studied"
            edu_line += f" - {school}"

            start_year = edu.get("start_year", edu.get("startYear"))
            end_year = edu.get("end_year", edu.get("endYear"))
            if start_year or end_year:
                years = []
                if start_year:
                    years.append(str(start_year))
                if end_year:
                    years.append(str(end_year))
                edu_line += f" ({'-'.join(years)})"

            education_lines.append(edu_line)

    if education_lines:
        sections.append("Education:\n" + "\n".join(f"• {edu}" for edu in education_lines[:3]))

    # Extract highlights (achievements, awards, publications)
    highlights = person_data.get("highlights", []) or []
    highlight_lines = []

    for highlight in highlights[:5]:  # Limit to top 5
        highlight_text = highlight.get("text", "")
        highlight_type = highlight.get("type", "")

        if highlight_text:
            if highlight_type and highlight_type != "OTHER":
                highlight_lines.append(f"{highlight_type}: {highlight_text}")
            else:
                highlight_lines.append(highlight_text)

    if highlight_lines:
        sections.append("Highlights:\n" + "\n".join(f"• {h}" for h in highlight_lines))

    # If we have no meaningful data, return empty
    if not sections:
        return ""

    return "\n\n".join(sections)


def enrich_founder_backgrounds(company_id: str, summarize: bool = True) -> dict:
    """
    Enrich founder backgrounds using Harmonic API with batch fetching.

    Fetches detailed profile information for all founders in a single batch
    API call, then updates the founders table with background text and sources.

    Args:
        company_id: Company URL or domain
        summarize: If True, use OpenAI to create concise summaries (default: True)

    Returns:
        Dict with enrichment results:
        {
            "company_id": str,
            "enriched_count": int,
            "skipped_count": int,
            "failed_count": int,
            "founders": list[dict],
        }
    """
    normalized_id = normalize_company_id(company_id)

    # Get existing founders from Supabase
    founders = read_founders_from_supabase(normalized_id)

    if not founders:
        logger.info(f"No founders found in Supabase for {normalized_id}")
        return {
            "company_id": normalized_id,
            "enriched_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "founders": [],
        }

    # Get company name for context
    company = read_company_from_supabase(normalized_id)
    company_name = company.company_name if company else None

    results = {
        "company_id": normalized_id,
        "enriched_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "founders": [],
    }

    # Separate founders into those needing enrichment vs already enriched
    founders_to_enrich = []
    linkedin_urls_to_fetch = []

    for founder in founders:
        founder_result = {
            "name": founder.name,
            "status": "pending",
        }

        # Skip if already enriched (has meaningful background)
        if founder.background and len(founder.background) > 50:
            founder_result["status"] = "skipped"
            founder_result["reason"] = "Already has background"
            results["skipped_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Collect for batch enrichment
        founders_to_enrich.append((founder, founder_result))
        if founder.linkedin_url:
            linkedin_urls_to_fetch.append(founder.linkedin_url)

    # If no founders need enrichment, return early
    if not founders_to_enrich:
        logger.info(f"All founders already enriched for {normalized_id}")
        return results

    # BATCH FETCH: Get all profiles in one API call from Harmonic
    harmonic = HarmonicClient()
    persons_by_url: dict[str, HarmonicPerson] = {}

    if linkedin_urls_to_fetch:
        logger.info(f"Batch fetching {len(linkedin_urls_to_fetch)} LinkedIn profiles from Harmonic for {normalized_id}")
        try:
            persons_by_url = harmonic.batch_lookup_persons(linkedin_urls_to_fetch)
            logger.info(f"Batch fetch returned {len(persons_by_url)} profiles from Harmonic")
        except HarmonicAPIError as e:
            logger.error(f"Batch Harmonic fetch failed: {e}")

    # Process each founder with the fetched profiles
    for founder, founder_result in founders_to_enrich:
        person: Optional[HarmonicPerson] = None

        # Try to find person by LinkedIn URL (normalized matching)
        if founder.linkedin_url:
            normalized_url = founder.linkedin_url.lower().rstrip('/')
            person = persons_by_url.get(normalized_url)

            # Try alternative normalizations if not found
            if not person:
                # Try without trailing slash
                alt_url = founder.linkedin_url.rstrip('/')
                person = persons_by_url.get(alt_url.lower())

            # Try with www prefix if needed
            if not person and not founder.linkedin_url.startswith('www.'):
                www_url = founder.linkedin_url.replace('://', '://www.')
                person = persons_by_url.get(www_url.lower().rstrip('/'))

        # Fallback: try individual lookup if not in batch results
        if not person and founder.linkedin_url:
            try:
                logger.info(f"Batch didn't find {founder.name}, trying individual lookup")
                person = harmonic.lookup_person(founder.linkedin_url)
            except HarmonicAPIError as e:
                logger.warning(f"Individual Harmonic lookup failed for {founder.name}: {e}")

        if not person:
            founder_result["status"] = "failed"
            founder_result["reason"] = "Profile not found in Harmonic"
            results["failed_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Format background from Harmonic person data
        raw_background = _format_harmonic_background(person.raw_data, current_company=company_name)

        if not raw_background or len(raw_background) < 20:
            founder_result["status"] = "failed"
            founder_result["reason"] = "No meaningful background data"
            results["failed_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Optionally summarize with LLM
        if summarize:
            background = _summarize_founder_background(
                name=founder.name,
                role_title=founder.role_title or "",
                raw_background=raw_background,
                company_name=company_name or "the company",
            )
        else:
            background = raw_background

        # Format sources (LinkedIn URL from Harmonic)
        sources = []
        if person.linkedin_url:
            sources.append({"network": "linkedin", "url": person.linkedin_url})

        sources_str = ""
        if sources:
            source_urls = [s["url"] for s in sources if s.get("url")]
            if source_urls:
                sources_str = "\n\n---\nSources: " + ", ".join(source_urls)

        # Combine background with sources
        full_background = background + sources_str if background else None

        if not full_background or len(full_background) < 20:
            founder_result["status"] = "failed"
            founder_result["reason"] = "No meaningful background data"
            results["failed_count"] += 1
            results["founders"].append(founder_result)
            continue

        # Update founder in database
        founder.background = full_background
        founder.source = "harmonic"
        founder.observed_at = datetime.utcnow().isoformat()

        # Also update LinkedIn URL if we found one and founder doesn't have it
        if person.linkedin_url and not founder.linkedin_url:
            founder.linkedin_url = person.linkedin_url

        sync_founders_to_supabase([founder], company_name=company_name)

        founder_result["status"] = "enriched"
        founder_result["sources"] = sources
        results["enriched_count"] += 1
        results["founders"].append(founder_result)

        logger.info(f"Enriched background for {founder.name} at {normalized_id}")

    logger.info(
        f"Founder enrichment complete for {normalized_id}: "
        f"enriched={results['enriched_count']}, "
        f"skipped={results['skipped_count']}, "
        f"failed={results['failed_count']}"
    )

    return results


# =============================================================================
# TOOL 3: get_recent_news
# =============================================================================

def get_recent_news(company_id: str, days: int = 30) -> list[NewsArticle]:
    """
    Fetch recent news articles for a company via Parallel Search.

    STATUS: IMPLEMENTED (Parallel Search)

    Args:
        company_id: Company URL or domain
        days: Number of days to look back (not currently used by Parallel Search)

    Returns:
        List of NewsArticle objects
    """
    normalized_id = normalize_company_id(company_id)

    parallel = get_parallel_client()
    if parallel is None:
        logger.info(f"get_recent_news: PARALLEL_API_KEY not set, skipping for {normalized_id}")
        return []

    # Resolve company name for search
    company_name = None
    existing = read_company_from_supabase(normalized_id)
    if existing:
        company_name = existing.company_name
    if not company_name:
        # Fall back to domain hint
        company_name = normalized_id.split(".")[0]

    try:
        results = parallel.search_company_news(company_name, max_results=10)
    except ParallelSearchError as e:
        logger.error(f"Parallel Search failed for {normalized_id}: {e}")
        return []

    # Transform to NewsArticle DB models
    articles: list[NewsArticle] = []
    for r in results:
        # Clean and join excerpts for LLM context
        if r.excerpts:
            cleaned_excerpts = []
            for excerpt in r.excerpts:
                cleaned = _clean_excerpt(excerpt, max_chars=500)
                if cleaned:
                    cleaned_excerpts.append(cleaned)
            excerpts_text = "\n".join(cleaned_excerpts) if cleaned_excerpts else None
        else:
            excerpts_text = None
        articles.append(NewsArticle(
            company_id=normalized_id,
            article_headline=r.title,
            outlet=r.source_domain,
            url=r.url,
            published_date=r.publish_date,
            excerpts=excerpts_text,
            observed_at=datetime.utcnow().isoformat(),
            source="parallel",
        ))

    # Generate synopsis and classify news type for each article
    if articles and company_name:
        logger.info(f"Generating synopsis for {len(articles)} news articles...")
        for article in articles:
            try:
                # Generate synopsis using LLM
                synopsis = _summarize_news_article(
                    headline=article.article_headline,
                    excerpts=article.excerpts or "",
                    outlet=article.outlet or "Unknown",
                    company_name=company_name,
                )
                article.synopsis = synopsis

                # Classify news type based on headline and excerpts
                excerpts_list = [article.excerpts] if article.excerpts else []
                article.news_type = _classify_signal_type(article.article_headline, excerpts_list)

                # Simple sentiment classification based on keywords
                headline_lower = article.article_headline.lower()
                if any(w in headline_lower for w in ["raises", "funding", "growth", "launches", "partnership", "expands"]):
                    article.sentiment = "positive"
                elif any(w in headline_lower for w in ["layoffs", "lawsuit", "decline", "fails", "shuts down"]):
                    article.sentiment = "negative"
                else:
                    article.sentiment = "neutral"

            except Exception as e:
                logger.warning(f"Failed to generate synopsis for '{article.article_headline[:50]}': {e}")

    if articles:
        logger.info(f"Fetched {len(articles)} news articles for {normalized_id}")

    return articles


# =============================================================================
# TOOL 4: get_key_signals
# =============================================================================

def get_key_signals(company_id: str) -> list[KeySignal]:
    """
    Aggregate event-like signals and write to key_signals table.

    STATUS: PARTIALLY IMPLEMENTED
    - web_traffic_trend: Harmonic (IMPLEMENTED)
    - hiring_firing: Harmonic (IMPLEMENTED)
    - website_update: Tavily (NOT IMPLEMENTED)

    Args:
        company_id: Company URL or domain

    Returns:
        List of KeySignal objects from implemented sources
    """
    client = get_harmonic_client()

    normalized_id = normalize_company_id(company_id)

    url_type, normalized = parse_company_url(company_id)
    company: Optional[HarmonicCompany] = None

    try:
        if url_type == "company_domain":
            company = client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            company = client.lookup_company(linkedin_url=normalized)
        elif url_type == "person_linkedin":
            person = client.lookup_person(normalized)
            if person and person.raw_data:
                experience = person.raw_data.get("experience", []) or []
                for exp in experience:
                    if exp.get("is_current_position"):
                        company_urn = exp.get("company_urn")
                        if company_urn and "company:" in company_urn:
                            company_id_from_urn = company_urn.split("company:")[-1]
                            company = client.get_company(company_id_from_urn)
                            break
    except HarmonicAPIError as e:
        logger.error(f"Harmonic API error for {company_id}: {e}")
        raise ValueError(f"Failed to fetch company from Harmonic: {e}")

    if not company:
        raise ValueError(f"Company not found in Harmonic for: {company_id}")

    signals: list[KeySignal] = []
    now = datetime.utcnow().isoformat()

    # Signal: Web Traffic Trend
    if company.web_traffic_change_30d is not None:
        trend = company.web_traffic_change_30d
        if trend > 20:
            description = f"Strong traffic growth: +{trend:.1f}% in 30 days"
        elif trend > 0:
            description = f"Traffic growing: +{trend:.1f}% in 30 days"
        elif trend > -20:
            description = f"Traffic declining: {trend:.1f}% in 30 days"
        else:
            description = f"Significant traffic decline: {trend:.1f}% in 30 days"

        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="web_traffic",
            description=description,
            observed_at=now,
            source="harmonic",
        ))

    # Signal: Hiring/Firing
    if company.headcount_change_90d is not None:
        change = company.headcount_change_90d
        if change > 10:
            description = f"Rapid hiring: +{change:.1f}% headcount in 90 days ({company.headcount:,} employees)"
        elif change > 0:
            description = f"Growing team: +{change:.1f}% headcount in 90 days ({company.headcount:,} employees)"
        elif change > -10:
            description = f"Team contraction: {change:.1f}% headcount in 90 days ({company.headcount:,} employees)"
        else:
            description = f"Significant layoffs: {change:.1f}% headcount in 90 days ({company.headcount:,} employees)"

        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="hiring",
            description=description,
            observed_at=now,
            source="harmonic",
        ))

    # Signal: Funding
    if company.funding_last_date and company.funding_last_amount:
        # Format date from ISO timestamp (e.g. "2025-06-18T00:00:00Z") to "June 18, 2025"
        try:
            from datetime import datetime as _dt
            raw_date = company.funding_last_date
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    parsed = _dt.strptime(raw_date, fmt)
                    formatted_date = parsed.strftime("%B %-d, %Y")
                    break
                except ValueError:
                    continue
            else:
                formatted_date = raw_date
        except Exception:
            formatted_date = company.funding_last_date
        description = f"Last funding: ${company.funding_last_amount:,.0f} on {formatted_date}"
        if company.funding_stage:
            description += f" ({company.funding_stage})"

        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="funding",
            description=description,
            observed_at=now,
            source="harmonic",
        ))

    # Signal: Website Intelligence (Tavily Crawl)
    tavily = get_tavily_client()
    if tavily is not None:
        try:
            # Ensure URL is properly formatted for crawl
            url = normalized_id if normalized_id.startswith(("http://", "https://")) else f"https://{normalized_id}"
            intel = tavily.crawl_company_website(url)

            # VC-relevant signal types to include
            vc_relevant_types = {"product_update", "funding_news", "partnership", "team_change"}

            # Collect and filter signals
            relevant_updates = []
            for sig in intel.signals:
                desc = sig.get("description", "")

                # Skip non-English content (check for common non-ASCII patterns)
                if any(ord(c) > 127 for c in desc[:50]):
                    continue

                # Skip junk content
                junk_patterns = ["opens in a new tab", "opens in a new window", "Read more",
                                 "newsletter", "Subscribe", "inbox", "cookie"]
                if any(p.lower() in desc.lower() for p in junk_patterns):
                    continue

                # Clean and truncate
                clean_desc = _clean_excerpt(desc, max_chars=150)
                if clean_desc and len(clean_desc) > 30:
                    relevant_updates.append({
                        "type": sig["type"],
                        "desc": clean_desc
                    })

            # Create ONE consolidated website signal for VCs
            if relevant_updates:
                # Prioritize: funding > product > partnership > team > general
                priority_order = ["funding_news", "product_update", "partnership", "team_change", "general_update"]
                relevant_updates.sort(key=lambda x: priority_order.index(x["type"]) if x["type"] in priority_order else 99)

                # Take top 5 updates for LLM summarization
                top_updates = relevant_updates[:5]
                raw_content = "\n".join([f"- {u['desc']}" for u in top_updates])

                # Use LLM to create VC-friendly summary
                summary = _summarize_website_updates(raw_content, company.name if company else normalized_id)

                signals.append(KeySignal(
                    company_id=normalized_id,
                    signal_type="website_update",
                    description=summary,
                    observed_at=now,
                    source="tavily",
                ))

                logger.info(f"Tavily: {len(relevant_updates)} relevant signals for {normalized_id}")

            # Update website_update field on briefing_companies (Supabase)
            if relevant_updates:
                summary = f"{len(relevant_updates)} website updates detected"
                patch_company_website_update(normalized_id, summary)
        except TavilyAPIError as e:
            logger.error(f"Tavily API error for {normalized_id}: {e}")
        except Exception as e:
            logger.error(f"Tavily unexpected error for {normalized_id}: {type(e).__name__}: {e}")
    else:
        signals.append(KeySignal(
            company_id=normalized_id,
            signal_type="website_update",
            description="Website change detection not yet available (TAVILY_API_KEY not set)",
            observed_at=now,
            source="pending_tavily",
        ))

    # Note: News from Parallel Search is stored separately in the news table
    # via get_recent_news(). We don't duplicate it as signals here.

    if signals:
        logger.info(f"Fetched {len(signals)} signals for {normalized_id}")

    return signals


# =============================================================================
# TOOL 5a: get_competitors
# =============================================================================

# Heuristics for startup vs incumbent classification
_INCUMBENT_STAGES = {
    "public", "ipo", "post_ipo_equity", "post_ipo_debt", "post_ipo_secondary", "acquired"
}
_INCUMBENT_HEADCOUNT_THRESHOLD = 500
_INCUMBENT_FOUNDED_BEFORE = 2010


def _classify_competitor_type(company: HarmonicCompany) -> str:
    """Classify a competitor as 'startup' or 'incumbent' using simple heuristics."""
    stage = (company.funding_stage or "").lower().replace(" ", "_").replace("-", "_")
    if stage in _INCUMBENT_STAGES:
        return "incumbent"
    if company.headcount and company.headcount >= _INCUMBENT_HEADCOUNT_THRESHOLD:
        return "incumbent"
    if company.founded_year and company.founded_year < _INCUMBENT_FOUNDED_BEFORE:
        return "incumbent"
    return "startup"


def _first_sentence(text: str) -> str:
    """Return the first complete sentence of text."""
    import re
    match = re.search(r'.+?[.!?](?:\s|$)', text)
    return match.group(0).strip() if match else text.strip()


def get_competitors(company_id: str, max_per_type: int = 3) -> list[CompetitorSnapshot]:
    """
    Fetch top startup and incumbent competitors via Harmonic's similar_companies endpoint.

    Steps:
    1. Look up the company in Harmonic to get its internal ID
    2. Call find_similar_companies() to get similar companies
    3. Classify each as startup or incumbent
    4. Return top max_per_type of each type
    5. Sync to Supabase briefing_competitors table

    Args:
        company_id: Company URL or domain
        max_per_type: Max competitors to return per type (startup/incumbent)

    Returns:
        List of CompetitorSnapshot objects (up to max_per_type * 2 total)
    """
    normalized_id = normalize_company_id(company_id)
    client = get_harmonic_client()

    # Step 1: Resolve Harmonic internal ID (not stored in CompanyCore)
    try:
        url_type, normalized = parse_company_url(company_id)
        if url_type == "company_domain":
            hc_subject = client.lookup_company(domain=normalized)
        elif url_type == "company_linkedin":
            hc_subject = client.lookup_company(linkedin_url=normalized)
        else:
            hc_subject = client.lookup_company(domain=normalized_id)
    except HarmonicAPIError as e:
        logger.warning(f"Harmonic lookup failed for {normalized_id}: {e}")
        return []

    if not hc_subject or not hc_subject.id:
        logger.warning(f"No Harmonic record found for {normalized_id}")
        return []

    # Step 2: Fetch similar company URNs then resolve each to full HarmonicCompany
    # The endpoint returns URNs like 'urn:harmonic:company:1858', not full objects
    try:
        resp = client._request(
            "GET",
            f"/search/similar_companies/{hc_subject.id}",
            params={"page_size": max_per_type * 5},
        )
        similar_urns = resp.get("results", [])
    except Exception as e:
        logger.error(f"similar_companies request failed for {normalized_id}: {e}")
        return []

    if not similar_urns:
        logger.info(f"No similar companies returned by Harmonic for {normalized_id}")
        return []

    # Resolve URNs to full company objects
    similar: list[HarmonicCompany] = []
    for urn in similar_urns:
        if not (isinstance(urn, str) and ":" in urn):
            continue
        comp_harmonic_id = urn.split(":")[-1]
        try:
            hc = client.get_company(comp_harmonic_id)
            if hc:
                similar.append(hc)
        except Exception:
            continue

    # Step 3: Classify and bucket
    startups: list[CompetitorSnapshot] = []
    incumbents: list[CompetitorSnapshot] = []

    for hc in similar:
        ctype = _classify_competitor_type(hc)
        snapshot = CompetitorSnapshot(
            company_id=normalized_id,
            competitor_name=hc.name,
            competitor_domain=hc.domain,
            competitor_type=ctype,
            description=_first_sentence(hc.description) if hc.description else None,
            funding_total=hc.funding_total,
            funding_stage=hc.funding_stage,
            funding_last_amount=hc.funding_last_amount,
            funding_last_date=hc.funding_last_date,
            headcount=hc.headcount,
            tags=", ".join(hc.tags[:5]) if hc.tags else None,
            harmonic_id=hc.id,
        )
        if ctype == "startup":
            startups.append(snapshot)
        else:
            incumbents.append(snapshot)

    # Step 4: Sort by headcount as relevance proxy, take top N per type
    startups.sort(key=lambda c: c.headcount or 0, reverse=True)
    incumbents.sort(key=lambda c: c.headcount or 0, reverse=True)
    result = startups[:max_per_type] + incumbents[:max_per_type]

    # Step 5: Sync to Supabase
    if result:
        try:
            sync_competitors_to_supabase(result)
        except Exception as e:
            logger.error(f"Failed to sync competitors to Supabase for {normalized_id}: {e}")

    logger.info(
        f"Fetched {len(startups[:max_per_type])} startup and "
        f"{len(incumbents[:max_per_type])} incumbent competitors for {normalized_id}"
    )
    return result


# =============================================================================
# TOOL 5: ingest_company
# =============================================================================

# How long a briefing_companies row stays "fresh" before re-ingesting.
# Override with the INGEST_TTL_HOURS env var.
_DEFAULT_INGEST_TTL_HOURS = 24


def _ingest_ttl_hours() -> int:
    raw = os.environ.get("INGEST_TTL_HOURS")
    if not raw:
        return _DEFAULT_INGEST_TTL_HOURS
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            f"Invalid INGEST_TTL_HOURS={raw!r}, falling back to {_DEFAULT_INGEST_TTL_HOURS}"
        )
        return _DEFAULT_INGEST_TTL_HOURS


def _briefing_freshness(normalized_id: str) -> Optional[datetime]:
    """Return observed_at for the briefing_companies row, or None on miss/error."""
    try:
        from core.clients.supabase_client import get_supabase
        supabase = get_supabase()
        result = (
            supabase.table("briefing_companies")
            .select("observed_at")
            .eq("company_id", normalized_id)
            .order("observed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        raw = result.data[0].get("observed_at")
        if not raw:
            return None
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception as e:
        logger.warning(f"TTL freshness check failed for {normalized_id}: {e}")
        return None


def _cached_ingest_result(normalized_id: str, observed_at: datetime) -> dict:
    """Build the same shape as a full ingest from already-cached Supabase data."""
    try:
        bundle = get_company_bundle_from_supabase(normalized_id)
    except Exception as e:
        logger.warning(f"get_company_bundle_from_supabase failed for {normalized_id}: {e}")
        bundle = None

    company_core = bundle.company_core if bundle else None
    return {
        "company_id": normalized_id,
        "company_name": company_core.company_name if company_core else None,
        "company_core": company_core is not None,
        "founders_count": len(bundle.founders) if bundle else 0,
        "founders_enriched": 0,
        "signals_count": len(bundle.key_signals) if bundle else 0,
        "news_count": len(bundle.news) if bundle else 0,
        "competitors_count": 0,
        "errors": [],
        "cached": True,
        "observed_at": observed_at.isoformat(),
    }


async def _ingest_company_async(
    company_id: str,
    user: Optional[str] = None,
    enrich_backgrounds: bool = True,
    force_refresh: bool = False,
) -> dict:
    """Concurrent ingest: fan out the 5 independent external fetches via asyncio.gather."""
    normalized_id = normalize_company_id(company_id)
    tracker = get_tracker()

    # TTL freshness check — skip external calls when briefing is recent
    if not force_refresh:
        observed_at = _briefing_freshness(normalized_id)
        if observed_at is not None:
            ttl_hours = _ingest_ttl_hours()
            now_utc = datetime.now(timezone.utc)
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            age = now_utc - observed_at
            if age < timedelta(hours=ttl_hours):
                logger.info(
                    f"Briefing for {normalized_id} is fresh "
                    f"(observed_at={observed_at.isoformat()}, age={age}, ttl={ttl_hours}h), "
                    f"skipping ingest"
                )
                return _cached_ingest_result(normalized_id, observed_at)

    results = {
        "company_id": normalized_id,
        "company_name": None,
        "company_core": False,
        "founders_count": 0,
        "founders_enriched": 0,
        "signals_count": 0,
        "news_count": 0,
        "competitors_count": 0,
        "errors": [],
    }

    # All five external fetches run concurrently — each only takes company_id.
    # get_competitors internally calls sync_competitors_to_supabase, so no
    # separate write step is needed for competitors.
    profile_r, founders_r, signals_r, news_r, competitors_r = await asyncio.gather(
        asyncio.to_thread(get_company_profile, company_id),
        asyncio.to_thread(get_founders, company_id),
        asyncio.to_thread(get_key_signals, company_id),
        asyncio.to_thread(get_recent_news, company_id),
        asyncio.to_thread(get_competitors, company_id),
        return_exceptions=True,
    )

    # Profile is required — bail if it failed.
    if isinstance(profile_r, Exception):
        results["errors"].append(f"Company profile: {profile_r}")
        logger.error(f"Failed to ingest company profile for {company_id}: {profile_r}")
        return results

    company_core = profile_r
    results["company_name"] = company_core.company_name
    results["company_core"] = True

    # Stage Supabase writes for parallel execution.
    write_tasks: list = [asyncio.to_thread(sync_company_to_supabase, company_core)]

    if isinstance(founders_r, Exception):
        results["errors"].append(f"Founders: {founders_r}")
        logger.error(f"Failed to ingest founders for {company_id}: {founders_r}")
        founders = []
    else:
        founders = founders_r
        results["founders_count"] = len(founders)
        if founders:
            write_tasks.append(
                asyncio.to_thread(
                    sync_founders_to_supabase, founders, company_name=results.get("company_name")
                )
            )

    if isinstance(signals_r, Exception):
        results["errors"].append(f"Signals: {signals_r}")
        logger.error(f"Failed to ingest signals for {company_id}: {signals_r}")
    else:
        results["signals_count"] = len(signals_r)
        if signals_r:
            write_tasks.append(asyncio.to_thread(sync_signals_to_supabase, signals_r))

    if isinstance(news_r, Exception):
        results["errors"].append(f"News: {news_r}")
        logger.error(f"Failed to ingest news for {company_id}: {news_r}")
    else:
        results["news_count"] = len(news_r)
        if news_r:
            write_tasks.append(asyncio.to_thread(sync_news_to_supabase, news_r, normalized_id))

    if isinstance(competitors_r, Exception):
        results["errors"].append(f"Competitors: {competitors_r}")
        logger.error(f"Failed to fetch competitors for {company_id}: {competitors_r}")
    else:
        results["competitors_count"] = len(competitors_r)

    # Run all Supabase writes concurrently. Founders sync must finish before
    # enrich_founder_backgrounds (which reads from Supabase), and gather()
    # waits for all tasks before returning.
    write_results = await asyncio.gather(*write_tasks, return_exceptions=True)
    write_labels = ["Company"] + (
        ["Founder"] if isinstance(founders_r, list) and founders_r else []
    ) + (
        ["Signals"] if not isinstance(signals_r, Exception) and signals_r else []
    ) + (
        ["News"] if not isinstance(news_r, Exception) and news_r else []
    )
    for label, wr in zip(write_labels, write_results):
        if isinstance(wr, Exception):
            results["errors"].append(f"{label} Supabase sync: {wr}")
            logger.error(f"{label} Supabase sync failed for {company_id}: {wr}")

    # Enrich backgrounds last — depends on founders being synced.
    if enrich_backgrounds and results["founders_count"] > 0:
        try:
            enrichment = await asyncio.to_thread(enrich_founder_backgrounds, company_id)
            results["founders_enriched"] = enrichment["enriched_count"]
        except Exception as e:
            results["errors"].append(f"Founder backgrounds: {str(e)}")
            logger.error(f"Failed to enrich founder backgrounds for {company_id}: {e}")

    logger.info(
        f"Ingestion complete for {results['company_name']}: "
        f"founders={results['founders_count']} (enriched={results['founders_enriched']}), "
        f"signals={results['signals_count']}, "
        f"news={results['news_count']}, "
        f"competitors={results['competitors_count']}"
    )

    tracker.log_usage(
        company_id=normalized_id,
        action="ingest",
        user=user,
        metadata={
            "founders_count": results["founders_count"],
            "founders_enriched": results["founders_enriched"],
            "signals_count": results["signals_count"],
            "competitors_count": results["competitors_count"],
            "errors": results["errors"],
        },
    )

    return results


def ingest_company(
    company_id: str,
    user: Optional[str] = None,
    enrich_backgrounds: bool = True,
    force_refresh: bool = False,
) -> dict:
    """
    Single entrypoint for company data ingestion.

    Orchestrates all data fetching and database writes.
    NO LLM calls - pure data ingestion.

    Args:
        company_id: Company URL or domain
        user: Optional user identifier for tracking
        enrich_backgrounds: If True (default), enrich founder backgrounds using Harmonic
        force_refresh: If True, bypass the TTL freshness check on briefing_companies

    Returns:
        Dict with ingestion results
    """
    # Sync wrapper: most callers (including the outreach generator) are sync.
    # asyncio.run creates a new event loop in the calling thread, which is safe
    # in the worker-thread context the generator runs under.
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is not None:
        # Caller is already in an event loop — schedule on it via a fresh task
        # in a thread to avoid nested-loop errors.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(
                lambda: asyncio.run(
                    _ingest_company_async(company_id, user, enrich_backgrounds, force_refresh)
                )
            ).result()

    return asyncio.run(
        _ingest_company_async(company_id, user, enrich_backgrounds, force_refresh)
    )


# =============================================================================
# TOOL 6: get_company_bundle
# =============================================================================

def get_company_bundle(company_id: str) -> CompanyBundle:
    """
    Read-only accessor for briefing generation. Pulls from Supabase only.

    Returns all stored data for a company. Does NOT fetch from APIs.

    Args:
        company_id: Company URL or domain

    Returns:
        CompanyBundle with all available data from Supabase
    """
    normalized_id = normalize_company_id(company_id)
    return get_company_bundle_from_supabase(normalized_id)
