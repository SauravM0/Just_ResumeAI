-- ============================================================================
-- Phase 5: Database Schema Hardening
-- 
-- Safe, additive migration for resume_generations progress tracking, status
-- constraints, and missing query-performance indexes.
-- 
-- Run order: standalone (depends only on resume_generations table existing).
-- Safe to run multiple times (all statements use IF NOT EXISTS / NOT VALID).
-- ============================================================================

-- ============================================================================
-- PART 1: Generation progress & failure tracking fields
-- ============================================================================
-- These columns enable durable progress tracking without relying solely on
-- in-memory SSE channels. The app code computes current_step/progress from
-- status when DB columns are absent, so adding them is non-breaking.

ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS current_step TEXT;

ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS progress_percentage INTEGER;

ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS failure_reason TEXT;

ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS failure_code TEXT;

ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS progress_json JSONB;

ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ;


-- ============================================================================
-- PART 2: Status value constraint (safe, non-blocking)
-- ============================================================================
-- The resume_generations.status column is currently unconstrained TEXT.
-- Adding a CHECK constraint ensures only valid lifecycle values are stored.
--
-- Approach: NOT VALID to avoid long table locks on large production tables.
-- VALIDATE CONSTRAINT can be run later in a maintenance window.

-- Preflight: find any existing rows with invalid status values.
-- Run before enabling constraint:
--   SELECT DISTINCT status FROM public.resume_generations
--   WHERE status NOT IN ('draft','queued','running','completed','failed','cancelled','archived');

-- Apply/replace constraint (does not re-check existing rows).
-- Older setup scripts created the same constraint name with fewer statuses,
-- so replace it instead of only adding when absent.
ALTER TABLE public.resume_generations
    DROP CONSTRAINT IF EXISTS resume_generations_status_check;

ALTER TABLE public.resume_generations
    ADD CONSTRAINT resume_generations_status_check
    CHECK (status IN ('draft', 'queued', 'running', 'completed', 'failed', 'cancelled', 'archived'))
    NOT VALID;

-- Optional (run in maintenance window after verifying no violations exist):
--   ALTER TABLE public.resume_generations VALIDATE CONSTRAINT resume_generations_status_check;


-- ============================================================================
-- PART 3: Useful query-performance indexes
-- ============================================================================
-- These support the most common access patterns: listing by user+status,
-- active generation lookup, and sorted event queries.

CREATE INDEX IF NOT EXISTS idx_resume_generations_user_status
  ON public.resume_generations(user_id, status);

CREATE INDEX IF NOT EXISTS idx_resume_generations_id_user
  ON public.resume_generations(id, user_id);

CREATE INDEX IF NOT EXISTS idx_usage_events_user_created
  ON public.usage_events(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_resumes_user_active
  ON public.source_resumes(user_id, is_active);

-- Guard indexes that may already exist from add_rag_tables.sql
CREATE INDEX IF NOT EXISTS idx_profile_embeddings_user_id
  ON public.profile_embeddings(user_id);

CREATE INDEX IF NOT EXISTS idx_jd_cache_hash
  ON public.jd_cache(jd_hash);

CREATE INDEX IF NOT EXISTS idx_jd_cache_expires
  ON public.jd_cache(expires_at);


-- ============================================================================
-- PART 4: generated_files safe indexes
-- ============================================================================
-- The active export code path returns direct downloads (no storage persistence).
-- The generated_files table exists for future durable-file support.
-- These indexes ensure the table is ready when Phase 7+ enables it.

CREATE INDEX IF NOT EXISTS idx_generated_files_user_gen
  ON public.generated_files(user_id, generation_id);

CREATE INDEX IF NOT EXISTS idx_generated_files_user_gen_type
  ON public.generated_files(user_id, generation_id, file_type);
