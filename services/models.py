"""
Pydantic models for API request/response schemas.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator


# =============================================================================
# REQUEST MODELS
# =============================================================================

class BriefingRequest(BaseModel):
    """Request to generate a new briefing."""
    url: str = Field(..., description="Company URL or domain (e.g., 'stripe.com')")


# =============================================================================
# RESPONSE MODELS
# =============================================================================

class CompanySnapshot(BaseModel):
    """Company core information."""
    company_name: str
    founded: Optional[str] = None
    hq: Optional[str] = None
    employees: Optional[int] = None
    products: Optional[str] = None
    customers: Optional[str] = None
    total_funding: Optional[float] = None
    last_round: Optional[str] = None


class FounderInfo(BaseModel):
    """Founder information."""
    name: str
    role: Optional[str] = None
    linkedin_url: Optional[str] = None
    background: Optional[str] = None


class Signal(BaseModel):
    """Key signal or indicator."""
    signal_type: str
    description: str
    source: str


class NewsItem(BaseModel):
    """News article."""
    headline: str
    outlet: Optional[str] = None
    url: Optional[str] = None
    published_date: Optional[str] = None
    takeaway: Optional[str] = None
    synopsis: Optional[str] = None  # 1-2 sentence VC-relevant summary
    sentiment: Optional[str] = None  # "positive", "negative", or "neutral"
    news_type: Optional[str] = None  # Signal type: funding, acquisition, executive_change, etc.


class CompetitorInfo(BaseModel):
    """Competitor company information."""
    name: str
    domain: Optional[str] = None
    competitor_type: str  # "startup" or "incumbent"
    description: Optional[str] = None
    funding_total: Optional[float] = None
    funding_stage: Optional[str] = None
    funding_last_amount: Optional[float] = None
    funding_last_date: Optional[str] = None
    headcount: Optional[int] = None
    tags: Optional[str] = None


class BriefingResponse(BaseModel):
    """Full briefing response."""
    id: str = Field(..., description="Unique briefing ID")
    company_id: str = Field(..., description="Normalized company identifier")
    company_name: str
    created_at: datetime

    # Structured sections
    tldr: Optional[str] = None
    why_it_matters: Optional[list[str]] = None
    company_snapshot: Optional[CompanySnapshot] = None
    founders: list[FounderInfo] = []
    signals: list[Signal] = []
    news: list[NewsItem] = []
    competitors: list[CompetitorInfo] = []
    meeting_prep: Optional[str] = None

    # Full markdown (for copy/export)
    markdown: str

    # Metadata
    success: bool
    error: Optional[str] = None
    data_sources: dict = {}


class BriefingListItem(BaseModel):
    """Summary item for briefing list view."""
    id: str
    company_id: str
    company_name: str
    created_at: datetime
    success: bool


class BriefingListResponse(BaseModel):
    """Response for listing briefings."""
    briefings: list[BriefingListItem]
    total: int


class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None


# =============================================================================
# DIGEST MODELS
# =============================================================================

class DigestArticleResponse(BaseModel):
    """Article in the weekly digest."""
    headline: str
    company: str
    category: str  # "portfolio" or "competitor"
    signal_type: str
    source: Optional[str] = None
    url: Optional[str] = None
    published_date: Optional[str] = None
    relevance_score: int = 0
    rank_score: float = 0.0
    sentiment: Optional[str] = None  # "positive", "negative", "neutral"
    synopsis: Optional[str] = None  # 1-2 sentence summary


class SentimentRollup(BaseModel):
    """Aggregated sentiment statistics."""
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    total: int = 0

    @property
    def positive_pct(self) -> float:
        return (self.positive / self.total * 100) if self.total > 0 else 0.0

    @property
    def negative_pct(self) -> float:
        return (self.negative / self.total * 100) if self.total > 0 else 0.0


class IndustryHighlight(BaseModel):
    """Industry trend summary."""
    industry: str
    total_signals: int = 0
    company_count: int = 0
    top_types: dict = {}


class DigestStats(BaseModel):
    """Digest statistics."""
    total_signals: int = 0
    companies_covered: int = 0
    portfolio_signals: int = 0
    competitor_signals: int = 0
    featured_count: int = 0
    summary_count: int = 0


class WeeklyDigestResponse(BaseModel):
    """Weekly digest response with tiered articles and sentiment rollup."""
    start_date: str
    end_date: str
    generated_at: datetime

    # Tiered article display
    featured_articles: list[DigestArticleResponse] = Field(
        default=[],
        description="Top 2-3 most significant articles with full details"
    )
    summary_articles: list[DigestArticleResponse] = Field(
        default=[],
        description="Additional 7-8 notable articles in condensed format"
    )

    # Sentiment rollup
    sentiment_rollup: SentimentRollup = Field(
        default_factory=SentimentRollup,
        description="Aggregated sentiment across all articles"
    )

    # Additional context
    industry_highlights: list[IndustryHighlight] = []
    stats: DigestStats = Field(default_factory=DigestStats)

    # Markdown export
    markdown: Optional[str] = None


# =============================================================================
# WATCHLIST MODELS
# =============================================================================

class WatchlistAddRequest(BaseModel):
    """Request to add a company to the watchlist."""
    domain: str = Field(..., description="Company domain (e.g., 'stripe.com')")
    name: str = Field(..., description="Company name (e.g., 'Stripe')")
    category: str = Field(
        default="portfolio",
        description="Category: 'portfolio' or 'competitor'"
    )


class WatchlistCompanyResponse(BaseModel):
    """Company in the watchlist."""
    id: str
    domain: str
    name: str
    category: str
    is_active: bool = True
    competitors: list[str] = []  # List of competitor names
    created_at: Optional[datetime] = None


class WatchlistResponse(BaseModel):
    """Response for listing watchlist companies."""
    companies: list[WatchlistCompanyResponse]
    total_portfolio: int
    total_competitors: int


# =============================================================================
# JOB RUN MODELS (for tracking agent execution)
# =============================================================================

class JobRunResponse(BaseModel):
    """Response for a job run."""
    id: str
    agent_type: str
    status: str  # "pending", "running", "completed", "failed"
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result_summary: dict = {}


class NewsRefreshRequest(BaseModel):
    """Request to trigger a news refresh."""
    days: int = Field(default=7, ge=1, le=30, description="Days to look back for signals")
    refresh_competitors: bool = Field(default=True, description="Discover competitors for new portfolio companies")


class NewsRefreshResponse(BaseModel):
    """Response after triggering a news refresh."""
    job_id: str
    status: str
    message: str


# =============================================================================
# OUTREACH FEEDBACK MODELS
# =============================================================================

class OutreachRequest(BaseModel):
    """Request to generate an outreach email or LinkedIn message."""
    company_id: str = Field(..., description="Company domain, e.g. 'stripe.com'")
    output_format: str = Field(default="email", pattern="^(email|linkedin)$")
    contact_name: Optional[str] = Field(default=None, description="Target contact name (auto-selected if omitted)")
    investor_key: str = Field(default="ashley", description="Investor profile key: ashley | tiffany | danielle | madison")
    skip_ingest: bool = Field(default=False, description="Use cached DB data only; set True to skip slow live ingest")
    context_type_override: Optional[str] = Field(default=None, description="Force a specific context type (optional)")
    outreach_goal: Optional[str] = Field(default=None, description="Free-text goal, e.g. 'congratulate on Series B'")
    has_event_context: bool = Field(default=False, description="True if investor has recent event/conference context")
    event_details: Optional[str] = Field(default=None, description="Details about the event context")
    has_prior_relationship: bool = Field(default=False, description="True if investor has a prior relationship with the founder")
    prior_relationship_details: Optional[str] = Field(default=None, description="Details about the prior relationship")
    stealth_mode: bool = Field(default=False, description="If True, bypasses company ingest and generates a founder-centric email")
    founder_linkedin_url: Optional[str] = Field(default=None, description="Required when stealth_mode=True; LinkedIn profile URL of the stealth founder")
    founder_background_notes: Optional[str] = Field(default=None, description="Investor's manual context about the founder (optional override/supplement)")

    @model_validator(mode="after")
    def require_linkedin_in_stealth(self) -> "OutreachRequest":
        if self.stealth_mode and not self.founder_linkedin_url:
            raise ValueError("founder_linkedin_url is required when stealth_mode=True")
        return self


class OutreachResponse(BaseModel):
    """Response from outreach generation."""
    company_id: str
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_title: Optional[str] = None
    contact_linkedin: Optional[str] = None
    investor_key: str
    output_format: str
    context_type: Optional[str] = None
    subject: Optional[str] = None
    message: Optional[str] = None
    generated_at: str
    data_sources: dict = {}
    success: bool
    error: Optional[str] = None
    stealth_mode: bool = False


class OutreachFeedbackRequest(BaseModel):
    """Investor feedback on a generated outreach email."""
    outreach_id: Optional[str] = Field(
        default=None,
        description="ID of the outreach_history record this feedback relates to (optional)"
    )
    investor_key: str = Field(..., description="Investor key, e.g. 'ashley'")
    company_id: str = Field(..., description="Company domain, e.g. 'stripe.com'")
    context_type: Optional[str] = Field(default=None, description="Context type used during generation")
    original_message: str = Field(..., description="The message as originally generated")
    edited_message: Optional[str] = Field(
        default=None,
        description="The investor's edited version. Required when approval_status='edited'"
    )
    approval_status: str = Field(
        ...,
        pattern="^(approved|edited|rejected)$",
        description="'approved' keeps the original, 'edited' promotes the edit, 'rejected' discards"
    )
    investor_notes: Optional[str] = Field(
        default=None,
        description="Optional free-text note explaining the edit or rejection"
    )


class OutreachFeedbackResponse(BaseModel):
    """Response after submitting outreach feedback."""
    id: str = Field(..., description="UUID of the created feedback record")
    approval_status: str
    promoted: bool = Field(
        ...,
        description="True if this email will be used as a future few-shot example"
    )
