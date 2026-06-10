-- Run this in Supabase SQL Editor to update an existing JustResume database.
-- It is safe to run more than once.

ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS alignment_report_json JSONB;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS ats_pre_check_json JSONB;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS cover_letter_text TEXT;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS latex_source TEXT;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft';
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS target_pages INT DEFAULT 1;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS last_validated_version_id TEXT;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS last_exported_version_id TEXT;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS current_step TEXT;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS progress_percentage INT;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS failure_reason TEXT;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS failure_code TEXT;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS progress_json JSONB;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE public.resume_generations ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ;

ALTER TABLE public.resume_generations DROP CONSTRAINT IF EXISTS resume_generations_status_check;
ALTER TABLE public.resume_generations
  ADD CONSTRAINT resume_generations_status_check
  CHECK (status IN ('draft', 'queued', 'running', 'completed', 'failed', 'cancelled', 'archived'));

ALTER TABLE public.generated_files ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE public.usage_events ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb;
ALTER TABLE public.user_settings ADD COLUMN IF NOT EXISTS target_resume_pages INT DEFAULT 1;
ALTER TABLE public.user_settings ADD COLUMN IF NOT EXISTS preferred_tone TEXT DEFAULT 'professional';

CREATE TABLE IF NOT EXISTS public.source_resumes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  display_name TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  file_type TEXT NOT NULL,
  content_type TEXT,
  file_size INT DEFAULT 0,
  extracted_text TEXT DEFAULT '',
  profile_json JSONB DEFAULT '{}'::jsonb,
  evidence_json JSONB DEFAULT '{}'::jsonb,
  is_active BOOLEAN DEFAULT false,
  status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_resumes_user_id ON public.source_resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_source_resumes_user_active ON public.source_resumes(user_id, is_active) WHERE status = 'active';

ALTER TABLE public.source_resumes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "source_resumes_select" ON public.source_resumes;
DROP POLICY IF EXISTS "source_resumes_insert" ON public.source_resumes;
DROP POLICY IF EXISTS "source_resumes_update" ON public.source_resumes;

CREATE POLICY "source_resumes_select" ON public.source_resumes
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "source_resumes_insert" ON public.source_resumes
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "source_resumes_update" ON public.source_resumes
  FOR UPDATE USING (auth.uid() = user_id);
