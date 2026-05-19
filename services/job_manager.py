"""
Job Manager Service
===================

Manages job runs for tracking agent execution status.
Persisted to NEA Scout's existing `databricks_job_runs` table (migration 013).

Column translation between Stanford's original `job_runs` schema and the
shared `databricks_job_runs` table happens entirely inside this module so
callers keep using the friendly Stanford field names:

    Stanford field    ->  databricks_job_runs column
    -----------------     ---------------------------
    agent_type        ->  job_type
    status            ->  status
    created_at        ->  created_at
    started_at        ->  (dropped; created_at serves as start time)
    completed_at      ->  updated_at
    error             ->  error_message
    result_summary    ->  result (json-stringified into text column)
    triggered_by      ->  user_id (only when value is a UUID; else null)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import json
import logging
import re

from core.clients.supabase_client import get_supabase

logger = logging.getLogger(__name__)


_TABLE = "databricks_job_runs"
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _maybe_uuid(value: Optional[str]) -> Optional[str]:
    """Return value only if it looks like a UUID; else None. Used to safely
    drop literal triggers like 'api' / 'cron' before writing to a uuid column."""
    if value and isinstance(value, str) and _UUID_RE.match(value):
        return value
    return None


def _serialize_result(result_summary: Optional[dict]) -> Optional[str]:
    """databricks_job_runs.result is text, not jsonb — stringify dicts."""
    if result_summary is None:
        return None
    if isinstance(result_summary, str):
        return result_summary
    try:
        return json.dumps(result_summary, default=str)
    except (TypeError, ValueError):
        return str(result_summary)


def _deserialize_result(value) -> dict:
    """Inverse of _serialize_result; tolerates legacy jsonb rows too."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return {"_raw": value}
    return {}


@dataclass
class JobRun:
    """A job run record (Stanford-shaped facade over databricks_job_runs)."""
    id: str
    agent_type: str
    status: str  # pending, running, completed, failed, cancelled
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result_summary: dict = field(default_factory=dict)
    triggered_by: str = "api"

    @classmethod
    def from_row(cls, row: dict) -> "JobRun":
        """Hydrate from a `databricks_job_runs` row."""
        def parse_dt(val):
            if val is None:
                return None
            if isinstance(val, str):
                return datetime.fromisoformat(val.replace('Z', '+00:00')).replace(tzinfo=None)
            return val

        # databricks_job_runs uses created_at + updated_at; we expose
        # created_at as both Stanford's created_at and started_at, and
        # updated_at as completed_at (only meaningful once status is terminal).
        created = parse_dt(row.get('created_at'))
        updated = parse_dt(row.get('updated_at'))
        status = row.get('status', 'pending')
        return cls(
            id=row['id'],
            agent_type=row.get('job_type', ''),
            status=status,
            created_at=created,
            started_at=created if status in ('running', 'completed', 'failed', 'cancelled') else None,
            completed_at=updated if status in ('completed', 'failed', 'cancelled') else None,
            error=row.get('error_message'),
            result_summary=_deserialize_result(row.get('result')),
            triggered_by=row.get('user_id') or 'api',
        )


class JobManager:
    """Manages job runs in Supabase (writes to databricks_job_runs)."""

    def create_job(self, agent_type: str, triggered_by: str = "api") -> JobRun:
        supabase = get_supabase()
        data = {
            "job_type": agent_type,
            "status": "pending",
            "user_id": _maybe_uuid(triggered_by),
        }
        result = supabase.table(_TABLE).insert(data).execute()
        row = result.data[0]
        logger.info(f"Created job {row['id']} for {agent_type}")
        return JobRun.from_row(row)

    def start_job(self, job_id: str) -> None:
        supabase = get_supabase()
        supabase.table(_TABLE).update({
            "status": "running",
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", job_id).execute()
        logger.info(f"Started job {job_id}")

    def complete_job(self, job_id: str, result_summary: dict = None) -> None:
        supabase = get_supabase()
        supabase.table(_TABLE).update({
            "status": "completed",
            "updated_at": datetime.utcnow().isoformat(),
            "result": _serialize_result(result_summary or {}),
        }).eq("id", job_id).execute()
        logger.info(f"Completed job {job_id}")

    def fail_job(self, job_id: str, error: str) -> None:
        supabase = get_supabase()
        supabase.table(_TABLE).update({
            "status": "failed",
            "updated_at": datetime.utcnow().isoformat(),
            "error_message": error,
        }).eq("id", job_id).execute()
        logger.error(f"Failed job {job_id}: {error}")

    def get_job(self, job_id: str) -> Optional[JobRun]:
        supabase = get_supabase()
        result = supabase.table(_TABLE).select("*").eq("id", job_id).execute()
        if result.data:
            return JobRun.from_row(result.data[0])
        return None

    def get_latest_job(self, agent_type: str) -> Optional[JobRun]:
        supabase = get_supabase()
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("job_type", agent_type)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return JobRun.from_row(result.data[0])
        return None

    def get_running_job(self, agent_type: str) -> Optional[JobRun]:
        supabase = get_supabase()
        result = (
            supabase.table(_TABLE)
            .select("*")
            .eq("job_type", agent_type)
            .eq("status", "running")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data:
            return JobRun.from_row(result.data[0])
        return None

    def list_jobs(self, agent_type: str = None, limit: int = 10) -> list[JobRun]:
        supabase = get_supabase()
        query = supabase.table(_TABLE).select("*")
        if agent_type:
            query = query.eq("job_type", agent_type)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return [JobRun.from_row(row) for row in result.data]


_job_manager = None


def get_job_manager() -> JobManager:
    global _job_manager
    if _job_manager is None:
        _job_manager = JobManager()
    return _job_manager
