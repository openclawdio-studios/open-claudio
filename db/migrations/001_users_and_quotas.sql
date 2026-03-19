-- =============================================================================
-- Migration 001 — User management and daily token quotas
-- Run against an already-initialised database:
--   docker exec -i open-claudio-postgres psql -U claudio -d claudio < db/migrations/001_users_and_quotas.sql
-- =============================================================================

BEGIN;

-- ── User identity ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    username     VARCHAR(50) UNIQUE NOT NULL,
    display_name TEXT,
    is_active    BOOLEAN     NOT NULL DEFAULT true,
    is_admin     BOOLEAN     NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ
);

-- ── API keys (credentials — raw key never stored, only SHA-256 hash) ─────────
CREATE TABLE IF NOT EXISTS api_keys (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash     CHAR(64)    NOT NULL UNIQUE,   -- SHA-256 hex of the raw key
    key_prefix   VARCHAR(13) NOT NULL,           -- "clau-XXXXXXXX" for display
    name         TEXT,
    is_active    BOOLEAN     NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    expires_at   TIMESTAMPTZ
);

-- ── Per-user daily token quota ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_quotas (
    user_id      UUID    PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    daily_tokens INTEGER NOT NULL DEFAULT 100000,   -- -1 = unlimited
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Attach user_id to every trace ────────────────────────────────────────────
ALTER TABLE traces
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;

-- ── Indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_traces_user_id ON traces(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash  ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_user  ON api_keys(user_id);

-- ── Analytical view: tokens consumed per user per day ────────────────────────
CREATE OR REPLACE VIEW v_user_daily_usage AS
SELECT
    t.user_id,
    t.created_at::date                                                    AS day,
    COALESCE(SUM(t.tokens_prompt_total + t.tokens_completion_total), 0)   AS tokens_used
FROM traces t
WHERE t.user_id IS NOT NULL
  AND t.status NOT IN ('running')
GROUP BY t.user_id, t.created_at::date;

COMMIT;
