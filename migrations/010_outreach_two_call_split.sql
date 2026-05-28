-- Migration 010: Two-call outreach pipeline (draft + cleanup)
-- Run in Supabase SQL Editor.
--
-- Scope:
--   The outreach generator now runs two LLM calls per request:
--     1. Sonnet draft (voice + personalization)
--     2. Haiku cleanup (de-LLM register scrub)
--
--   We persist the pre-cleanup draft alongside the final message so we can
--   diff the cleanup pass during evals, and we record whether cleanup
--   succeeded so we can monitor fallback rate.
--
-- Both columns are nullable so older rows and any deployment that disables
-- the cleanup pass remain valid.

-- =============================================================================
-- outreach_history: draft_message + cleanup_succeeded
-- =============================================================================
ALTER TABLE outreach_history
  ADD COLUMN IF NOT EXISTS draft_message TEXT;

ALTER TABLE outreach_history
  ADD COLUMN IF NOT EXISTS cleanup_succeeded BOOLEAN;

-- Optional index — useful when filtering for rows where cleanup fell back,
-- e.g. for eval triage. Cheap because most rows will have cleanup_succeeded=TRUE.
CREATE INDEX IF NOT EXISTS idx_outreach_history_cleanup_succeeded
  ON outreach_history(cleanup_succeeded)
  WHERE cleanup_succeeded = FALSE;
