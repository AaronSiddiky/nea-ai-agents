"""
Agent History Service
=====================

Unified history storage for all agents with automatic cleanup.

Stores:
- Meeting briefings (meeting_briefing agent)
- Digest runs (news_aggregator agent)
- Outreach messages (outreach agent)
- Audit logs (all agents)
- Job runs (all agents)

All records older than 30 days are automatically cleaned up.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional
import logging

from core.clients.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Default retention period
DEFAULT_RETENTION_DAYS = 30


# =============================================================================
# BRIEFING HISTORY (Meeting Briefing Agent)
# =============================================================================

@dataclass
class BriefingRecord:
    """A stored briefing record."""
    id: str
    company_id: str
    company_name: str
    created_at: datetime
    markdown: str
    success: bool
    error: Optional[str] = None
    data_sources: dict = None
    user_id: Optional[str] = None  # Phase 3.1: Clerk user ID

    def to_dict(self) -> dict:
        """Convert to dictionary for DB storage."""
        d = asdict(self)
        d['created_at'] = self.created_at.isoformat()
        return d

    @classmethod
    def from_row(cls, row: dict) -> "BriefingRecord":
        """Create from Supabase row."""
        created_at = row['created_at']
        if isinstance(created_at, str):
            # Handle ISO format with timezone
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            created_at = created_at.replace(tzinfo=None)

        return cls(
            id=row['id'],
            company_id=row['company_id'],
            company_name=row['company_name'],
            created_at=created_at,
            markdown=row.get('markdown', ''),
            success=row.get('success', True),
            error=row.get('error'),
            data_sources=row.get('data_sources') or {},
            user_id=row.get('user_id'),  # Phase 3.1
        )


class BriefingHistoryDB:
    """Supabase database for briefing history."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database connection.

        Args:
            db_path: Ignored - kept for API compatibility with SQLite version
        """
        # db_path is ignored, we use Supabase
        pass

    def save_briefing(self, record: BriefingRecord, user_id: Optional[str] = None) -> None:
        """Save a briefing to history.

        Args:
            record: The briefing record to save
            user_id: Optional Clerk user ID (Phase 3.1). If not provided,
                    uses record.user_id if set.
        """
        supabase = get_supabase()
        data = {
            "id": record.id,
            "company_id": record.company_id,
            "company_name": record.company_name,
            "markdown": record.markdown,
            "success": record.success,
            "error": record.error,
            "data_sources": record.data_sources or {},
        }

        # Phase 3.1: Include user_id if available
        effective_user_id = user_id or record.user_id
        if effective_user_id:
            data["user_id"] = effective_user_id

        supabase.table("briefing_history").insert(data).execute()
        logger.info(f"Saved briefing for {record.company_name}" +
                   (f" (user: {effective_user_id})" if effective_user_id else ""))

    def get_briefing(self, briefing_id: str) -> Optional[BriefingRecord]:
        """Get a briefing by ID."""
        supabase = get_supabase()
        result = supabase.table("briefing_history").select("*").eq("id", briefing_id).execute()

        if not result.data:
            return None
        return BriefingRecord.from_row(result.data[0])

    def list_briefings(
        self,
        search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BriefingRecord]:
        """List briefings with optional search."""
        supabase = get_supabase()
        query = supabase.table("briefing_history").select("*")

        if search:
            # Search in company_name and company_id using ilike
            query = query.or_(f"company_name.ilike.%{search}%,company_id.ilike.%{search}%")

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = query.execute()
        return [BriefingRecord.from_row(row) for row in result.data]

    def count_briefings(self, search: Optional[str] = None) -> int:
        """Count briefings with optional search."""
        supabase = get_supabase()
        query = supabase.table("briefing_history").select("id", count="exact")

        if search:
            query = query.or_(f"company_name.ilike.%{search}%,company_id.ilike.%{search}%")

        result = query.execute()
        return result.count or 0

    def delete_briefing(self, briefing_id: str) -> bool:
        """Delete a briefing. Returns True if deleted."""
        supabase = get_supabase()
        result = supabase.table("briefing_history").delete().eq("id", briefing_id).execute()

        deleted = len(result.data) > 0
        if deleted:
            logger.info(f"Deleted briefing {briefing_id}")
        return deleted

    def clear_all(self) -> int:
        """Clear all briefing history. Returns count deleted."""
        supabase = get_supabase()

        # First count existing records
        count_result = supabase.table("briefing_history").select("id", count="exact").execute()
        count = count_result.count or 0

        if count > 0:
            # Delete all records by using a condition that's always true
            supabase.table("briefing_history").delete().neq("id", "").execute()
            logger.info(f"Cleared {count} briefings from history")

        return count


# =============================================================================
# DIGEST HISTORY (News Aggregator Agent)
# =============================================================================

@dataclass
class DigestRecord:
    """A stored digest run record."""
    id: str
    generated_at: datetime
    story_count: int
    portfolio_count: int
    competitor_count: int
    top_stories_summary: Optional[str] = None
    investor_filter: Optional[str] = None
    success: bool = True
    error: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "DigestRecord":
        """Create from Supabase row."""
        generated_at = row['generated_at']
        if isinstance(generated_at, str):
            generated_at = datetime.fromisoformat(generated_at.replace('Z', '+00:00'))
            generated_at = generated_at.replace(tzinfo=None)

        return cls(
            id=row['id'],
            generated_at=generated_at,
            story_count=row.get('story_count', 0),
            portfolio_count=row.get('portfolio_count', 0),
            competitor_count=row.get('competitor_count', 0),
            top_stories_summary=row.get('top_stories_summary'),
            investor_filter=row.get('investor_filter'),
            success=row.get('success', True),
            error=row.get('error'),
        )


class DigestHistoryDB:
    """Supabase database for digest history."""

    def save_digest(
        self,
        story_count: int,
        portfolio_count: int,
        competitor_count: int,
        top_stories_summary: Optional[str] = None,
        investor_filter: Optional[str] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> str:
        """Save a digest run to history. Returns the record ID."""
        supabase = get_supabase()
        data = {
            "story_count": story_count,
            "portfolio_count": portfolio_count,
            "competitor_count": competitor_count,
            "top_stories_summary": top_stories_summary,
            "investor_filter": investor_filter,
            "success": success,
            "error": error,
        }

        result = supabase.table("digest_history").insert(data).execute()
        record_id = result.data[0]['id']
        logger.info(f"Saved digest with {story_count} stories")
        return record_id

    def get_digest(self, digest_id: str) -> Optional[DigestRecord]:
        """Get a digest by ID."""
        supabase = get_supabase()
        result = supabase.table("digest_history").select("*").eq("id", digest_id).execute()

        if not result.data:
            return None
        return DigestRecord.from_row(result.data[0])

    def list_digests(self, limit: int = 50, offset: int = 0) -> list[DigestRecord]:
        """List digest runs."""
        supabase = get_supabase()
        result = supabase.table("digest_history").select("*").order(
            "generated_at", desc=True
        ).range(offset, offset + limit - 1).execute()

        return [DigestRecord.from_row(row) for row in result.data]

    def count_digests(self) -> int:
        """Count total digests."""
        supabase = get_supabase()
        result = supabase.table("digest_history").select("id", count="exact").execute()
        return result.count or 0


# =============================================================================
# OUTREACH HISTORY (Outreach Agent)
# =============================================================================

@dataclass
class OutreachRecord:
    """A stored outreach message record."""
    id: str
    company_id: str
    company_name: str
    contact_name: str
    investor_key: str
    context_type: str
    output_format: str
    created_at: datetime
    message_preview: Optional[str] = None
    full_message: Optional[str] = None
    model: Optional[str] = None
    tokens_total: int = 0
    latency_ms: int = 0
    success: bool = True
    error: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "OutreachRecord":
        """Create from Supabase row."""
        created_at = row['created_at']
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            created_at = created_at.replace(tzinfo=None)

        return cls(
            id=row['id'],
            company_id=row['company_id'],
            company_name=row['company_name'],
            contact_name=row['contact_name'],
            investor_key=row['investor_key'],
            context_type=row['context_type'],
            output_format=row['output_format'],
            created_at=created_at,
            message_preview=row.get('message_preview'),
            full_message=row.get('full_message'),
            model=row.get('model'),
            tokens_total=row.get('tokens_total', 0),
            latency_ms=row.get('latency_ms', 0),
            success=row.get('success', True),
            error=row.get('error'),
        )


class OutreachHistoryDB:
    """Supabase database for outreach history."""

    def save_outreach(
        self,
        company_id: str,
        company_name: str,
        contact_name: str,
        investor_key: str,
        context_type: str,
        output_format: str,
        message_preview: Optional[str] = None,
        full_message: Optional[str] = None,
        model: Optional[str] = None,
        tokens_total: int = 0,
        latency_ms: int = 0,
        success: bool = True,
        error: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> str:
        """Save an outreach message to history. Returns the record ID.

        Args:
            company_id: Normalized company identifier
            company_name: Company display name
            contact_name: Founder/contact name
            investor_key: Investor profile key
            context_type: Context type used for generation
            output_format: 'email' or 'linkedin'
            message_preview: First 500 chars of message
            full_message: Complete message content
            model: LLM model used
            tokens_total: Total token count
            latency_ms: Generation latency
            success: Whether generation succeeded
            error: Error message if failed
            user_id: Optional Clerk user ID (Phase 3.1)
        """
        supabase = get_supabase()
        data = {
            "company_id": company_id,
            "company_name": company_name,
            "contact_name": contact_name,
            "investor_key": investor_key,
            "context_type": context_type,
            "output_format": output_format,
            "message_preview": message_preview,
            "full_message": full_message,
            "model": model,
            "tokens_total": tokens_total,
            "latency_ms": latency_ms,
            "success": success,
            "error": error,
            "user_id": user_id,
        }

        result = supabase.table("outreach_history").insert(data).execute()
        record_id = result.data[0]['id']
        logger.info(f"Saved outreach for {company_name} to {contact_name}")
        return record_id

    def get_outreach(self, outreach_id: str) -> Optional[OutreachRecord]:
        """Get an outreach record by ID."""
        supabase = get_supabase()
        result = supabase.table("outreach_history").select("*").eq("id", outreach_id).execute()

        if not result.data:
            return None
        return OutreachRecord.from_row(result.data[0])

    def list_outreach(
        self,
        company_id: Optional[str] = None,
        investor_key: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OutreachRecord]:
        """List outreach messages with optional filters."""
        supabase = get_supabase()
        query = supabase.table("outreach_history").select("*")

        if company_id:
            query = query.eq("company_id", company_id)
        if investor_key:
            query = query.eq("investor_key", investor_key)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = query.execute()
        return [OutreachRecord.from_row(row) for row in result.data]

    def count_outreach(
        self,
        company_id: Optional[str] = None,
        investor_key: Optional[str] = None,
    ) -> int:
        """Count outreach messages with optional filters."""
        supabase = get_supabase()
        query = supabase.table("outreach_history").select("id", count="exact")

        if company_id:
            query = query.eq("company_id", company_id)
        if investor_key:
            query = query.eq("investor_key", investor_key)

        result = query.execute()
        return result.count or 0


# =============================================================================
# AUDIT LOGS (All Agents)
# =============================================================================

@dataclass
class AuditLogRecord:
    """A persistent audit log record."""
    id: str
    created_at: datetime
    agent: str
    event_type: str
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    actor: Optional[str] = None
    details: Optional[dict] = None
    request_id: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict) -> "AuditLogRecord":
        """Create from Supabase row."""
        created_at = row['created_at']
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            created_at = created_at.replace(tzinfo=None)

        return cls(
            id=row['id'],
            created_at=created_at,
            agent=row['agent'],
            event_type=row['event_type'],
            action=row['action'],
            resource_type=row.get('resource_type'),
            resource_id=row.get('resource_id'),
            actor=row.get('actor'),
            details=row.get('details'),
            request_id=row.get('request_id'),
        )


class AuditLogDB:
    """Supabase database for persistent audit logs."""

    def log(
        self,
        agent: str,
        event_type: str,
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        actor: Optional[str] = None,
        details: Optional[dict] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """Log an audit event. Returns the record ID."""
        supabase = get_supabase()
        data = {
            "agent": agent,
            "event_type": event_type,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "actor": actor,
            "details": details or {},
            "request_id": request_id,
        }

        result = supabase.table("audit_logs").insert(data).execute()
        record_id = result.data[0]['id']
        logger.debug(f"Audit log: {agent}/{event_type}/{action}")
        return record_id

    def list_logs(
        self,
        agent: Optional[str] = None,
        event_type: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogRecord]:
        """List audit logs with optional filters."""
        supabase = get_supabase()
        query = supabase.table("audit_logs").select("*")

        if agent:
            query = query.eq("agent", agent)
        if event_type:
            query = query.eq("event_type", event_type)
        if resource_type:
            query = query.eq("resource_type", resource_type)

        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = query.execute()
        return [AuditLogRecord.from_row(row) for row in result.data]

    def count_logs(
        self,
        agent: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> int:
        """Count audit logs with optional filters."""
        supabase = get_supabase()
        query = supabase.table("audit_logs").select("id", count="exact")

        if agent:
            query = query.eq("agent", agent)
        if event_type:
            query = query.eq("event_type", event_type)

        result = query.execute()
        return result.count or 0


# =============================================================================
# CLEANUP FUNCTIONS (30-day retention)
# =============================================================================

def cleanup_old_briefings(keep_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete briefings older than N days. Returns count deleted."""
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    result = supabase.table("briefing_history").delete().lt("created_at", cutoff).execute()
    count = len(result.data)
    if count > 0:
        logger.info(f"Cleaned up {count} briefings older than {keep_days} days")
    return count


def cleanup_old_digests(keep_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete digest records older than N days. Returns count deleted."""
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    result = supabase.table("digest_history").delete().lt("generated_at", cutoff).execute()
    count = len(result.data)
    if count > 0:
        logger.info(f"Cleaned up {count} digest records older than {keep_days} days")
    return count


def cleanup_old_stories(keep_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete cached stories older than N days. Returns count deleted."""
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    result = supabase.table("stories").delete().lt("created_at", cutoff).execute()
    count = len(result.data)
    if count > 0:
        logger.info(f"Cleaned up {count} stories older than {keep_days} days")
    return count


def cleanup_old_outreach(keep_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete outreach records older than N days. Returns count deleted."""
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    result = supabase.table("outreach_history").delete().lt("created_at", cutoff).execute()
    count = len(result.data)
    if count > 0:
        logger.info(f"Cleaned up {count} outreach records older than {keep_days} days")
    return count


def cleanup_old_audit_logs(keep_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete audit logs older than N days. Returns count deleted."""
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    result = supabase.table("audit_logs").delete().lt("created_at", cutoff).execute()
    count = len(result.data)
    if count > 0:
        logger.info(f"Cleaned up {count} audit logs older than {keep_days} days")
    return count


def cleanup_old_job_runs(keep_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete job runs older than N days. Returns count deleted."""
    supabase = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
    result = supabase.table("databricks_job_runs").delete().lt("created_at", cutoff).execute()
    count = len(result.data)
    if count > 0:
        logger.info(f"Cleaned up {count} job runs older than {keep_days} days")
    return count


def cleanup_old_embeddings(keep_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """Delete embedding cache entries older than N days. Returns count deleted."""
    import sqlite3
    from pathlib import Path

    try:
        embedding_cache_path = Path(__file__).parent.parent / "agents" / "news_aggregator" / "embedding_cache.db"
        if not embedding_cache_path.exists():
            return 0

        conn = sqlite3.connect(str(embedding_cache_path))
        cursor = conn.cursor()

        cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).isoformat()
        cursor.execute("DELETE FROM embedding_cache WHERE created_at < ?", (cutoff,))
        count = cursor.rowcount
        conn.commit()
        conn.close()

        if count > 0:
            logger.info(f"Cleaned up {count} embeddings older than {keep_days} days")
        return count
    except Exception as e:
        logger.warning(f"Failed to clean up embeddings: {e}")
        return 0


def cleanup_all(keep_days: int = DEFAULT_RETENTION_DAYS) -> dict:
    """
    Clean up all history tables, deleting records older than N days.

    This is the main cleanup function that should be called periodically
    (e.g., daily via cron or scheduled task).

    Returns:
        Dictionary with counts of deleted records per table.
    """
    logger.info(f"Starting cleanup of records older than {keep_days} days...")

    results = {
        "briefings": cleanup_old_briefings(keep_days),
        "digests": cleanup_old_digests(keep_days),
        "stories": cleanup_old_stories(keep_days),
        "outreach": cleanup_old_outreach(keep_days),
        "audit_logs": cleanup_old_audit_logs(keep_days),
        "job_runs": cleanup_old_job_runs(keep_days),
        "embeddings": cleanup_old_embeddings(keep_days),
    }

    total = sum(results.values())
    logger.info(f"Cleanup complete. Total records deleted: {total}")

    return results


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_briefing_history() -> BriefingHistoryDB:
    """Get the briefing history database instance."""
    return BriefingHistoryDB()


def get_digest_history() -> DigestHistoryDB:
    """Get the digest history database instance."""
    return DigestHistoryDB()


def get_outreach_history() -> OutreachHistoryDB:
    """Get the outreach history database instance."""
    return OutreachHistoryDB()


def get_audit_log() -> AuditLogDB:
    """Get the audit log database instance."""
    return AuditLogDB()
