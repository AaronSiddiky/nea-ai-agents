"""
Shared Data Models and Supabase Integration
============================================

Data models for structured company data used by multiple agents.
All persistence is via Supabase (no SQLite).

Models:
- CompanyCore: Company snapshot data
- Founder: Founders and key team members
- NewsArticle: News articles
- KeySignal: Strategic signals and indicators
- CompetitorSnapshot: Competitor company data
- CompanyBundle: Complete company data bundle

Usage:
    from core.database import (
        CompanyCore, Founder, NewsArticle, KeySignal, CompanyBundle,
        get_company_bundle_from_supabase,
        sync_company_to_supabase,
    )
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class CompanyCore:
    """Company core data matching company_core table schema."""
    company_id: str  # URL/domain used for lookup
    company_name: str
    founding_date: Optional[str] = None
    hq: Optional[str] = None
    employee_count: Optional[int] = None
    total_funding: Optional[float] = None
    products: Optional[str] = None
    customers: Optional[str] = None
    arr_apr: Optional[str] = None
    last_round_date: Optional[str] = None
    last_round_funding: Optional[float] = None
    investors: list = field(default_factory=list)  # list of investor names
    web_traffic_trend: Optional[str] = None  # e.g., "+5.2% (30d)"
    website_update: Optional[str] = None  # NULL; pending Tavily
    hiring_firing: Optional[str] = None  # e.g., "-9.7% (90d)"
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source_map: dict = field(default_factory=dict)  # field -> source mapping

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        d = asdict(self)
        d['source_map'] = json.dumps(d['source_map'])
        d['investors'] = json.dumps(d['investors'])
        return d


@dataclass
class Founder:
    """Founder/key team member matching founders table schema."""
    company_id: str
    name: str
    role_title: Optional[str] = None
    linkedin_url: Optional[str] = None
    background: Optional[str] = None  # NULL; pending Swarm
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "harmonic"  # or "pending_swarm" for background

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)


@dataclass
class NewsArticle:
    """News article matching news table schema."""
    company_id: str
    article_headline: str
    outlet: Optional[str] = None
    url: Optional[str] = None
    published_date: Optional[str] = None
    excerpts: Optional[str] = None  # Article content/excerpts for LLM context
    synopsis: Optional[str] = None  # 1-2 sentence VC-relevant summary
    sentiment: Optional[str] = None  # "positive", "negative", or "neutral"
    news_type: Optional[str] = None  # Signal type: funding, acquisition, executive_change, etc.
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "news_api"  # or "pending_news_api"

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)


@dataclass
class KeySignal:
    """Key signal matching key_signals table schema."""
    company_id: str
    signal_type: str  # hiring, traffic, funding, website_update
    description: str
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    source: str = "harmonic"  # or "pending_tavily"

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)


@dataclass
class CompetitorSnapshot:
    """Competitor company data for briefing competitive landscape section."""
    company_id: str  # The subject company this competitor relates to
    competitor_name: str
    competitor_domain: Optional[str] = None
    competitor_type: str = "startup"  # "startup" or "incumbent"
    description: Optional[str] = None
    funding_total: Optional[float] = None
    funding_stage: Optional[str] = None
    funding_last_amount: Optional[float] = None
    funding_last_date: Optional[str] = None
    headcount: Optional[int] = None
    tags: Optional[str] = None
    harmonic_id: Optional[str] = None
    observed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CompanyBundle:
    """Complete company data bundle for briefing generation."""
    company_core: Optional[CompanyCore] = None
    founders: list[Founder] = field(default_factory=list)
    news: list[NewsArticle] = field(default_factory=list)
    key_signals: list[KeySignal] = field(default_factory=list)
    competitors: list[CompetitorSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert entire bundle to dictionary."""
        return {
            'company_core': asdict(self.company_core) if self.company_core else None,
            'founders': [asdict(f) for f in self.founders],
            'news': [asdict(n) for n in self.news],
            'key_signals': [asdict(s) for s in self.key_signals],
            'competitors': [asdict(c) for c in self.competitors],
        }


# =============================================================================
# SUPABASE SYNC FUNCTIONS
# =============================================================================
#
# NOTE: The SQLite Database class has been removed. All persistence is now
# via Supabase. See the sync_*_to_supabase and read_*_from_supabase functions
# below for data access.
#
# Migration completed as part of Task 2.7: Railway + SQLite decommissioning.
# =============================================================================


def sync_founders_to_supabase(
    founders: list[Founder],
    company_name: Optional[str] = None,
) -> dict:
    """
    Sync founders to Supabase for Lovable UI access.

    Args:
        founders: List of Founder objects to sync
        company_name: Optional company name for denormalization

    Returns:
        Dict with 'synced' count and any 'errors'
    """
    if not founders:
        return {'synced': 0, 'errors': []}

    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured, skipping sync: {e}")
        return {'synced': 0, 'errors': [str(e)]}

    synced = 0
    errors = []

    from core.canonical_bridge import resolve_canonical_entity_id

    for founder in founders:
        try:
            data = {
                'company_id': founder.company_id,
                'company_name': company_name,
                'name': founder.name,
                'role_title': founder.role_title,
                'linkedin_url': founder.linkedin_url,
                'background': founder.background,
                'source': founder.source,
                'observed_at': founder.observed_at,
            }
            cid = resolve_canonical_entity_id(domain=founder.company_id, name=company_name)
            if cid:
                data['canonical_entity_id'] = cid

            # Upsert (insert or update on conflict)
            supabase.table('founders').upsert(
                data,
                on_conflict='company_id,name'
            ).execute()
            synced += 1

        except Exception as e:
            errors.append(f"{founder.name}: {str(e)}")
            logger.warning(f"Failed to sync founder {founder.name}: {e}")

    if synced > 0:
        logger.info(f"Synced {synced} founders to Supabase")

    return {'synced': synced, 'errors': errors}


def sync_company_to_supabase(company: CompanyCore) -> dict:
    """
    Sync company data to Supabase briefing_companies table for Lovable UI access.

    Args:
        company: CompanyCore object to sync

    Returns:
        Dict with 'synced' bool and 'error' str|None
    """
    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured, skipping company sync: {e}")
        return {'synced': False, 'error': str(e)}

    try:
        from core.canonical_bridge import resolve_canonical_entity_id

        data = {
            'company_id': company.company_id,
            'company_name': company.company_name,
            'founding_date': company.founding_date,
            'hq': company.hq,
            'employee_count': company.employee_count,
            'total_funding': company.total_funding,
            'products': company.products,
            'customers': company.customers,
            'arr_apr': company.arr_apr,
            'last_round_date': company.last_round_date,
            'last_round_funding': company.last_round_funding,
            'investors': company.investors,
            'web_traffic_trend': company.web_traffic_trend,
            'website_update': company.website_update,
            'hiring_firing': company.hiring_firing,
            'observed_at': company.observed_at,
            'source_map': company.source_map,
        }
        cid = resolve_canonical_entity_id(domain=company.company_id, name=company.company_name)
        if cid:
            data['canonical_entity_id'] = cid

        # Upsert (insert or update on conflict)
        supabase.table('briefing_companies').upsert(
            data,
            on_conflict='company_id'
        ).execute()

        logger.info(f"Synced company {company.company_id} to Supabase")
        return {'synced': True, 'error': None}

    except Exception as e:
        logger.warning(f"Failed to sync company {company.company_id}: {e}")
        return {'synced': False, 'error': str(e)}


def sync_news_to_supabase(news: list[NewsArticle], company_id: str) -> dict:
    """
    Sync news articles to Supabase briefing_news table for Lovable UI access.

    Args:
        news: List of NewsArticle objects to sync
        company_id: Company ID for logging

    Returns:
        Dict with 'synced' count and 'errors' list
    """
    if not news:
        return {'synced': 0, 'errors': []}

    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured, skipping news sync: {e}")
        return {'synced': 0, 'errors': [str(e)]}

    synced = 0
    errors = []

    from core.canonical_bridge import resolve_canonical_entity_id
    cid = resolve_canonical_entity_id(domain=company_id)

    for article in news:
        try:
            data = {
                'company_id': article.company_id,
                'article_headline': article.article_headline,
                'outlet': article.outlet,
                'url': article.url,
                'published_date': article.published_date,
                'excerpts': article.excerpts,
                'synopsis': article.synopsis,
                'sentiment': article.sentiment,
                'news_type': article.news_type,
                'observed_at': article.observed_at,
                'source': article.source,
            }
            if cid:
                data['canonical_entity_id'] = cid

            # Upsert (insert or update on conflict)
            supabase.table('briefing_news').upsert(
                data,
                on_conflict='company_id,url'
            ).execute()
            synced += 1

        except Exception as e:
            errors.append(f"{article.article_headline[:50]}: {str(e)}")
            logger.warning(f"Failed to sync news article: {e}")

    if synced > 0:
        logger.info(f"Synced {synced} news articles to Supabase for {company_id}")

    return {'synced': synced, 'errors': errors}


def sync_competitors_to_supabase(competitors: list[CompetitorSnapshot]) -> dict:
    """
    Sync competitor snapshots to Supabase briefing_competitors table.

    Args:
        competitors: List of CompetitorSnapshot objects to sync

    Returns:
        Dict with 'synced' count and 'errors' list
    """
    if not competitors:
        return {'synced': 0, 'errors': []}

    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured, skipping competitor sync: {e}")
        return {'synced': 0, 'errors': [str(e)]}

    synced = 0
    errors = []

    from core.canonical_bridge import resolve_canonical_entity_id

    for c in competitors:
        try:
            data = {
                'company_id': c.company_id,
                'competitor_name': c.competitor_name,
                'competitor_domain': c.competitor_domain,
                'competitor_type': c.competitor_type,
                'description': c.description,
                'funding_total': c.funding_total,
                'funding_stage': c.funding_stage,
                'funding_last_amount': c.funding_last_amount,
                'funding_last_date': c.funding_last_date,
                'headcount': c.headcount,
                'tags': c.tags,
                'harmonic_id': c.harmonic_id,
                'observed_at': c.observed_at,
            }
            cid = resolve_canonical_entity_id(domain=c.company_id, name=c.competitor_name)
            if cid:
                data['canonical_entity_id'] = cid

            supabase.table('briefing_competitors').upsert(
                data,
                on_conflict='company_id,competitor_name'
            ).execute()
            synced += 1

        except Exception as e:
            errors.append(f"{c.competitor_name}: {str(e)}")
            logger.warning(f"Failed to sync competitor {c.competitor_name}: {e}")

    if synced > 0:
        logger.info(f"Synced {synced} competitors to Supabase")

    return {'synced': synced, 'errors': errors}


def sync_signals_to_supabase(signals: list[KeySignal]) -> dict:
    """
    Sync key signals to Supabase briefing_signals table.

    Returns:
        Dict with 'synced' count and 'errors' list
    """
    if not signals:
        return {'synced': 0, 'errors': []}

    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured, skipping signals sync: {e}")
        return {'synced': 0, 'errors': [str(e)]}

    synced = 0
    errors = []

    from core.canonical_bridge import resolve_canonical_entity_id

    for signal in signals:
        try:
            data = {
                'company_id': signal.company_id,
                'signal_type': signal.signal_type,
                'description': signal.description,
                'source': signal.source,
                'observed_at': signal.observed_at,
            }
            cid = resolve_canonical_entity_id(domain=signal.company_id)
            if cid:
                data['canonical_entity_id'] = cid
            supabase.table('briefing_signals').upsert(
                data,
                on_conflict='company_id,signal_type,description'
            ).execute()
            synced += 1
        except Exception as e:
            errors.append(f"{signal.signal_type}: {str(e)}")
            logger.warning(f"Failed to sync signal {signal.signal_type}: {e}")

    if synced > 0:
        logger.info(f"Synced {synced} signals to Supabase")

    return {'synced': synced, 'errors': errors}


# =============================================================================
# SUPABASE READ FUNCTIONS
# =============================================================================

def _coerce_json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def read_company_from_supabase(company_id: str) -> Optional[CompanyCore]:
    """Read company core data from Supabase briefing_companies."""
    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured: {e}")
        return None

    try:
        resp = (
            supabase.table('briefing_companies')
            .select('*')
            .eq('company_id', company_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.warning(f"Failed to read company from Supabase: {e}")
        return None

    rows = resp.data or []
    if not rows:
        return None

    row = rows[0]
    return CompanyCore(
        company_id=row['company_id'],
        company_name=row.get('company_name') or '',
        founding_date=row.get('founding_date'),
        hq=row.get('hq'),
        employee_count=row.get('employee_count'),
        total_funding=row.get('total_funding'),
        products=row.get('products'),
        customers=row.get('customers'),
        arr_apr=row.get('arr_apr'),
        last_round_date=row.get('last_round_date'),
        last_round_funding=row.get('last_round_funding'),
        investors=_coerce_json(row.get('investors'), []),
        web_traffic_trend=row.get('web_traffic_trend'),
        website_update=row.get('website_update'),
        hiring_firing=row.get('hiring_firing'),
        observed_at=row.get('observed_at') or datetime.utcnow().isoformat(),
        source_map=_coerce_json(row.get('source_map'), {}),
    )


def read_founders_from_supabase(company_id: str) -> list[Founder]:
    """Read founders from Supabase founders table."""
    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured: {e}")
        return []

    try:
        resp = (
            supabase.table('founders')
            .select('*')
            .eq('company_id', company_id)
            .execute()
        )
    except Exception as e:
        logger.warning(f"Failed to read founders from Supabase: {e}")
        return []

    out = []
    for row in (resp.data or []):
        out.append(Founder(
            company_id=row['company_id'],
            name=row['name'],
            role_title=row.get('role_title'),
            linkedin_url=row.get('linkedin_url'),
            background=row.get('background'),
            observed_at=row.get('observed_at') or datetime.utcnow().isoformat(),
            source=row.get('source') or 'harmonic',
        ))
    return out


def read_news_from_supabase(company_id: str, limit: int = 10) -> list[NewsArticle]:
    """Read news articles from Supabase briefing_news."""
    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured: {e}")
        return []

    try:
        resp = (
            supabase.table('briefing_news')
            .select('*')
            .eq('company_id', company_id)
            .order('published_date', desc=True)
            .order('observed_at', desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as e:
        logger.warning(f"Failed to read news from Supabase: {e}")
        return []

    out = []
    for row in (resp.data or []):
        out.append(NewsArticle(
            company_id=row['company_id'],
            article_headline=row['article_headline'],
            outlet=row.get('outlet'),
            url=row.get('url'),
            published_date=row.get('published_date'),
            excerpts=row.get('excerpts'),
            synopsis=row.get('synopsis'),
            sentiment=row.get('sentiment'),
            news_type=row.get('news_type'),
            observed_at=row.get('observed_at') or datetime.utcnow().isoformat(),
            source=row.get('source') or 'news_api',
        ))
    return out


def read_signals_from_supabase(company_id: str) -> list[KeySignal]:
    """Read key signals from Supabase briefing_signals."""
    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured: {e}")
        return []

    try:
        resp = (
            supabase.table('briefing_signals')
            .select('*')
            .eq('company_id', company_id)
            .order('observed_at', desc=True)
            .execute()
        )
    except Exception as e:
        logger.warning(f"Failed to read signals from Supabase: {e}")
        return []

    out = []
    for row in (resp.data or []):
        out.append(KeySignal(
            company_id=row['company_id'],
            signal_type=row['signal_type'],
            description=row['description'],
            observed_at=row.get('observed_at') or datetime.utcnow().isoformat(),
            source=row.get('source') or 'harmonic',
        ))
    return out


def read_competitors_from_supabase(company_id: str) -> list[CompetitorSnapshot]:
    """Read competitors from Supabase briefing_competitors."""
    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured: {e}")
        return []

    try:
        resp = (
            supabase.table('briefing_competitors')
            .select('*')
            .eq('company_id', company_id)
            .execute()
        )
    except Exception as e:
        logger.warning(f"Failed to read competitors from Supabase: {e}")
        return []

    out = []
    for row in (resp.data or []):
        row.pop('id', None)
        row.pop('created_at', None)
        out.append(CompetitorSnapshot(**row))
    return out


def get_company_bundle_from_supabase(company_id: str) -> CompanyBundle:
    """Assemble complete CompanyBundle from Supabase only (no SQLite)."""
    return CompanyBundle(
        company_core=read_company_from_supabase(company_id),
        founders=read_founders_from_supabase(company_id),
        news=read_news_from_supabase(company_id),
        key_signals=read_signals_from_supabase(company_id),
        competitors=read_competitors_from_supabase(company_id),
    )


def patch_company_website_update(company_id: str, website_update: str) -> None:
    """Update only the website_update field on briefing_companies."""
    try:
        from core.clients import get_supabase
        supabase = get_supabase()
    except Exception as e:
        logger.warning(f"Supabase not configured, skipping website_update patch: {e}")
        return

    try:
        supabase.table('briefing_companies').update(
            {'website_update': website_update}
        ).eq('company_id', company_id).execute()
    except Exception as e:
        logger.warning(f"Failed to patch website_update for {company_id}: {e}")
