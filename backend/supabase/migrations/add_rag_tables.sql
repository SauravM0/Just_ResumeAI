-- RAG foundation: profile embeddings and JD cache support.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS public.profile_embeddings (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    profile_id  TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    chunk_type  TEXT NOT NULL,
    chunk_text  TEXT NOT NULL,
    embedding   vector(768),
    metadata    JSONB DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profile_emb_user ON public.profile_embeddings(user_id);
CREATE INDEX IF NOT EXISTS idx_profile_emb_source ON public.profile_embeddings(user_id, source_id);

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

CREATE TABLE IF NOT EXISTS public.jd_cache (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    jd_hash     TEXT UNIQUE NOT NULL,
    parsed_jd_json  TEXT NOT NULL,
    ats_plan_json   TEXT,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jd_cache_hash ON public.jd_cache(jd_hash);
CREATE INDEX IF NOT EXISTS idx_jd_cache_expires ON public.jd_cache(expires_at);

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
AS $$
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
$$;

-- Optional after enough data exists:
-- CREATE INDEX ON public.profile_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
