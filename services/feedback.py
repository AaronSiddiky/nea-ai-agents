"""
Outreach Feedback Service
=========================

Handles persistence of investor feedback on generated outreach emails and
promotes approved/edited emails into the few-shot example pool used during
future generation.

Phase 1:  save_feedback()  →  stores raw feedback in outreach_feedback table
          load_promoted_samples()  →  returns approved/edited rows as EmailSample
                                      objects for the generation pipeline

Phase 2 (not yet implemented):  pattern extraction job reads accumulated
          feedback and writes inferred rules to investor_learned_preferences.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.clients.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Statuses whose emails get promoted into the examples pool
PROMOTABLE_STATUSES = {"approved", "edited"}


# =============================================================================
# DATA CLASS
# =============================================================================

@dataclass
class FeedbackRecord:
    """Represents one piece of investor feedback on a generated email."""

    investor_key: str
    company_id: str
    context_type: Optional[str]
    original_message: str
    approval_status: str           # 'approved' | 'edited' | 'rejected'
    outreach_id: Optional[str] = None
    edited_message: Optional[str] = None
    investor_notes: Optional[str] = None


# =============================================================================
# PERSISTENCE
# =============================================================================

def save_feedback(record: FeedbackRecord) -> str:
    """
    Persist investor feedback to Supabase.

    Args:
        record: FeedbackRecord with all fields populated.

    Returns:
        The UUID of the created row.
    """
    supabase = get_supabase()

    data = {
        "outreach_id":      record.outreach_id,
        "investor_key":     record.investor_key,
        "company_id":       record.company_id,
        "context_type":     record.context_type,
        "original_message": record.original_message,
        "edited_message":   record.edited_message,
        "approval_status":  record.approval_status,
        "investor_notes":   record.investor_notes,
    }

    # M1b: bridge to canonical_entities
    try:
        from core.canonical_bridge import resolve_canonical_entity_id
        cid = resolve_canonical_entity_id(domain=record.company_id)
        if cid:
            data["canonical_entity_id"] = cid
    except Exception as _ex:
        logger.debug(f"canonical_bridge lookup failed (outreach_feedback): {_ex}")

    result = supabase.table("outreach_feedback").insert(data).execute()
    record_id = result.data[0]["id"] if result.data else "unknown"

    logger.info(
        f"Saved feedback investor={record.investor_key} "
        f"company={record.company_id} status={record.approval_status} id={record_id}"
    )
    return record_id


# =============================================================================
# EXAMPLE PROMOTION
# =============================================================================

def load_promoted_samples(investor_key: str) -> list:
    """
    Load all approved/edited feedback rows as EmailSample objects.

    These are injected into the few-shot example pool during generation.
    Edited emails use the investor's edited version; approved emails use the
    original unchanged. Rejected emails are never promoted.

    Args:
        investor_key: Lowercase investor key (e.g. "ashley").

    Returns:
        List of EmailSample objects ordered newest-first.
        Returns [] on any DB error so generation is never blocked.
    """
    # Lazy import to avoid circular dependency
    from agents.outreach.context import EmailSample

    supabase = get_supabase()

    try:
        result = (
            supabase.table("outreach_feedback")
            .select("*")
            .eq("investor_key", investor_key)
            .in_("approval_status", list(PROMOTABLE_STATUSES))
            .order("created_at", desc=True)
            .execute()
        )
    except Exception as exc:
        logger.warning(f"Failed to load promoted samples for {investor_key}: {exc}")
        return []

    samples = []
    for row in result.data:
        # Prefer the edited version; fall back to original
        body = row.get("edited_message") or row.get("original_message", "")
        if not body:
            continue

        samples.append(EmailSample(
            investor=investor_key,
            recipient="",
            company=row.get("company_id", ""),
            context_type=row.get("context_type") or "unknown",
            length=_classify_length(body),
            body=body,
            human_edited=row.get("approval_status") == "edited",
        ))

    logger.debug(
        f"Loaded {len(samples)} promoted sample(s) for {investor_key}"
    )
    return samples


# =============================================================================
# HELPERS
# =============================================================================

def _classify_length(body: str) -> str:
    """Classify email length bucket from word count."""
    words = len(body.split())
    if words < 80:
        return "short"
    if words < 160:
        return "medium"
    return "long"
