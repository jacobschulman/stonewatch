-- Supabase Schema for StoneWatch
-- Run this in your Supabase SQL Editor

-- Create the availability_logs table
CREATE TABLE IF NOT EXISTS availability_logs (
    id BIGSERIAL PRIMARY KEY,
    seen_at_iso TIMESTAMPTZ NOT NULL,
    slot_at_iso TIMESTAMPTZ NOT NULL,
    lead_minutes INTEGER,
    lead_hours NUMERIC(6,1),
    service TEXT NOT NULL,
    party_size INTEGER NOT NULL,
    weekday_slot TEXT,
    weekday_seen TEXT,
    hour_slot INTEGER,
    merchant_id TEXT DEFAULT '278278',
    source TEXT DEFAULT 'wisely',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_availability_seen_at ON availability_logs(seen_at_iso DESC);
CREATE INDEX IF NOT EXISTS idx_availability_slot_at ON availability_logs(slot_at_iso);
CREATE INDEX IF NOT EXISTS idx_availability_service ON availability_logs(service);
CREATE INDEX IF NOT EXISTS idx_availability_party_size ON availability_logs(party_size);

-- Enable Row Level Security
ALTER TABLE availability_logs ENABLE ROW LEVEL SECURITY;

-- Policy: Allow anonymous read access (for dashboard)
CREATE POLICY "Allow anonymous read access"
    ON availability_logs
    FOR SELECT
    TO anon
    USING (true);

-- Policy: Allow insert from service role (for watcher)
CREATE POLICY "Allow insert from authenticated"
    ON availability_logs
    FOR INSERT
    TO anon
    WITH CHECK (true);

-- Grant permissions
GRANT SELECT ON availability_logs TO anon;
GRANT INSERT ON availability_logs TO anon;

-- View: deduplicated unique slots (keeps first sighting of each slot)
-- The raw table logs every sighting across runs, so the same slot appears many times.
-- This view collapses duplicates using (slot_at_iso, party_size, service) as the unique key.
CREATE OR REPLACE VIEW unique_slots AS
SELECT DISTINCT ON (slot_at_iso, party_size, service)
    seen_at_iso,
    slot_at_iso,
    lead_minutes,
    lead_hours,
    service,
    party_size,
    weekday_slot,
    weekday_seen,
    hour_slot,
    merchant_id,
    source
FROM availability_logs
ORDER BY slot_at_iso, party_size, service, seen_at_iso ASC;

-- Allow dashboard to read from the view
GRANT SELECT ON unique_slots TO anon;
