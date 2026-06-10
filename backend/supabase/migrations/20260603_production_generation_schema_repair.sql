-- ============================================================================
-- Production generation schema repair
--
-- Purpose:
-- - Align live Supabase schema with the generation lifecycle code.
-- - Keep the migration additive/idempotent.
-- - Preserve all existing data.
-- - Reload PostgREST schema cache after DDL.
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- resume_generations: durable generation progress, lifecycle, and fallback data
-- ---------------------------------------------------------------------------
-- These fields are nullable/additive so existing generations remain unchanged.
ALTER TABLE public.resume_generations
  ADD COLUMN IF NOT EXISTS target_pages INTEGER DEFAULT 1,
  ADD COLUMN IF NOT EXISTS current_step TEXT,
  ADD COLUMN IF NOT EXISTS progress_json JSONB,
  ADD COLUMN IF NOT EXISTS progress_percentage INTEGER,
  ADD COLUMN IF NOT EXISTS recruiter_impression DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS recruiter_review_json JSONB,
  ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS failure_reason TEXT,
  ADD COLUMN IF NOT EXISTS failure_code TEXT,
  ADD COLUMN IF NOT EXISTS docx_fallback_path TEXT,
  ADD COLUMN IF NOT EXISTS pdf_compile_error TEXT;

-- Replace older status constraints that rejected queued/running.
-- NOT VALID avoids a full-table validation lock; validate later after checking
-- existing rows if desired.
ALTER TABLE public.resume_generations
  DROP CONSTRAINT IF EXISTS resume_generations_status_check;

ALTER TABLE public.resume_generations
  ADD CONSTRAINT resume_generations_status_check
  CHECK (status IN ('draft', 'queued', 'running', 'completed', 'failed', 'cancelled', 'archived'))
  NOT VALID;

-- Common generation lookup/listing paths.
CREATE INDEX IF NOT EXISTS idx_resume_generations_user_status
  ON public.resume_generations(user_id, status);

CREATE INDEX IF NOT EXISTS idx_resume_generations_id_user
  ON public.resume_generations(id, user_id);

CREATE INDEX IF NOT EXISTS idx_resume_generations_user_created
  ON public.resume_generations(user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- jd_cache: non-fatal cache used to avoid repeated Gemini JD parsing
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.jd_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  jd_hash TEXT NOT NULL UNIQUE,
  parsed_jd_json TEXT NOT NULL,
  ats_plan_json TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jd_cache_hash
  ON public.jd_cache(jd_hash);

CREATE INDEX IF NOT EXISTS idx_jd_cache_expires
  ON public.jd_cache(expires_at);

-- ---------------------------------------------------------------------------
-- profile_embeddings: optional RAG storage
-- ---------------------------------------------------------------------------
-- pgvector is optional. If unavailable, this migration leaves generation safe:
-- app code falls back without RAG instead of failing generation.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_available_extensions
    WHERE name = 'vector'
  ) THEN
    CREATE EXTENSION IF NOT EXISTS vector;
  ELSE
    RAISE NOTICE 'pgvector extension is not available; skipping profile_embeddings table creation.';
  END IF;
END
$$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_extension
    WHERE extname = 'vector'
  ) THEN
    CREATE TABLE IF NOT EXISTS public.profile_embeddings (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
      profile_id TEXT NOT NULL,
      source_id TEXT NOT NULL,
      chunk_type TEXT NOT NULL,
      chunk_text TEXT NOT NULL,
      embedding vector(768),
      metadata JSONB DEFAULT '{}'::jsonb,
      created_at TIMESTAMPTZ DEFAULT now(),
      updated_at TIMESTAMPTZ DEFAULT now()
    );

    CREATE INDEX IF NOT EXISTS idx_profile_embeddings_user_id
      ON public.profile_embeddings(user_id);

    CREATE INDEX IF NOT EXISTS idx_profile_embeddings_source
      ON public.profile_embeddings(user_id, source_id);

    ALTER TABLE public.profile_embeddings ENABLE ROW LEVEL SECURITY;

    DROP POLICY IF EXISTS "profile_embeddings_select" ON public.profile_embeddings;
    DROP POLICY IF EXISTS "profile_embeddings_insert" ON public.profile_embeddings;
    DROP POLICY IF EXISTS "profile_embeddings_update" ON public.profile_embeddings;
    DROP POLICY IF EXISTS "profile_embeddings_delete" ON public.profile_embeddings;

    CREATE POLICY "profile_embeddings_select" ON public.profile_embeddings
      FOR SELECT USING (auth.uid() = user_id);

    CREATE POLICY "profile_embeddings_insert" ON public.profile_embeddings
      FOR INSERT WITH CHECK (auth.uid() = user_id);

    CREATE POLICY "profile_embeddings_update" ON public.profile_embeddings
      FOR UPDATE USING (auth.uid() = user_id);

    CREATE POLICY "profile_embeddings_delete" ON public.profile_embeddings
      FOR DELETE USING (auth.uid() = user_id);

    CREATE OR REPLACE FUNCTION public.match_profile_chunks(
      query_embedding vector(768),
      match_user_id uuid,
      match_count int DEFAULT 3,
      similarity_threshold float DEFAULT 0.6
    )
    RETURNS TABLE (
      id uuid,
      source_id text,
      chunk_type text,
      chunk_text text,
      metadata jsonb,
      similarity float
    )
    LANGUAGE sql
    STABLE
    AS $fn$
      SELECT
        profile_embeddings.id,
        profile_embeddings.source_id,
        profile_embeddings.chunk_type,
        profile_embeddings.chunk_text,
        profile_embeddings.metadata,
        1 - (profile_embeddings.embedding <=> query_embedding) AS similarity
      FROM public.profile_embeddings
      WHERE
        profile_embeddings.user_id = match_user_id
        AND profile_embeddings.embedding IS NOT NULL
        AND 1 - (profile_embeddings.embedding <=> query_embedding) > similarity_threshold
      ORDER BY profile_embeddings.embedding <=> query_embedding
      LIMIT match_count;
    $fn$;
  ELSE
    RAISE NOTICE 'pgvector extension is not installed; profile_embeddings and match_profile_chunks were skipped.';
  END IF;
END
$$;

COMMIT;

-- Ask PostgREST/Supabase to refresh table, column, and function metadata.
NOTIFY pgrst, 'reload schema';
