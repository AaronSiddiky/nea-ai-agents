"""Database layer for news aggregator using Supabase PostgreSQL."""

import json
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, List

from core.clients.supabase_client import get_supabase


def _is_readonly_env() -> bool:
    """Detect read-only serverless environments (Vercel, AWS Lambda) where
    SQLite writes to the bundle path will fail."""
    return bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


@dataclass
class Investor:
    """An investor who tracks companies."""
    id: str
    name: str
    email: Optional[str] = None
    slack_id: Optional[str] = None
    is_active: bool = True
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()


@dataclass
class WatchedCompany:
    """A company being tracked for signals."""
    id: str
    company_id: str  # domain
    company_name: str
    category: str  # "portfolio" or "competitor"
    harmonic_id: Optional[str] = None
    parent_company_id: Optional[str] = None  # For competitors: links to portfolio company
    competitors_refreshed_at: Optional[str] = None  # When competitors were last fetched
    industry_tags: Optional[List[str]] = None  # List of industry tags
    is_active: bool = True
    added_at: str = None

    def __post_init__(self):
        if self.added_at is None:
            self.added_at = datetime.utcnow().isoformat()
        # Handle industry_tags from Supabase (comes as list) vs legacy (JSON string)
        if isinstance(self.industry_tags, str):
            try:
                self.industry_tags = json.loads(self.industry_tags)
            except (json.JSONDecodeError, TypeError):
                self.industry_tags = []

    @property
    def industries(self) -> List[str]:
        """Get industry tags as a list."""
        return self.industry_tags or []

    def competitors_need_refresh(self, days: int = 30) -> bool:
        """Check if competitors need to be refreshed (older than N days)."""
        if self.category != "portfolio":
            return False
        if not self.competitors_refreshed_at:
            return True
        refreshed = datetime.fromisoformat(self.competitors_refreshed_at.replace('Z', '+00:00'))
        return datetime.utcnow() - refreshed.replace(tzinfo=None) > timedelta(days=days)


@dataclass
class InvestorCompany:
    """Links investors to companies they track."""
    id: str
    investor_id: str
    company_id: str  # References WatchedCompany.id
    added_at: str = None

    def __post_init__(self):
        if self.added_at is None:
            self.added_at = datetime.utcnow().isoformat()


@dataclass
class EmployeeSnapshot:
    id: str
    company_id: str
    snapshot_date: str
    employees_json: str  # Keep as JSON string for compatibility
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

    @property
    def employees(self) -> List[dict]:
        return json.loads(self.employees_json) if self.employees_json else []


@dataclass
class CompanySignal:
    id: str
    company_id: str
    signal_type: str  # funding/team_change/product_launch/acquisition/partnership/news
    headline: str
    description: str
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    published_date: Optional[str] = None
    relevance_score: int = 0
    score_breakdown: Optional[dict] = None  # Dict (Supabase JSONB)
    raw_data: Optional[dict] = None  # Dict (Supabase JSONB)
    sentiment: Optional[str] = None  # "positive", "negative", or "neutral"
    synopsis: Optional[str] = None  # 1-2 sentence VC-relevant summary
    detected_at: str = None

    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.utcnow().isoformat()
        # Handle JSON strings from legacy code
        if isinstance(self.score_breakdown, str):
            try:
                self.score_breakdown = json.loads(self.score_breakdown)
            except (json.JSONDecodeError, TypeError):
                self.score_breakdown = None
        if isinstance(self.raw_data, str):
            try:
                self.raw_data = json.loads(self.raw_data)
            except (json.JSONDecodeError, TypeError):
                self.raw_data = None

    @property
    def raw_data_dict(self) -> dict:
        return self.raw_data or {}


# =============================================================================
# INVESTOR OPERATIONS
# =============================================================================

def add_investor(name: str, email: str = None, slack_id: str = None) -> Investor:
    """Add a new investor."""
    supabase = get_supabase()
    data = {
        "name": name,
        "email": email,
        "slack_id": slack_id,
        "is_active": True,
    }
    result = supabase.table("investors").insert(data).execute()
    row = result.data[0]
    return Investor(
        id=row["id"],
        name=row["name"],
        email=row.get("email"),
        slack_id=row.get("slack_id"),
        is_active=row.get("is_active", True),
        created_at=row.get("created_at"),
    )


def get_investor(investor_id: str = None, name: str = None) -> Optional[Investor]:
    """Get investor by ID or name."""
    supabase = get_supabase()
    query = supabase.table("investors").select("*")

    if investor_id:
        query = query.eq("id", investor_id)
    elif name:
        query = query.eq("name", name)
    else:
        return None

    result = query.execute()
    if not result.data:
        return None

    row = result.data[0]
    return Investor(
        id=row["id"],
        name=row["name"],
        email=row.get("email"),
        slack_id=row.get("slack_id"),
        is_active=row.get("is_active", True),
        created_at=row.get("created_at"),
    )


def get_investors(active_only: bool = True) -> List[Investor]:
    """Get all investors."""
    supabase = get_supabase()
    query = supabase.table("investors").select("*")

    if active_only:
        query = query.eq("is_active", True)

    result = query.execute()
    return [
        Investor(
            id=row["id"],
            name=row["name"],
            email=row.get("email"),
            slack_id=row.get("slack_id"),
            is_active=row.get("is_active", True),
            created_at=row.get("created_at"),
        )
        for row in result.data
    ]


def get_or_create_default_investor() -> Investor:
    """Get or create a default investor for single-user mode."""
    investor = get_investor(name="default")
    if not investor:
        investor = add_investor(name="default", email=None)
    return investor


# =============================================================================
# COMPANY OPERATIONS
# =============================================================================

def _row_to_company(row: dict) -> WatchedCompany:
    """Convert Supabase row to WatchedCompany."""
    return WatchedCompany(
        id=row["id"],
        company_id=row["company_id"],
        company_name=row["company_name"],
        category=row["category"],
        harmonic_id=row.get("harmonic_id"),
        parent_company_id=row.get("parent_company_id"),
        competitors_refreshed_at=row.get("competitors_refreshed_at"),
        industry_tags=row.get("industry_tags") or [],
        is_active=row.get("is_active", True),
        added_at=row.get("added_at"),
    )


def get_company_by_domain(domain: str) -> Optional[WatchedCompany]:
    """Get company by domain (company_id)."""
    supabase = get_supabase()
    result = supabase.table("watched_companies").select("*").eq("company_id", domain).execute()

    if not result.data:
        return None
    return _row_to_company(result.data[0])


def get_company_by_id(company_id: str) -> Optional[WatchedCompany]:
    """Get company by internal ID."""
    supabase = get_supabase()
    result = supabase.table("watched_companies").select("*").eq("id", company_id).execute()

    if not result.data:
        return None
    return _row_to_company(result.data[0])


def add_company(
    company_id: str,
    company_name: str,
    category: str,
    harmonic_id: str = None,
    parent_company_id: str = None,
    industry_tags: List[str] = None,
) -> WatchedCompany:
    """Add a company to the watchlist (or return existing)."""
    # Check if company already exists
    existing = get_company_by_domain(company_id)
    if existing:
        return existing

    supabase = get_supabase()
    data = {
        "company_id": company_id,
        "company_name": company_name,
        "category": category,
        "harmonic_id": harmonic_id,
        "parent_company_id": parent_company_id,
        "industry_tags": industry_tags or [],
        "is_active": True,
    }
    # M1b: bridge to canonical_entities
    try:
        from core.canonical_bridge import resolve_canonical_entity_id
        cid = resolve_canonical_entity_id(domain=company_id, harmonic_id=harmonic_id, name=company_name)
        if cid:
            data["canonical_entity_id"] = cid
    except Exception as _ex:
        pass

    result = supabase.table("watched_companies").insert(data).execute()
    return _row_to_company(result.data[0])


def link_investor_to_company(investor_id: str, company_id: str) -> InvestorCompany:
    """Link an investor to a company."""
    supabase = get_supabase()

    # Check if link already exists
    existing = supabase.table("investor_companies").select("*").eq(
        "investor_id", investor_id
    ).eq("company_id", company_id).execute()

    if existing.data:
        row = existing.data[0]
        return InvestorCompany(
            id=row["id"],
            investor_id=row["investor_id"],
            company_id=row["company_id"],
            added_at=row.get("added_at"),
        )

    data = {
        "investor_id": investor_id,
        "company_id": company_id,
    }
    result = supabase.table("investor_companies").insert(data).execute()
    row = result.data[0]
    return InvestorCompany(
        id=row["id"],
        investor_id=row["investor_id"],
        company_id=row["company_id"],
        added_at=row.get("added_at"),
    )


def unlink_investor_from_company(investor_id: str, company_id: str) -> bool:
    """Remove link between investor and company."""
    supabase = get_supabase()
    result = supabase.table("investor_companies").delete().eq(
        "investor_id", investor_id
    ).eq("company_id", company_id).execute()
    return len(result.data) > 0


def get_companies(
    active_only: bool = True,
    investor_id: str = None,
    category: str = None,
    parent_company_id: str = None
) -> List[WatchedCompany]:
    """Get watched companies with optional filters."""
    supabase = get_supabase()

    if investor_id:
        # Get companies for a specific investor via junction table
        # First get company IDs for this investor
        links = supabase.table("investor_companies").select("company_id").eq(
            "investor_id", investor_id
        ).execute()

        if not links.data:
            return []

        company_ids = [link["company_id"] for link in links.data]

        query = supabase.table("watched_companies").select("*").in_("id", company_ids)
    else:
        query = supabase.table("watched_companies").select("*")

    if active_only:
        query = query.eq("is_active", True)
    if category:
        query = query.eq("category", category)
    if parent_company_id:
        query = query.eq("parent_company_id", parent_company_id)

    result = query.execute()
    return [_row_to_company(row) for row in result.data]


def get_portfolio_companies(investor_id: str = None) -> List[WatchedCompany]:
    """Get only portfolio companies."""
    return get_companies(investor_id=investor_id, category="portfolio")


def get_competitors_for_company(parent_company_id: str) -> List[WatchedCompany]:
    """Get competitors linked to a portfolio company."""
    return get_companies(parent_company_id=parent_company_id, category="competitor")


def update_company(company_id: str, **updates) -> bool:
    """Update company fields."""
    if not updates:
        return False

    supabase = get_supabase()
    result = supabase.table("watched_companies").update(updates).eq("id", company_id).execute()
    return len(result.data) > 0


def update_company_harmonic_id(company_id: str, harmonic_id: str):
    """Update harmonic ID for a company."""
    update_company(company_id, harmonic_id=harmonic_id)


def update_competitors_refreshed(company_id: str):
    """Mark competitors as refreshed now."""
    update_company(company_id, competitors_refreshed_at=datetime.utcnow().isoformat())


def deactivate_company(company_id: str) -> bool:
    """Soft-delete a company by marking inactive."""
    return update_company(company_id, is_active=False)


def remove_company(company_id: str, hard_delete: bool = False) -> bool:
    """Remove a company (soft or hard delete)."""
    if not hard_delete:
        return deactivate_company(company_id)

    supabase = get_supabase()

    # Remove investor links
    supabase.table("investor_companies").delete().eq("company_id", company_id).execute()
    # Remove signals
    supabase.table("company_signals").delete().eq("company_id", company_id).execute()
    # Remove snapshots
    supabase.table("employee_snapshots").delete().eq("company_id", company_id).execute()
    # Remove company
    result = supabase.table("watched_companies").delete().eq("id", company_id).execute()

    return len(result.data) > 0


# =============================================================================
# SIGNAL OPERATIONS
# =============================================================================

def _row_to_signal(row: dict) -> CompanySignal:
    """Convert Supabase row to CompanySignal."""
    return CompanySignal(
        id=row["id"],
        company_id=row["company_id"],
        signal_type=row["signal_type"],
        headline=row["headline"],
        description=row.get("description", ""),
        source_url=row.get("source_url"),
        source_name=row.get("source_name"),
        published_date=row.get("published_date"),
        relevance_score=row.get("relevance_score", 0),
        score_breakdown=row.get("score_breakdown"),
        raw_data=row.get("raw_data"),
        sentiment=row.get("sentiment"),
        synopsis=row.get("synopsis"),
        detected_at=row.get("detected_at"),
    )


def save_signal(signal: CompanySignal) -> CompanySignal:
    """Save a signal to the database."""
    supabase = get_supabase()
    data = {
        "company_id": signal.company_id,
        "signal_type": signal.signal_type,
        "headline": signal.headline,
        "description": signal.description,
        "source_url": signal.source_url,
        "source_name": signal.source_name,
        "published_date": signal.published_date,
        "relevance_score": signal.relevance_score,
        "score_breakdown": signal.score_breakdown,
        "raw_data": signal.raw_data,
        "sentiment": signal.sentiment,
        "synopsis": signal.synopsis,
    }

    result = supabase.table("company_signals").insert(data).execute()
    return _row_to_signal(result.data[0])


def get_signals(
    company_id: str = None,
    signal_type: str = None,
    min_score: int = None,
    limit: int = 100,
    investor_id: str = None
) -> List[CompanySignal]:
    """Get signals with optional filters."""
    supabase = get_supabase()

    if investor_id:
        # Get signals for companies tracked by this investor
        links = supabase.table("investor_companies").select("company_id").eq(
            "investor_id", investor_id
        ).execute()

        if not links.data:
            return []

        company_ids = [link["company_id"] for link in links.data]
        query = supabase.table("company_signals").select("*").in_("company_id", company_ids)
    else:
        query = supabase.table("company_signals").select("*")

    if company_id:
        query = query.eq("company_id", company_id)
    if signal_type:
        query = query.eq("signal_type", signal_type)
    if min_score is not None:
        query = query.gte("relevance_score", min_score)

    query = query.order("relevance_score", desc=True).order("detected_at", desc=True).limit(limit)

    result = query.execute()
    return [_row_to_signal(row) for row in result.data]


def signal_exists(company_id: str, signal_type: str, headline: str) -> bool:
    """Check if a similar signal already exists (deduplication)."""
    supabase = get_supabase()
    result = supabase.table("company_signals").select("id").eq(
        "company_id", company_id
    ).eq("signal_type", signal_type).eq("headline", headline).execute()
    return len(result.data) > 0


# =============================================================================
# INDUSTRY NEWS OPERATIONS
# =============================================================================

# Common industry categories for VC-relevant news
INDUSTRY_CATEGORIES = {
    "fintech": ["fintech", "payments", "banking", "neobank", "lending", "insurtech"],
    "ai_ml": ["artificial intelligence", "machine learning", "AI", "ML", "deep learning", "LLM", "generative AI"],
    "saas": ["SaaS", "software as a service", "enterprise software", "B2B software"],
    "healthtech": ["healthtech", "healthcare", "digital health", "medtech", "biotech"],
    "ecommerce": ["ecommerce", "e-commerce", "retail tech", "DTC", "marketplace"],
    "cybersecurity": ["cybersecurity", "security", "infosec", "threat detection"],
    "devtools": ["developer tools", "devtools", "devops", "infrastructure", "cloud"],
    "crypto": ["crypto", "blockchain", "web3", "defi", "NFT"],
    "climate": ["climate tech", "cleantech", "sustainability", "renewable", "carbon"],
    "edtech": ["edtech", "education technology", "learning", "online education"],
}


def get_companies_by_industry(
    industry: str,
    active_only: bool = True,
) -> List[WatchedCompany]:
    """
    Get companies tagged with a specific industry.

    Args:
        industry: Industry tag to search for (e.g., "fintech", "ai_ml")
        active_only: Only return active companies

    Returns:
        List of WatchedCompany with matching industry tags
    """
    supabase = get_supabase()
    query = supabase.table("watched_companies").select("*").contains("industry_tags", [industry])

    if active_only:
        query = query.eq("is_active", True)

    result = query.execute()
    return [_row_to_company(row) for row in result.data]


def get_all_industries() -> List[str]:
    """
    Get all unique industry tags across watched companies.

    Returns:
        List of unique industry tag strings
    """
    supabase = get_supabase()
    result = supabase.table("watched_companies").select("industry_tags").not_.is_("industry_tags", "null").execute()

    # Collect unique tags from all JSONB arrays
    all_tags = set()
    for row in result.data:
        tags = row.get("industry_tags") or []
        if isinstance(tags, list):
            all_tags.update(tags)

    return sorted(list(all_tags))


def update_company_industries(company_id: str, industry_tags: List[str]) -> bool:
    """
    Update industry tags for a company.

    Args:
        company_id: Company internal ID
        industry_tags: List of industry tag strings

    Returns:
        True if updated successfully
    """
    return update_company(company_id, industry_tags=industry_tags or [])


def search_industry_news(
    industry: str,
    signal_types: List[str] = None,
    min_score: int = None,
    limit: int = 50,
) -> List[CompanySignal]:
    """
    Search for news signals across all companies in an industry.

    This enables broader market news monitoring beyond individual company tracking.
    Useful for identifying industry trends, competitive moves, and market signals.

    Args:
        industry: Industry tag to search for (e.g., "fintech", "ai_ml")
        signal_types: Optional filter for specific signal types
        min_score: Minimum relevance score filter
        limit: Maximum signals to return

    Returns:
        List of CompanySignal from companies in the specified industry,
        sorted by relevance score and detection time
    """
    # Get companies in this industry
    companies = get_companies_by_industry(industry)
    if not companies:
        return []

    company_ids = [c.id for c in companies]

    supabase = get_supabase()
    query = supabase.table("company_signals").select("*").in_("company_id", company_ids)

    if signal_types:
        query = query.in_("signal_type", signal_types)
    if min_score is not None:
        query = query.gte("relevance_score", min_score)

    query = query.order("relevance_score", desc=True).order("detected_at", desc=True).limit(limit)

    result = query.execute()
    return [_row_to_signal(row) for row in result.data]


def get_industry_signal_summary(industry: str, days: int = 7) -> dict:
    """
    Get a summary of signals for an industry over a time period.

    Args:
        industry: Industry tag to summarize
        days: Number of days to look back

    Returns:
        Dict with signal counts by type and top signals
    """
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    # Get companies in this industry
    companies = get_companies_by_industry(industry)
    if not companies:
        return {
            "industry": industry,
            "days": days,
            "company_count": 0,
            "signal_counts": {},
            "total_signals": 0,
            "top_signals": [],
        }

    company_ids = [c.id for c in companies]

    supabase = get_supabase()

    # Get signals for these companies within the time period
    result = supabase.table("company_signals").select("*").in_(
        "company_id", company_ids
    ).gte("detected_at", cutoff).order("relevance_score", desc=True).execute()

    signals = [_row_to_signal(row) for row in result.data]

    # Count by signal type
    signal_counts = {}
    for signal in signals:
        signal_counts[signal.signal_type] = signal_counts.get(signal.signal_type, 0) + 1

    # Top 10 signals
    top_signals = signals[:10]

    return {
        "industry": industry,
        "days": days,
        "company_count": len(companies),
        "signal_counts": signal_counts,
        "total_signals": len(signals),
        "top_signals": top_signals,
    }


# =============================================================================
# EMPLOYEE SNAPSHOT OPERATIONS
# =============================================================================

def save_employee_snapshot(company_id: str, employees: List[dict]) -> EmployeeSnapshot:
    """Save an employee snapshot."""
    supabase = get_supabase()
    data = {
        "company_id": company_id,
        "snapshot_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "employees": employees,  # JSONB in Supabase
    }

    result = supabase.table("employee_snapshots").insert(data).execute()
    row = result.data[0]

    return EmployeeSnapshot(
        id=row["id"],
        company_id=row["company_id"],
        snapshot_date=row["snapshot_date"],
        employees_json=json.dumps(row.get("employees") or []),
        created_at=row.get("created_at"),
    )


def get_latest_employee_snapshot(company_id: str) -> Optional[EmployeeSnapshot]:
    """Get the most recent employee snapshot for a company."""
    supabase = get_supabase()
    result = supabase.table("employee_snapshots").select("*").eq(
        "company_id", company_id
    ).order("snapshot_date", desc=True).limit(1).execute()

    if not result.data:
        return None

    row = result.data[0]
    return EmployeeSnapshot(
        id=row["id"],
        company_id=row["company_id"],
        snapshot_date=row["snapshot_date"],
        employees_json=json.dumps(row.get("employees") or []),
        created_at=row.get("created_at"),
    )


# =============================================================================
# STORY CACHE OPERATIONS
# =============================================================================

@dataclass
class CachedStory:
    """A cached story from digest generation."""
    id: str
    story_id: str  # Hash-based ID for deduplication
    primary_url: str
    primary_title: str
    other_urls: List[dict] = field(default_factory=list)  # [{url, source}, ...]
    classification: str = "GENERAL"
    sentiment_label: str = "Neutral"
    sentiment_score: int = 0
    sentiment_keywords: List[str] = field(default_factory=list)
    synopsis: str = ""
    company_id: str = ""
    company_name: str = ""
    company_category: str = ""
    parent_company_name: Optional[str] = None
    industry_tags: List[str] = field(default_factory=list)
    priority_score: float = 0.0
    priority_reasons: List[str] = field(default_factory=list)
    published_date: Optional[str] = None
    max_engagement: int = 0
    source_count: int = 0
    article_signal_ids: List[str] = field(default_factory=list)
    digest_generated_at: str = ""
    created_at: str = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()

    @classmethod
    def from_row(cls, row: dict) -> "CachedStory":
        """Create CachedStory from database row."""
        return cls(
            id=row["id"],
            story_id=row["story_id"],
            primary_url=row["primary_url"],
            primary_title=row["primary_title"],
            other_urls=row.get("other_urls") or [],
            classification=row.get("classification", "GENERAL"),
            sentiment_label=row.get("sentiment_label", "Neutral"),
            sentiment_score=row.get("sentiment_score", 0),
            sentiment_keywords=row.get("sentiment_keywords") or [],
            synopsis=row.get("synopsis", ""),
            company_id=row.get("company_id", ""),
            company_name=row.get("company_name", ""),
            company_category=row.get("company_category", ""),
            parent_company_name=row.get("parent_company_name"),
            industry_tags=row.get("industry_tags") or [],
            priority_score=row.get("priority_score", 0.0),
            priority_reasons=row.get("priority_reasons") or [],
            published_date=row.get("published_date"),
            max_engagement=row.get("max_engagement", 0),
            source_count=row.get("source_count", 0),
            article_signal_ids=row.get("article_signal_ids") or [],
            digest_generated_at=row.get("digest_generated_at", ""),
            created_at=row.get("created_at"),
        )


def _story_to_row(story: CachedStory) -> dict:
    data = {
        "story_id": story.story_id,
        "primary_url": story.primary_url,
        "primary_title": story.primary_title,
        "other_urls": story.other_urls,
        "classification": story.classification,
        "sentiment_label": story.sentiment_label,
        "sentiment_score": story.sentiment_score,
        "sentiment_keywords": story.sentiment_keywords,
        "synopsis": story.synopsis,
        "company_id": story.company_id,
        "company_name": story.company_name,
        "company_category": story.company_category,
        "parent_company_name": story.parent_company_name,
        "industry_tags": story.industry_tags,
        "priority_score": story.priority_score,
        "priority_reasons": story.priority_reasons,
        "published_date": story.published_date,
        "max_engagement": story.max_engagement,
        "source_count": story.source_count,
        "article_signal_ids": story.article_signal_ids,
        "digest_generated_at": story.digest_generated_at,
    }
    # M1b: bridge to canonical_entities (only if a company is attached)
    if story.company_id:
        try:
            from core.canonical_bridge import resolve_canonical_entity_id
            cid = resolve_canonical_entity_id(
                domain=story.company_id,
                name=story.company_name,
            )
            if cid:
                data["canonical_entity_id"] = cid
        except Exception:
            pass
    return data


def save_story(story: CachedStory) -> bool:
    """Save or update a cached story."""
    supabase = get_supabase()
    data = _story_to_row(story)

    # Upsert based on story_id
    supabase.table("stories").upsert(data, on_conflict="story_id").execute()
    return True


def save_stories_batch(stories: List[CachedStory], digest_generated_at: str) -> int:
    """Save multiple stories in a single transaction."""
    supabase = get_supabase()
    saved_count = 0

    for story in stories:
        story.digest_generated_at = digest_generated_at
        data = _story_to_row(story)
        supabase.table("stories").upsert(data, on_conflict="story_id").execute()
        saved_count += 1

    return saved_count


def get_stories(
    digest_generated_at: str = None,
    company_id: str = None,
    classification: str = None,
    limit: int = 100
) -> List[CachedStory]:
    """Get cached stories with optional filters."""
    supabase = get_supabase()
    query = supabase.table("stories").select("*")

    if digest_generated_at:
        query = query.eq("digest_generated_at", digest_generated_at)
    if company_id:
        query = query.eq("company_id", company_id)
    if classification:
        query = query.eq("classification", classification)

    query = query.order("priority_score", desc=True).limit(limit)

    result = query.execute()
    return [CachedStory.from_row(row) for row in result.data]


def get_latest_digest_timestamp() -> Optional[str]:
    """Get the timestamp of the most recent digest generation."""
    supabase = get_supabase()
    result = supabase.table("stories").select("digest_generated_at").order(
        "digest_generated_at", desc=True
    ).limit(1).execute()

    if not result.data:
        return None
    return result.data[0]["digest_generated_at"]


def get_stories_by_digest(digest_generated_at: str) -> List[CachedStory]:
    """Get all stories from a specific digest run."""
    return get_stories(digest_generated_at=digest_generated_at, limit=1000)


def delete_old_stories(keep_days: int = 30) -> int:
    """Delete stories older than N days.

    Note: For comprehensive cleanup across all agents, use
    services.history.cleanup_all() instead.
    """
    supabase = get_supabase()
    cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
    result = supabase.table("stories").delete().lt("created_at", cutoff).execute()
    return len(result.data)


def deduplicate_stories() -> dict:
    """
    Deduplicate stories that represent the same event.

    Finds stories with the same company + classification + week that should
    be merged. Keeps the one with highest priority score, merges URLs from
    others, then deletes the duplicates.

    Returns:
        Dict with stats: {merged: N, deleted: N}
    """
    import re
    from collections import defaultdict

    supabase = get_supabase()

    # Get all stories from the last 45 days
    cutoff = (datetime.utcnow() - timedelta(days=45)).isoformat()
    result = supabase.table("stories").select("*").gte("created_at", cutoff).execute()

    if not result.data:
        return {"merged": 0, "deleted": 0}

    # Helper to extract funding amount
    def extract_funding(title: str) -> str:
        if not title:
            return ""
        pattern = r'\$(\d+(?:\.\d+)?)\s*([BMK]|billion|million)?'
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            amount = match.group(1)
            unit = (match.group(2) or 'M').upper()[0]
            return f"${amount}{unit}"
        return ""

    # Helper to get week bucket
    def get_week(pub_date: str) -> str:
        if not pub_date:
            return ""
        try:
            # Handle various date formats
            date_str = pub_date.replace('Z', '+00:00')
            if 'T' not in date_str:
                date_str = f"{date_str}T00:00:00+00:00"
            dt = datetime.fromisoformat(date_str)
            return dt.strftime("%Y-W%W")
        except (ValueError, TypeError):
            return pub_date[:7] if pub_date else ""

    # Group stories by event key (company + classification)
    # For FUNDING and M&A stories, we cluster by company + classification only
    # (same event reported on different dates should still be merged)
    # For other types, we include the month to allow multiple distinct events
    groups = defaultdict(list)
    for row in result.data:
        company = row.get("company_id") or row.get("company_name", "").lower()
        classification = row.get("classification", "GENERAL")

        # For high-impact event types (funding, M&A, IPO), merge all stories
        # for the same company since there's usually only one major event
        if classification in ("FUNDING", "M&A", "IPO"):
            event_key = f"{company}|{classification}"
        else:
            # For other types, include month to allow multiple events
            month = get_week(row.get("published_date"))[:7] if row.get("published_date") else ""
            event_key = f"{company}|{classification}|{month}"
        groups[event_key].append(row)

    merged = 0
    deleted = 0

    # Helper to extract source name from URL
    def get_source_from_url(url: str) -> str:
        """Extract readable source name from URL."""
        if not url:
            return "News"
        try:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.lower().replace('www.', '')

            source_names = {
                'techcrunch.com': 'TechCrunch',
                'bloomberg.com': 'Bloomberg',
                'reuters.com': 'Reuters',
                'wsj.com': 'Wall Street Journal',
                'ft.com': 'Financial Times',
                'forbes.com': 'Forbes',
                'cnbc.com': 'CNBC',
                'theverge.com': 'The Verge',
                'wired.com': 'Wired',
                'venturebeat.com': 'VentureBeat',
                'axios.com': 'Axios',
                'theinformation.com': 'The Information',
                'businessinsider.com': 'Business Insider',
                'nytimes.com': 'NY Times',
                'news.ycombinator.com': 'Hacker News',
                'producthunt.com': 'Product Hunt',
                'crunchbase.com': 'Crunchbase',
                'pitchbook.com': 'PitchBook',
                'semafor.com': 'Semafor',
                'news.google.com': 'Google News',
            }

            for key, name in source_names.items():
                if key in domain:
                    return name

            # Fallback: capitalize domain
            name = domain.split('.')[0]
            return name.title() if name else "News"
        except Exception:
            return "News"

    # Process groups with duplicates
    for event_key, stories in groups.items():
        if len(stories) <= 1:
            continue

        # Sort by priority_score desc, then by source_count desc
        stories.sort(
            key=lambda s: (s.get("priority_score", 0), s.get("source_count", 0)),
            reverse=True
        )

        # Keep the best one, merge URLs from others
        best = stories[0]
        best_id = best["id"]
        best_primary_url = best.get("primary_url", "")

        # Collect all sources as {url, source} dicts (deduped by URL)
        all_sources = {}  # url -> {url, source}

        # Add primary URL of best story
        all_sources[best_primary_url] = {
            "url": best_primary_url,
            "source": get_source_from_url(best_primary_url)
        }

        # Add other_urls from best story (handle both old and new format)
        for item in (best.get("other_urls") or []):
            if isinstance(item, dict):
                url = item.get("url", "")
                source = item.get("source", get_source_from_url(url))
            else:
                url = item
                source = get_source_from_url(url)
            if url:
                all_sources[url] = {"url": url, "source": source}

        # Collect URLs from duplicates
        ids_to_delete = []
        for dup in stories[1:]:
            # Add primary URL
            dup_primary = dup.get("primary_url", "")
            if dup_primary:
                all_sources[dup_primary] = {
                    "url": dup_primary,
                    "source": get_source_from_url(dup_primary)
                }

            # Add other_urls (handle both formats)
            for item in (dup.get("other_urls") or []):
                if isinstance(item, dict):
                    url = item.get("url", "")
                    source = item.get("source", get_source_from_url(url))
                else:
                    url = item
                    source = get_source_from_url(url)
                if url:
                    all_sources[url] = {"url": url, "source": source}

            ids_to_delete.append(dup["id"])

        # Remove the best's own primary URL from other_urls
        all_sources.pop(best_primary_url, None)

        # Update the best story with merged sources
        merged_sources = list(all_sources.values())
        supabase.table("stories").update({
            "other_urls": merged_sources,
            "source_count": len(merged_sources) + 1,
        }).eq("id", best_id).execute()

        # Delete the duplicates
        for dup_id in ids_to_delete:
            supabase.table("stories").delete().eq("id", dup_id).execute()
            deleted += 1

        merged += 1

    return {"merged": merged, "deleted": deleted}


# =============================================================================
# EMBEDDING CACHE OPERATIONS
# Note: Embedding cache remains local for performance. Consider using
# pg_vector extension in Supabase for production vector search.
# =============================================================================

import sqlite3
from pathlib import Path

EMBEDDING_CACHE_PATH = Path(__file__).parent / "embedding_cache.db"


def _get_embedding_connection() -> sqlite3.Connection:
    """Get connection to local embedding cache."""
    conn = sqlite3.connect(str(EMBEDDING_CACHE_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_embedding_cache():
    """Initialize local embedding cache table."""
    conn = _get_embedding_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS embedding_cache (
            url_hash TEXT PRIMARY KEY,
            embedding BLOB NOT NULL,
            title TEXT,
            snippet TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_embedding_cache_created
        ON embedding_cache(created_at)
    """)
    conn.commit()
    conn.close()


# Initialize embedding cache on import, unless we're in a read-only serverless
# env (Vercel, Lambda) where the bundle path is not writable. The embedding
# cache is only used by GitHub-Actions-scheduled news refresh scripts; Vercel
# functions that import this module (e.g. digest) never read/write embeddings.
if not _is_readonly_env():
    _init_embedding_cache()


def get_cached_embedding(url_hash: str) -> Optional[bytes]:
    """
    Get cached embedding by URL hash.

    Args:
        url_hash: MD5 hash of the URL

    Returns:
        Embedding bytes if cached, None otherwise
    """
    if _is_readonly_env():
        return None
    conn = _get_embedding_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT embedding FROM embedding_cache WHERE url_hash = ?",
        (url_hash,)
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def save_embedding(
    url_hash: str,
    embedding: bytes,
    title: str = None,
    snippet: str = None
) -> bool:
    """
    Save embedding to cache.

    Args:
        url_hash: MD5 hash of the URL
        embedding: Embedding as bytes (numpy tobytes())
        title: Optional title for debugging
        snippet: Optional snippet for debugging

    Returns:
        True if saved successfully
    """
    if _is_readonly_env():
        return False
    conn = _get_embedding_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO embedding_cache
            (url_hash, embedding, title, snippet, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            url_hash,
            embedding,
            title[:200] if title else None,
            snippet[:500] if snippet else None,
            datetime.utcnow().isoformat(),
        ))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def delete_old_embeddings(keep_days: int = 30) -> int:
    """
    Delete embeddings older than N days.

    Args:
        keep_days: Days to keep (default 30)

    Returns:
        Number of deleted embeddings
    """
    if _is_readonly_env():
        return 0
    conn = _get_embedding_connection()
    cursor = conn.cursor()

    cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
    cursor.execute("DELETE FROM embedding_cache WHERE created_at < ?", (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    return deleted


def get_embedding_cache_stats() -> dict:
    """Get embedding cache statistics."""
    if _is_readonly_env():
        return {'count': 0, 'oldest': None, 'newest': None}
    conn = _get_embedding_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM embedding_cache")
    count = cursor.fetchone()[0]

    cursor.execute(
        "SELECT MIN(created_at), MAX(created_at) FROM embedding_cache"
    )
    row = cursor.fetchone()
    oldest = row[0] if row else None
    newest = row[1] if row else None

    conn.close()

    return {
        'count': count,
        'oldest': oldest,
        'newest': newest,
    }
