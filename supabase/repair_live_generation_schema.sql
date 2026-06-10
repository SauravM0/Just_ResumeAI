-- ============================================================================
-- JustResume live generation schema repair
-- Target Supabase project:
--   https://sqyzzsegcamnvhnyxzux.supabase.co
--
-- Run this manually in Supabase SQL Editor for the live project above.
-- This script is additive/idempotent: it does not delete data or remove columns.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Add generation lifecycle/progress/fallback columns expected by backend.
-- ---------------------------------------------------------------------------
ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS target_pages INTEGER DEFAULT 1,
  ADD COLUMN IF NOT EXISTS current_step TEXT,
  ADD COLUMN IF NOT EXISTS progress_percentage INTEGER,
  ADD COLUMN IF NOT EXISTS failure_reason TEXT,
  ADD COLUMN IF NOT EXISTS failure_code TEXT,
  ADD COLUMN IF NOT EXISTS progress_json JSONB,
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS recruiter_review_json JSONB,
  ADD COLUMN IF NOT EXISTS recruiter_impression DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS docx_fallback_path TEXT,
  ADD COLUMN IF NOT EXISTS pdf_compile_error TEXT;

ALTER TABLE public.user_settings
  ADD COLUMN IF NOT EXISTS aggressive_ats_default BOOLEAN DEFAULT false;

-- ---------------------------------------------------------------------------
-- 2. Replace stale status constraint that rejects queued/running.
-- ---------------------------------------------------------------------------
ALTER TABLE public.resume_generations
  DROP CONSTRAINT IF EXISTS resume_generations_status_check;

ALTER TABLE public.resume_generations
  ADD CONSTRAINT resume_generations_status_check
  CHECK (status IN ('draft', 'queued', 'running', 'completed', 'failed', 'cancelled', 'archived'))
  NOT VALID;

-- ---------------------------------------------------------------------------
-- 3. Create JD cache table used by backend to avoid repeated Gemini JD parsing.
--    Keep parsed_jd_json/ats_plan_json as TEXT because the current backend
--    stores JSON strings and reads them with json.loads(...).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.jd_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jd_hash TEXT NOT NULL UNIQUE,
  parsed_jd_json TEXT NOT NULL,
  ats_plan_json TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 4. Add indexes for common generation and cache lookups.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_resume_generations_user_status
  ON public.resume_generations(user_id, status);

CREATE INDEX IF NOT EXISTS idx_resume_generations_id_user
  ON public.resume_generations(id, user_id);

CREATE INDEX IF NOT EXISTS idx_resume_generations_user_created
  ON public.resume_generations(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jd_cache_hash
  ON public.jd_cache(jd_hash);

CREATE INDEX IF NOT EXISTS idx_jd_cache_expires
  ON public.jd_cache(expires_at);

COMMIT;

-- ---------------------------------------------------------------------------
-- 5. Force PostgREST/Supabase to reload schema cache.
-- ---------------------------------------------------------------------------
NOTIFY pgrst, 'reload schema';

-- ============================================================================
-- Verification queries
-- Run these after the repair statements above. They should return:
-- - all required resume_generations columns
-- - one status constraint containing queued and running
-- - jd_cache exists
-- ============================================================================

-- Required columns: expect 12 rows.
SELECT
  column_name,
  data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'resume_generations'
  AND column_name IN (
    'target_pages',
    'current_step',
    'progress_percentage',
    'failure_reason',
    'failure_code',
    'progress_json',
    'completed_at',
    'failed_at',
    'recruiter_review_json',
    'recruiter_impression',
    'docx_fallback_path',
    'pdf_compile_error'
  )
ORDER BY column_name;

-- Status constraint: expect check definition to include queued and running.
SELECT
  conname,
  pg_get_constraintdef(oid) AS constraint_definition,
  pg_get_constraintdef(oid) LIKE '%queued%' AS allows_queued,
  pg_get_constraintdef(oid) LIKE '%running%' AS allows_running
FROM pg_constraint
WHERE conrelid = 'public.resume_generations'::regclass
  AND conname = 'resume_generations_status_check';

-- jd_cache table: expect one row with exists = true.
SELECT
  to_regclass('public.jd_cache') IS NOT NULL AS jd_cache_exists;
