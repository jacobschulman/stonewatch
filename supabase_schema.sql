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
