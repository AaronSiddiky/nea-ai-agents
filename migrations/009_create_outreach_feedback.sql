-- Migration 009: Create outreach_feedback table (if missing) and fix RLS
-- The outreach_feedback table was defined in 002_feedback_tables.sql but is absent
-- from the base supabase_schema.sql, so it was never created in production.
-- Run this in Supabase SQL Editor.

-- =============================================================================
-- OUTREACH FEEDBACK TABLE
-- =============================================================================
CREATE TABLE IF NOT EXISTS outreach_feedback (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  outreach_id      TEXT,
  investor_key     TEXT NOT NULL,
  company_id       TEXT,
  context_type     TEXT,
  original_message TEXT NOT NULL,
  edited_message   TEXT,
  approval_status  TEXT NOT NULL CHECK (approval_status IN ('approved', 'edited', 'rejected')),
  investor_notes   TEXT,
  created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_outreach_feedback_investor ON outreach_feedback(investor_key);
CREATE INDEX IF NOT EXISTS idx_outreach_feedback_context  ON outreach_feedback(investor_key, context_type);
CREATE INDEX IF NOT EXISTS idx_outreach_feedback_status   ON outreach_feedback(approval_status);
CREATE INDEX IF NOT EXISTS idx_outreach_feedback_created  ON outreach_feedback(created_at DESC);

-- =============================================================================
-- INVESTOR LEARNED PREFERENCES TABLE (also from migration 002)
-- =============================================================================
CREATE TABLE IF NOT EXISTS investor_learned_preferences (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  investor_key        TEXT NOT NULL,
  preference_text     TEXT NOT NULL,
  derived_from_count  INT  DEFAULT 0,
  version             INT  DEFAULT 1,
  is_active           BOOLEAN DEFAULT TRUE,
  created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_investor_prefs_key    ON investor_learned_preferences(investor_key);
CREATE INDEX IF NOT EXISTS idx_investor_prefs_active ON investor_learned_preferences(investor_key, is_active);

-- =============================================================================
-- ROW LEVEL SECURITY
-- Service role (SUPABASE_SERVICE_KEY) bypasses RLS entirely.
-- Public read is kept so the outreach page can query feedback.
-- Insert is open because all writes come from the authenticated backend.
-- =============================================================================
ALTER TABLE outreach_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE investor_learned_preferences ENABLE ROW LEVEL SECURITY;

-- Drop any existing policies so we start clean
DROP POLICY IF EXISTS "Public read"            ON outreach_feedback;
DROP POLICY IF EXISTS "Public insert"          ON outreach_feedback;
DROP POLICY IF EXISTS "Authenticated insert"   ON outreach_feedback;

DROP POLICY IF EXISTS "Public read"            ON investor_learned_preferences;
DROP POLICY IF EXISTS "Public insert"          ON investor_learned_preferences;
DROP POLICY IF EXISTS "Authenticated insert"   ON investor_learned_preferences;

-- Re-create policies
CREATE POLICY "Public read"   ON outreach_feedback FOR SELECT USING (true);
CREATE POLICY "Public insert" ON outreach_feedback FOR INSERT WITH CHECK (true);

CREATE POLICY "Public read"   ON investor_learned_preferences FOR SELECT USING (true);
CREATE POLICY "Public insert" ON investor_learned_preferences FOR INSERT WITH CHECK (true);

-- =============================================================================
-- VERIFICATION
-- =============================================================================
-- SELECT tablename, rowsecurity FROM pg_tables WHERE tablename IN ('outreach_feedback', 'investor_learned_preferences');
-- SELECT tablename, policyname, cmd FROM pg_policies WHERE tablename IN ('outreach_feedback', 'investor_learned_preferences');
