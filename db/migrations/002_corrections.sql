-- =============================================================================
-- Migration 002 — Corrections table for Phase 7 (Data Collection)
-- Run against an already-initialised database:
--   docker exec -i open-claudio-postgres psql -U claudio -d claudio < db/migrations/002_corrections.sql
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS corrections (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id      UUID        REFERENCES traces(id) ON DELETE SET NULL,
    agent_name    VARCHAR(100),          -- which agent handled the original request
    tool_name     VARCHAR(100),          -- last tool called before the correction
    wrong_value   TEXT,                  -- the wrong value the agent used (extracted)
    correct_value TEXT,                  -- the correct value the user intended (extracted)
    raw_message   TEXT        NOT NULL,  -- the full correction message verbatim
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_corrections_trace_id   ON corrections (trace_id);
CREATE INDEX IF NOT EXISTS idx_corrections_tool_name  ON corrections (tool_name);
CREATE INDEX IF NOT EXISTS idx_corrections_created_at ON corrections (created_at DESC);

COMMIT;
