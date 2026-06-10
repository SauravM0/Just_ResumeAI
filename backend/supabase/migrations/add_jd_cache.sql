-- JD Cache: caches parsed JD results keyed by SHA-256 content hash.
-- Reduces redundant Gemini API calls for repeated job descriptions.
-- Entries expire after 24 hours; expired rows are cleaned up periodically.

CREATE TABLE IF NOT EXISTS jd_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jd_hash TEXT NOT NULL UNIQUE,
    parsed_jd_json TEXT NOT NULL,
    ats_plan_json TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jd_cache_hash ON jd_cache (jd_hash);
CREATE INDEX IF NOT EXISTS idx_jd_cache_expires ON jd_cache (expires_at);

-- Auto-delete expired entries every 24 hours via pg_cron if available.
-- If pg_cron isn't enabled, the app's background cleanup task handles it.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule(
            'jd-cache-cleanup',
            '0 3 * * *',
            $$DELETE FROM jd_cache WHERE expires_at < NOW()$$
        );
    END IF;
END
$$;
