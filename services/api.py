"""
FastAPI backend for Meeting Briefing Agent.

Endpoints:
- POST /api/briefing - Generate a new briefing
- GET /api/briefings - List past briefings
- GET /api/briefings/{id} - Get a specific briefing
- DELETE /api/briefings/{id} - Delete a briefing
- GET /api/digest/weekly - Generate weekly signal digest

Run with:
    uvicorn services.api:app --reload --port 8000
"""

# Load environment variables (don't override existing env vars from Railway/production)
from dotenv import load_dotenv
load_dotenv(override=False)

import hmac
import logging
import os
import re
from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from services.models import (
    BriefingRequest,
    BriefingResponse,
    BriefingListItem,
    BriefingListResponse,
    CompanySnapshot,
    FounderInfo,
    Signal,
    NewsItem,
    CompetitorInfo,
    ErrorResponse,
    WeeklyDigestResponse,
    DigestArticleResponse,
    SentimentRollup,
    IndustryHighlight,
    DigestStats,
    WatchlistAddRequest,
    WatchlistCompanyResponse,
    WatchlistResponse,
    JobRunResponse,
    OutreachRequest,
    OutreachResponse,
    OutreachFeedbackRequest,
    OutreachFeedbackResponse,
)
from services.history import BriefingHistoryDB, BriefingRecord

# Configure structured logging for JSON output (Vercel log drain compatible)
from services.logging_setup import setup_logging, get_logger
setup_logging(use_json=True)
logger = get_logger(__name__)

# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title="NEA Meeting Briefing API",
    description="API for generating company meeting briefings",
    version="1.0.1",
)

# Version marker for debugging Railway deployments
API_VERSION = "1.0.3"
logger.info(f"=== NEA API VERSION {API_VERSION} - WATCHLIST FIX DEPLOYED ===")

# CORS — allowlist from ALLOWED_ORIGINS env (comma-separated).
# Defaults to localhost dev only; production must set ALLOWED_ORIGINS explicitly.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
logger.info(f"CORS allowlist: {ALLOWED_ORIGINS}")

# Import auth utilities. Post-NEA merge (M5): Supabase HS256 is the only
# accepted auth scheme. Clerk RS256 and the legacy X-NEA-Key shared secret
# have been removed.
from services.auth import (
    USE_SUPABASE_AUTH,
    verify_supabase_token,
    get_user_id,
)

_PROTECTED_METHODS = {"POST", "DELETE", "PUT", "PATCH"}
_PROTECTED_PATH_PREFIX = "/api/"
_UNPROTECTED_PATHS = {"/", "/health"}
# Internal endpoints are guarded by X-NEA-Internal-Token (NEA_INTERNAL_SECRET).
# They bypass the user-JWT requirement so cron / GitHub Actions can call them.
_INTERNAL_PATH_PREFIX = "/api/internal/"


@app.middleware("http")
async def require_auth(request: Request, call_next):
    """
    Gate write endpoints on Supabase JWT auth.

    Protected POST/DELETE/PUT/PATCH under /api/ (excluding /api/internal/*)
    require an `Authorization: Bearer <supabase_jwt>` header. The token's
    `sub` claim is the `auth.users.id` UUID and becomes
    `request.state.user_id`.

    /api/internal/* is gated by `X-NEA-Internal-Token` in the route handler.
    """
    if (
        request.method in _PROTECTED_METHODS
        and request.url.path.startswith(_PROTECTED_PATH_PREFIX)
        and not request.url.path.startswith(_INTERNAL_PATH_PREFIX)
        and request.url.path not in _UNPROTECTED_PATHS
    ):
        if not USE_SUPABASE_AUTH:
            # If someone deploys with USE_SUPABASE_AUTH=false we hard-fail
            # rather than silently opening every write endpoint to the world.
            logger.error(
                "USE_SUPABASE_AUTH must be true post-M5; refusing %s %s",
                request.method, request.url.path,
            )
            return _json_error(503, "Server misconfigured: Supabase auth disabled")

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning(
                "Rejected %s %s — missing Authorization header",
                request.method, request.url.path,
            )
            return _json_error(401, "Missing Authorization header")

        token = auth_header[7:]
        claims = verify_supabase_token(token)
        if not claims:
            logger.warning(
                "Rejected %s %s — invalid or expired token",
                request.method, request.url.path,
            )
            return _json_error(401, "Invalid or expired token")

        request.state.user_id = claims.get("sub")
        logger.info(f"Authenticated user: {request.state.user_id}")

    return await call_next(request)


def _json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={"detail": detail})


# Initialize history database
history_db = BriefingHistoryDB()


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_briefing_sections(markdown: str) -> dict:
    """
    Parse markdown briefing into structured sections.

    Extracts:
    - tldr: TL;DR section
    - why_it_matters: Why This Meeting Matters bullets
    - meeting_prep: For This Meeting section
    """
    sections = {}

    # Extract TL;DR
    tldr_match = re.search(
        r'### 1\) TL;DR\s*\n(.*?)(?=\n### |\Z)',
        markdown,
        re.DOTALL
    )
    if tldr_match:
        sections['tldr'] = tldr_match.group(1).strip()

    # Extract Why This Meeting Matters as bullet list
    why_match = re.search(
        r'### 2\) Why This Meeting Matters\s*\n(.*?)(?=\n### |\Z)',
        markdown,
        re.DOTALL
    )
    if why_match:
        bullets = re.findall(r'[-*]\s+(.+)', why_match.group(1))
        sections['why_it_matters'] = bullets if bullets else None

    # Extract For This Meeting (section 3 current, fallback to legacy 7/8)
    meeting_match = re.search(
        r'### [378]\) For This Meeting\s*\n(.*?)(?=\n### |\Z)',
        markdown,
        re.DOTALL
    )
    if meeting_match:
        sections['meeting_prep'] = meeting_match.group(1).strip()

    return sections


def build_response(
    briefing_id: str,
    result: dict,
    bundle: "CompanyBundle",
    created_at: datetime,
) -> BriefingResponse:
    """Build BriefingResponse from generate_briefing result and company bundle."""

    # Phase 3.4: Check for pre-parsed structured fields first (from with_structured_output)
    # If present, use them directly; otherwise fall back to regex parsing
    if result.get('tldr') is not None:
        # Structured output was used - fields are already parsed
        sections = {
            'tldr': result['tldr'],
            'why_it_matters': result.get('why_it_matters'),
            'meeting_prep': result.get('meeting_prep'),
        }
    elif result.get('markdown'):
        # Legacy path: parse sections from markdown using regex
        sections = parse_briefing_sections(result['markdown'])
    else:
        sections = {}

    # Build company snapshot
    company_snapshot = None
    if bundle.company_core:
        c = bundle.company_core
        last_round = None
        if c.last_round_date and c.last_round_funding:
            last_round = f"${c.last_round_funding:,.0f} ({c.last_round_date})"
        elif c.last_round_date:
            last_round = c.last_round_date

        company_snapshot = CompanySnapshot(
            company_name=c.company_name,
            founded=c.founding_date,
            hq=c.hq,
            employees=c.employee_count,
            products=c.products,
            customers=c.customers,
            total_funding=c.total_funding,
            last_round=last_round,
        )

    # Build founders list
    founders = [
        FounderInfo(
            name=f.name,
            role=f.role_title,
            linkedin_url=f.linkedin_url,
            background=f.background,
        )
        for f in bundle.founders
    ]

    # Build signals list
    signals = [
        Signal(
            signal_type=s.signal_type,
            description=s.description,
            source=s.source,
        )
        for s in bundle.key_signals
    ]

    # Build news list
    news = [
        NewsItem(
            headline=n.article_headline,
            outlet=n.outlet,
            url=n.url,
            published_date=n.published_date,
            synopsis=n.synopsis,
            takeaway=n.synopsis,  # Use synopsis as takeaway for frontend compatibility
            sentiment=n.sentiment,
            news_type=n.news_type,
        )
        for n in bundle.news
    ]

    # Build competitors list
    competitors = [
        CompetitorInfo(
            name=c.competitor_name,
            domain=c.competitor_domain,
            competitor_type=c.competitor_type,
            description=c.description,
            funding_total=c.funding_total,
            funding_stage=c.funding_stage,
            funding_last_amount=c.funding_last_amount,
            funding_last_date=c.funding_last_date,
            headcount=c.headcount,
            tags=c.tags,
        )
        for c in bundle.competitors
    ]

    return BriefingResponse(
        id=briefing_id,
        company_id=result['company_id'],
        company_name=result.get('company_name') or 'Unknown',
        created_at=created_at,
        tldr=sections.get('tldr'),
        why_it_matters=sections.get('why_it_matters'),
        company_snapshot=company_snapshot,
        founders=founders,
        signals=signals,
        news=news,
        competitors=competitors,
        meeting_prep=sections.get('meeting_prep'),
        markdown=result.get('markdown') or '',
        success=result.get('success', False),
        error=result.get('error'),
        data_sources=result.get('data_sources', {}),
    )


# =============================================================================
# ENDPOINTS
# =============================================================================

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "NEA Meeting Briefing API", "version": API_VERSION}


@app.get("/health")
async def health():
    """Databricks Apps health check."""
    return {"status": "ok"}


@app.post("/api/briefing", response_model=BriefingResponse)
async def create_briefing(request: BriefingRequest):
    """
    Generate a new meeting briefing for a company.

    1. Ingests company data from APIs (Harmonic, Swarm, etc.)
    2. Generates briefing using LLM
    3. Stores in history
    4. Returns structured response
    """
    # Import here to avoid circular imports and allow lazy loading
    from tools.company_tools import ingest_company, get_company_bundle, normalize_company_id
    from agents.meeting_briefing.briefing_generator import generate_briefing

    url = request.url.strip()
    logger.info(f"Generating briefing for: {url}")

    try:
        # Step 1: Ingest company data
        logger.info("Ingesting company data...")
        ingest_result = ingest_company(url)

        if not ingest_result.get('company_core'):
            errors = ingest_result.get('errors', [])
            error_msg = errors[0] if errors else 'Company not found'
            raise HTTPException(
                status_code=404,
                detail=f"Could not find company: {error_msg}"
            )

        # Step 2: Generate briefing
        logger.info("Generating briefing...")
        result = generate_briefing(url)

        if not result.get('success'):
            raise HTTPException(
                status_code=500,
                detail=f"Briefing generation failed: {result.get('error', 'Unknown error')}"
            )

        # Step 3: Get company bundle for structured data
        normalized_id = normalize_company_id(url)
        bundle = get_company_bundle(normalized_id)

        # Step 4: Build response
        briefing_id = str(uuid4())
        created_at = datetime.utcnow()

        response = build_response(briefing_id, result, bundle, created_at)

        # Step 5: Store in history
        history_db.save_briefing(BriefingRecord(
            id=briefing_id,
            company_id=response.company_id,
            company_name=response.company_name,
            created_at=created_at,
            markdown=response.markdown,
            success=response.success,
            error=response.error,
            data_sources=response.data_sources,
        ))

        logger.info(f"Briefing generated successfully: {response.company_name}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error generating briefing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/briefings", response_model=BriefingListResponse)
async def list_briefings(
    search: Optional[str] = Query(None, description="Search by company name or URL"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List past briefings with optional search."""
    briefings = history_db.list_briefings(search=search, limit=limit, offset=offset)
    total = history_db.count_briefings(search=search)

    items = [
        BriefingListItem(
            id=b.id,
            company_id=b.company_id,
            company_name=b.company_name,
            created_at=b.created_at,
            success=b.success,
        )
        for b in briefings
    ]

    return BriefingListResponse(briefings=items, total=total)


@app.get("/api/briefings/{briefing_id}", response_model=BriefingResponse)
async def get_briefing(briefing_id: str):
    """Get a specific briefing by ID."""
    from tools.company_tools import get_company_bundle

    record = history_db.get_briefing(briefing_id)
    if not record:
        raise HTTPException(status_code=404, detail="Briefing not found")

    # Get current company bundle for structured data
    bundle = get_company_bundle(record.company_id)

    # Reconstruct result dict
    result = {
        'company_id': record.company_id,
        'company_name': record.company_name,
        'markdown': record.markdown,
        'success': record.success,
        'error': record.error,
        'data_sources': record.data_sources,
    }

    return build_response(record.id, result, bundle, record.created_at)


@app.delete("/api/briefings/{briefing_id}")
async def delete_briefing(briefing_id: str):
    """Delete a briefing."""
    success = history_db.delete_briefing(briefing_id)
    if not success:
        raise HTTPException(status_code=404, detail="Briefing not found")
    return {"status": "deleted", "id": briefing_id}


# =============================================================================
# DIGEST ENDPOINTS
# =============================================================================

@app.get("/api/digest/weekly", response_model=WeeklyDigestResponse)
async def get_weekly_digest(
    days: int = Query(7, ge=1, le=30, description="Number of days to look back"),
    featured_count: int = Query(3, ge=1, le=5, description="Number of featured articles"),
    summary_count: int = Query(8, ge=1, le=15, description="Number of summary articles"),
    investor_id: Optional[str] = Query(None, description="Filter to specific investor"),
    include_markdown: bool = Query(True, description="Include markdown export"),
):
    """
    Generate a weekly digest of company signals.

    Returns a tiered article display:
    - Top 2-3 featured articles with full details
    - 7-8 summarized articles in condensed format
    - Sentiment rollup across all articles
    - Industry trend highlights
    """
    from agents.news_aggregator.digest import generate_weekly_digest

    try:
        logger.info(f"Generating weekly digest (days={days}, featured={featured_count}, summary={summary_count})")

        # Generate digest using the digest module
        digest = generate_weekly_digest(
            days=days,
            featured_count=featured_count,
            summary_count=summary_count,
            investor_id=investor_id,
            include_industry_highlights=True,
            use_llm_summaries=False,  # Can be enabled for enhanced summaries
        )

        # Convert featured articles
        featured = [
            DigestArticleResponse(
                headline=a.signal.headline,
                company=a.company_name,
                category=a.company_category,
                signal_type=a.signal.signal_type,
                source=a.signal.source_name,
                url=a.signal.source_url,
                published_date=a.signal.published_date,
                relevance_score=a.signal.relevance_score or 0,
                rank_score=a.rank_score,
                sentiment=a.signal.sentiment,
                synopsis=a.signal.synopsis or a.signal.description,
            )
            for a in digest.featured_articles
        ]

        # Convert summary articles
        summary = [
            DigestArticleResponse(
                headline=a.signal.headline,
                company=a.company_name,
                category=a.company_category,
                signal_type=a.signal.signal_type,
                source=a.signal.source_name,
                url=a.signal.source_url,
                published_date=a.signal.published_date,
                relevance_score=a.signal.relevance_score or 0,
                rank_score=a.rank_score,
                sentiment=a.signal.sentiment,
                synopsis=a.signal.synopsis,
            )
            for a in digest.summary_articles
        ]

        # Calculate sentiment rollup
        all_articles = digest.featured_articles + digest.summary_articles
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        for article in all_articles:
            sentiment = article.signal.sentiment or "neutral"
            if sentiment in sentiment_counts:
                sentiment_counts[sentiment] += 1
            else:
                sentiment_counts["neutral"] += 1

        sentiment_rollup = SentimentRollup(
            positive=sentiment_counts["positive"],
            negative=sentiment_counts["negative"],
            neutral=sentiment_counts["neutral"],
            total=len(all_articles),
        )

        # Convert industry highlights
        industry_highlights = [
            IndustryHighlight(
                industry=industry,
                total_signals=data.get("total_signals", 0),
                company_count=data.get("company_count", 0),
                top_types=data.get("top_types", {}),
            )
            for industry, data in digest.industry_highlights.items()
        ]

        # Build stats
        stats = DigestStats(
            total_signals=digest.stats.get("total_signals", 0),
            companies_covered=digest.stats.get("companies_covered", 0),
            portfolio_signals=digest.stats.get("portfolio_signals", 0),
            competitor_signals=digest.stats.get("competitor_signals", 0),
            featured_count=len(featured),
            summary_count=len(summary),
        )

        # Build response
        response = WeeklyDigestResponse(
            start_date=digest.start_date,
            end_date=digest.end_date,
            generated_at=datetime.fromisoformat(digest.generated_at),
            featured_articles=featured,
            summary_articles=summary,
            sentiment_rollup=sentiment_rollup,
            industry_highlights=industry_highlights,
            stats=stats,
            markdown=digest.to_markdown() if include_markdown else None,
        )

        logger.info(
            f"Digest generated: {len(featured)} featured, {len(summary)} summary, "
            f"sentiment: +{sentiment_rollup.positive}/-{sentiment_rollup.negative}"
        )

        return response

    except Exception as e:
        logger.exception(f"Error generating weekly digest: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WATCHLIST ENDPOINTS
# =============================================================================

@app.get("/api/watchlist", response_model=WatchlistResponse)
async def get_watchlist():
    """
    Get all companies in the watchlist.

    Returns portfolio companies with their discovered competitors.
    """
    from agents.news_aggregator.database import (
        get_companies, get_portfolio_companies,
        get_competitors_for_company
    )

    try:

        portfolio = get_portfolio_companies()
        all_companies = get_companies()

        companies = []

        # Add portfolio companies with their competitors
        for p in portfolio:
            competitors = get_competitors_for_company(p.id)
            competitor_names = [c.company_name for c in competitors]

            companies.append(WatchlistCompanyResponse(
                id=p.id,
                domain=p.company_id,
                name=p.company_name,
                category="portfolio",
                is_active=p.is_active,
                competitors=competitor_names,
                created_at=None,
            ))

        # Add standalone competitors (those without a parent)
        for c in all_companies:
            if c.category == "competitor" and not c.parent_company_id:
                companies.append(WatchlistCompanyResponse(
                    id=c.id,
                    domain=c.company_id,
                    name=c.company_name,
                    category="competitor",
                    is_active=c.is_active,
                    competitors=[],
                    created_at=None,
                ))

        portfolio_count = len([c for c in companies if c.category == "portfolio"])
        competitor_count = len([c for c in all_companies if c.category == "competitor"])

        return WatchlistResponse(
            companies=companies,
            total_portfolio=portfolio_count,
            total_competitors=competitor_count,
        )

    except Exception as e:
        logger.exception(f"Error fetching watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/watchlist", response_model=WatchlistCompanyResponse)
async def add_to_watchlist(request: WatchlistAddRequest):
    """
    Add a company to the watchlist.

    - domain: Company domain (e.g., "stripe.com")
    - name: Company name (e.g., "Stripe")
    - category: "portfolio" or "competitor"
    """
    from agents.news_aggregator.database import (
        add_company, get_or_create_default_investor,
        link_investor_to_company, get_company_by_domain
    )

    try:

        # Validate category
        if request.category not in ["portfolio", "competitor"]:
            raise HTTPException(
                status_code=400,
                detail="Category must be 'portfolio' or 'competitor'"
            )

        # Check if company already exists
        existing = get_company_by_domain(request.domain)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Company '{request.domain}' already exists in watchlist"
            )

        # Get default investor
        investor = get_or_create_default_investor()

        # Add company
        company = add_company(
            company_id=request.domain,
            company_name=request.name,
            category=request.category,
        )

        # Link to investor
        link_investor_to_company(investor.id, company.id)

        logger.info(f"Added {request.name} ({request.domain}) to watchlist as {request.category}")

        return WatchlistCompanyResponse(
            id=company.id,
            domain=company.company_id,
            name=company.company_name,
            category=company.category,
            is_active=company.is_active,
            competitors=[],
            created_at=None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error adding to watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/watchlist/{domain}")
async def remove_from_watchlist(domain: str, hard_delete: bool = False):
    """
    Remove a company from the watchlist.

    - domain: Company domain to remove
    - hard_delete: If true, permanently delete. Otherwise just deactivate.
    """
    from agents.news_aggregator.database import (
        get_company_by_domain, remove_company, deactivate_company
    )

    try:

        company = get_company_by_domain(domain)
        if not company:
            raise HTTPException(status_code=404, detail=f"Company '{domain}' not found")

        if hard_delete:
            success = remove_company(company.id, hard_delete=True)
            action = "deleted"
        else:
            success = deactivate_company(company.id)
            action = "deactivated"

        if not success:
            raise HTTPException(status_code=500, detail=f"Failed to {action} company")

        logger.info(f"{action.capitalize()} {company.company_name} ({domain}) from watchlist")

        return {"status": action, "domain": domain, "name": company.company_name}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error removing from watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# COMPANY ENDPOINTS (Supabase-backed for Lovable frontend)
# =============================================================================

class CompanyAddRequest(BaseModel):
    """Request to add a company via the API (bypasses RLS)."""
    name: str = Field(..., description="Company name (e.g., 'Stripe')")
    domain: str = Field(..., description="Company domain (e.g., 'stripe.com')")
    category: str = Field(default="portfolio", description="Category: 'portfolio' or 'competitor'")


class CompanyResponse(BaseModel):
    """Response for a company."""
    id: str
    company_id: str
    company_name: str
    category: str
    is_active: bool
    added_at: Optional[str] = None


@app.post("/api/companies", response_model=CompanyResponse)
async def add_company(request: CompanyAddRequest):
    """
    Add a company to the watched_companies table.

    Uses service role key to bypass RLS. After adding, automatically
    triggers a news refresh to fetch stories for the new company.
    """
    from core.clients.supabase_client import get_supabase

    try:
        supabase = get_supabase()

        # Validate category
        if request.category not in ["portfolio", "competitor"]:
            raise HTTPException(
                status_code=400,
                detail="Category must be 'portfolio' or 'competitor'"
            )

        # Check if company already exists
        existing = supabase.table("watched_companies").select("*").eq("company_id", request.domain).execute()
        if existing.data:
            raise HTTPException(
                status_code=409,
                detail=f"Company '{request.domain}' already exists"
            )

        # Insert the company. M1b: bridge to canonical_entities.
        _watched_row = {
            "company_id": request.domain,
            "company_name": request.name,
            "category": request.category,
            "is_active": True,
        }
        try:
            from core.canonical_bridge import resolve_canonical_entity_id
            _cid = resolve_canonical_entity_id(domain=request.domain, name=request.name)
            if _cid:
                _watched_row["canonical_entity_id"] = _cid
        except Exception as _ex:
            logger.debug(f"canonical_bridge lookup failed (watched_companies add): {_ex}")

        result = supabase.table("watched_companies").insert(_watched_row).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to insert company")

        company = result.data[0]
        logger.info(f"Added company: {request.name} ({request.domain})")

        return CompanyResponse(
            id=company["id"],
            company_id=company["company_id"],
            company_name=company["company_name"],
            category=company["category"],
            is_active=company["is_active"],
            added_at=company.get("added_at"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error adding company: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/companies/{company_id}")
async def delete_company(company_id: str, hard_delete: bool = False):
    """
    Remove a company from the watched_companies table.

    - company_id: UUID of the company to remove
    - hard_delete: If true, permanently delete. Otherwise just deactivate.
    """
    from core.clients.supabase_client import get_supabase

    try:
        supabase = get_supabase()

        # Check if company exists
        existing = supabase.table("watched_companies").select("*").eq("id", company_id).execute()
        if not existing.data:
            raise HTTPException(status_code=404, detail=f"Company not found")

        company = existing.data[0]

        if hard_delete:
            supabase.table("watched_companies").delete().eq("id", company_id).execute()
            action = "deleted"
        else:
            supabase.table("watched_companies").update({"is_active": False}).eq("id", company_id).execute()
            action = "deactivated"

        logger.info(f"{action.capitalize()} company: {company['company_name']} ({company['company_id']})")

        return {"status": action, "id": company_id, "name": company["company_name"]}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error removing company: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# NEWS STATUS ENDPOINTS
# =============================================================================
# Note: POST /api/news/refresh has been removed. News refresh is now handled
# by GitHub Actions scheduled workflows (see .github/workflows/news_refresh.yml).
# These GET endpoints remain for checking job status.
# =============================================================================

@app.get("/api/news/status/{job_id}", response_model=JobRunResponse)
async def get_news_job_status(job_id: str):
    """
    Get the status of a specific news refresh job.

    Note: Lovable can also query the job_runs table directly via Supabase
    for real-time updates without hitting this endpoint.
    """
    from services.job_manager import get_job_manager

    job_manager = get_job_manager()
    job = job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobRunResponse(
        id=job.id,
        agent_type=job.agent_type,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
        result_summary=job.result_summary or {},
    )


@app.get("/api/news/status", response_model=JobRunResponse)
async def get_latest_news_status():
    """
    Get the status of the most recent news refresh job.

    Useful for checking if a refresh is currently running or
    when the last refresh completed.
    """
    from services.job_manager import get_job_manager

    job_manager = get_job_manager()
    job = job_manager.get_latest_job("news_aggregator")

    if not job:
        raise HTTPException(status_code=404, detail="No news jobs found")

    return JobRunResponse(
        id=job.id,
        agent_type=job.agent_type,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
        result_summary=job.result_summary or {},
    )


@app.get("/api/news/stories")
async def get_stories(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    classification: Optional[str] = Query(None, description="Filter by classification"),
    company_category: Optional[str] = Query(None, description="Filter by portfolio/competitor"),
    min_priority: Optional[float] = Query(None, description="Minimum priority score"),
):
    """
    Get cached stories from the most recent digest.

    Note: Lovable can also query the stories table directly via Supabase.
    This endpoint provides convenient filtering and pagination.
    """
    from core.clients.supabase_client import get_supabase

    supabase = get_supabase()
    query = supabase.table("stories").select("*")

    if classification:
        query = query.eq("classification", classification)
    if company_category:
        query = query.eq("company_category", company_category)
    if min_priority is not None:
        query = query.gte("priority_score", min_priority)

    result = (
        query
        .order("priority_score", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "stories": result.data,
        "count": len(result.data),
        "offset": offset,
        "limit": limit,
    }


# =============================================================================
# OUTREACH GENERATION
# =============================================================================

@app.post("/api/outreach", response_model=OutreachResponse)
async def generate_outreach_endpoint(request: Request, body: OutreachRequest):
    """
    Generate a personalized cold outreach email or LinkedIn message.

    Runs the full outreach pipeline:
    1. Ingests company data (Harmonic, Tavily, news) unless skip_ingest=True
    2. Selects the best contact (or uses contact_name if provided)
    3. Detects context type from available signals + investor inputs
    4. Loads investor voice profile and few-shot examples (including any
       previously promoted from investor feedback)
    5. Calls Claude to generate the message

    Note: with skip_ingest=False (default) this may take 20-40 seconds
    depending on data availability. Set skip_ingest=True to use cached
    data for a faster response.
    """
    import asyncio
    from agents.outreach.generator import generate_outreach

    # Phase 3.1: Extract user_id from request state (set by auth middleware)
    user_id = getattr(request.state, "user_id", None)

    try:
        # generate_outreach is synchronous — run in thread pool to avoid
        # blocking the event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: generate_outreach(
                company_id=body.company_id,
                output_format=body.output_format,
                contact_name=body.contact_name,
                investor_key=body.investor_key,
                skip_ingest=body.skip_ingest,
                force_refresh=body.force_refresh,
                context_type_override=body.context_type_override,
                outreach_goal=body.outreach_goal,
                has_event_context=body.has_event_context,
                event_details=body.event_details,
                has_prior_relationship=body.has_prior_relationship,
                prior_relationship_details=body.prior_relationship_details,
                stealth_mode=body.stealth_mode,
                founder_linkedin_url=body.founder_linkedin_url,
                founder_background_notes=body.founder_background_notes,
                user_id=user_id,
            )
        )
    except Exception as exc:
        logger.error(f"Outreach generation error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))

    if not result.get("success"):
        raise HTTPException(
            status_code=422,
            detail=result.get("error", "Outreach generation failed")
        )

    return OutreachResponse(
        company_id=result["company_id"],
        company_name=result.get("company_name"),
        contact_name=result.get("contact_name"),
        contact_title=result.get("contact_title"),
        contact_linkedin=result.get("contact_linkedin"),
        investor_key=result["investor_key"],
        output_format=result["output_format"],
        context_type=result.get("context_type"),
        subject=result.get("subject"),
        message=result.get("message"),
        generated_at=result["generated_at"],
        data_sources=result.get("data_sources", {}),
        success=result["success"],
        error=result.get("error"),
        stealth_mode=result.get("stealth_mode", False),
    )


# =============================================================================
# OUTREACH FEEDBACK
# =============================================================================

@app.post("/api/outreach/feedback", response_model=OutreachFeedbackResponse)
async def submit_outreach_feedback(request: OutreachFeedbackRequest):
    """
    Submit investor feedback on a generated outreach email.

    - approval_status='approved'  → original email promoted to examples pool as-is
    - approval_status='edited'    → investor's edited version promoted to examples pool
    - approval_status='rejected'  → stored for analysis but never used in generation

    Promoted emails become high-priority few-shot examples for future
    generations matching the same investor and context type.
    """
    from services.feedback import save_feedback, FeedbackRecord, PROMOTABLE_STATUSES

    if request.approval_status == "edited" and not request.edited_message:
        raise HTTPException(
            status_code=422,
            detail="edited_message is required when approval_status is 'edited'"
        )

    record = FeedbackRecord(
        outreach_id=request.outreach_id,
        investor_key=request.investor_key,
        company_id=request.company_id,
        context_type=request.context_type,
        original_message=request.original_message,
        edited_message=request.edited_message,
        approval_status=request.approval_status,
        investor_notes=request.investor_notes,
    )

    try:
        record_id = save_feedback(record)
    except Exception as exc:
        logger.error(f"Failed to save outreach feedback: {exc}")
        raise HTTPException(status_code=500, detail="Failed to save feedback")

    return OutreachFeedbackResponse(
        id=record_id,
        approval_status=request.approval_status,
        promoted=request.approval_status in PROMOTABLE_STATUSES,
    )


# =============================================================================
# INTERNAL JOB TRIGGERS (GitHub Actions cron)
# =============================================================================
# These endpoints kick off long-running batch jobs in background threads and
# return immediately with a job id. Caller polls /api/news/status/{id} for
# completion. Guarded by NEA_INTERNAL_SECRET — never expose to the frontend.

NEA_INTERNAL_SECRET = os.getenv("NEA_INTERNAL_SECRET")


def _check_internal_token(request: Request) -> None:
    """403 unless the request carries a matching X-NEA-Internal-Token header."""
    if not NEA_INTERNAL_SECRET:
        raise HTTPException(status_code=503, detail="Internal endpoints disabled (NEA_INTERNAL_SECRET unset)")
    provided = request.headers.get("x-nea-internal-token", "")
    if not hmac.compare_digest(provided, NEA_INTERNAL_SECRET):
        raise HTTPException(status_code=403, detail="Invalid internal token")


def _run_news_refresh_job() -> None:
    """Background-thread wrapper around scripts/run_news_refresh.main()."""
    try:
        from scripts.run_news_refresh import main as run_news_main
        run_news_main()
    except Exception:
        logger.exception("Background news refresh failed")


def _run_investor_digest_job() -> None:
    """Background-thread wrapper around scripts/run_investor_digest.main()."""
    try:
        from scripts.run_investor_digest import main as run_digest_main
        run_digest_main()
    except Exception:
        logger.exception("Background investor digest failed")


@app.post("/api/internal/news/refresh")
async def internal_trigger_news_refresh(request: Request, background_tasks: BackgroundTasks):
    """
    Kick off scripts/run_news_refresh in the background.

    Auth: X-NEA-Internal-Token header must equal NEA_INTERNAL_SECRET.
    Returns 202 immediately. Caller can poll /api/news/status for the
    matching job_runs row.
    """
    _check_internal_token(request)
    background_tasks.add_task(_run_news_refresh_job)
    logger.info("Internal trigger: news refresh queued")
    return {"status": "queued", "agent_type": "news_aggregator"}


@app.post("/api/internal/digest/run")
async def internal_trigger_investor_digest(request: Request, background_tasks: BackgroundTasks):
    """
    Kick off scripts/run_investor_digest in the background.

    Auth: X-NEA-Internal-Token header must equal NEA_INTERNAL_SECRET.
    Returns 202 immediately. Caller can poll /api/news/status (agent_type
    filter) for completion.
    """
    _check_internal_token(request)
    background_tasks.add_task(_run_investor_digest_job)
    logger.info("Internal trigger: investor digest queued")
    return {"status": "queued", "agent_type": "investor_digest"}


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
