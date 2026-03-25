-- Supabase Schema for StoneWatch Run Tracking
-- Run this in your Supabase SQL Editor (after the base schema)

-- ============================================================
-- Table: watcher_runs  — one row per GitHub Actions watcher run
-- ============================================================
CREATE TABLE IF NOT EXISTS watcher_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    run_type TEXT NOT NULL DEFAULT 'base',          -- 'base' or 'vip'
    merchant_id TEXT DEFAULT '278278',
    restaurant_name TEXT DEFAULT 'Hillstone NYC',
    status TEXT NOT NULL DEFAULT 'running',          -- running, success, error
    error_message TEXT,

    -- Summary counts (filled at end of run)
    slots_checked INTEGER DEFAULT 0,
    slots_found INTEGER DEFAULT 0,
    notifications_sent INTEGER DEFAULT 0,
    slots_suppressed INTEGER DEFAULT 0,
    api_calls_made INTEGER DEFAULT 0,
    api_calls_failed INTEGER DEFAULT 0,

    -- Config snapshot (for auditability)
    config JSONB DEFAULT '{}'::jsonb,

    -- GitHub Actions metadata
    github_run_id TEXT,
    github_run_url TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_started_at ON watcher_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_run_type ON watcher_runs(run_type);
CREATE INDEX IF NOT EXISTS idx_runs_status ON watcher_runs(status);

-- ============================================================
-- Table: run_events  — one row per slot decision per run
-- ============================================================
CREATE TABLE IF NOT EXISTS run_events (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID REFERENCES watcher_runs(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    slot_key TEXT NOT NULL,              -- e.g. "278278|Thu Oct 09|7:30 PM|2|Dinner"
    slot_at_iso TEXT,                    -- reservation time ISO string
    service TEXT,                        -- Lunch / Dinner
    party_size INTEGER,
    lead_days INTEGER,

    action TEXT NOT NULL,                -- NOTIFIED, SUPPRESSED
    reason TEXT,                         -- FIRST_SIGHTING, REAPPEARED, COOLDOWN_120min, etc.
    suppression_type TEXT               -- cooldown, daily_cap, far_future, duplicate, rate_limit
);

CREATE INDEX IF NOT EXISTS idx_events_run_id ON run_events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_action ON run_events(action);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON run_events(created_at DESC);

-- ============================================================
-- RLS Policies
-- ============================================================
ALTER TABLE watcher_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_events ENABLE ROW LEVEL SECURITY;

-- Dashboard reads (anon)
CREATE POLICY "Allow anonymous read watcher_runs"
    ON watcher_runs FOR SELECT TO anon USING (true);

CREATE POLICY "Allow anonymous read run_events"
    ON run_events FOR SELECT TO anon USING (true);

-- Watcher inserts/updates (anon key from GitHub Actions)
CREATE POLICY "Allow insert watcher_runs"
    ON watcher_runs FOR INSERT TO anon WITH CHECK (true);

CREATE POLICY "Allow update watcher_runs"
    ON watcher_runs FOR UPDATE TO anon USING (true) WITH CHECK (true);

CREATE POLICY "Allow insert run_events"
    ON run_events FOR INSERT TO anon WITH CHECK (true);

-- Grants
GRANT SELECT, INSERT, UPDATE ON watcher_runs TO anon;
GRANT SELECT, INSERT ON run_events TO anon;
GRANT USAGE, SELECT ON SEQUENCE run_events_id_seq TO anon;

-- ============================================================
-- View: recent_runs  — last 200 runs with event counts
-- ============================================================
CREATE OR REPLACE VIEW recent_runs AS
SELECT
    r.*,
    COALESCE(e.notified_count, 0) AS notified_count,
    COALESCE(e.suppressed_count, 0) AS suppressed_count,
    COALESCE(e.total_events, 0) AS total_events
FROM watcher_runs r
LEFT JOIN LATERAL (
    SELECT
        COUNT(*) FILTER (WHERE action = 'NOTIFIED') AS notified_count,
        COUNT(*) FILTER (WHERE action = 'SUPPRESSED') AS suppressed_count,
        COUNT(*) AS total_events
    FROM run_events
    WHERE run_id = r.id
) e ON true
ORDER BY r.started_at DESC
LIMIT 200;

GRANT SELECT ON recent_runs TO anon;
