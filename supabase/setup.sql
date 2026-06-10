-- ============================================
-- JustResume AI - Complete Supabase Database Setup
-- ============================================
-- Run this entire file in Supabase SQL Editor once
-- This includes: schema creation, indexes, RLS, and verification

-- ============================================
-- PART 1: CREATE TABLES
-- ============================================

CREATE TABLE IF NOT EXISTS public.allowed_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT NOT NULL UNIQUE,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.user_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  profile_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  profile_completion_score INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id)
);

CREATE TABLE IF NOT EXISTS public.resume_generations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  profile_id UUID,
  job_title TEXT,
  company TEXT,
  raw_jd_text TEXT NOT NULL,
  parsed_jd_json JSONB,
  resume_json JSONB,
  ats_score_json JSONB,
  alignment_report_json JSONB,
  ats_pre_check_json JSONB,
  cover_letter_text TEXT,
  latex_source TEXT,
  status TEXT DEFAULT 'draft',
  target_pages INT DEFAULT 1,
  last_validated_version_id TEXT,
  last_exported_version_id TEXT,
  current_step TEXT,
  progress_percentage INT,
  failure_reason TEXT,
  failure_code TEXT,
  progress_json JSONB,
  completed_at TIMESTAMPTZ,
  failed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.generated_files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  generation_id UUID,
  file_type TEXT,
  storage_path TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.usage_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID,
  generation_id UUID,
  event_type TEXT,
  metadata_json JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.user_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE,
  settings_json JSONB,
  target_resume_pages INT DEFAULT 1,
  preferred_tone TEXT DEFAULT 'professional',
  aggressive_ats_default BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

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

-- Existing Supabase projects created from an older setup.sql need these migrations.
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
ALTER TABLE public.generated_files ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE public.usage_events ADD COLUMN IF NOT EXISTS metadata_json JSONB DEFAULT '{}'::jsonb;
ALTER TABLE public.user_settings ADD COLUMN IF NOT EXISTS target_resume_pages INT DEFAULT 1;
ALTER TABLE public.user_settings ADD COLUMN IF NOT EXISTS preferred_tone TEXT DEFAULT 'professional';
ALTER TABLE public.user_settings ADD COLUMN IF NOT EXISTS aggressive_ats_default BOOLEAN DEFAULT false;

-- ============================================
-- PART 2: CREATE INDEXES
-- ============================================

CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON public.user_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_resume_generations_user_id ON public.resume_generations(user_id);
CREATE INDEX IF NOT EXISTS idx_resume_generations_user_created ON public.resume_generations(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_resume_generations_created_at ON public.resume_generations(created_at);
CREATE INDEX IF NOT EXISTS idx_generated_files_user_id ON public.generated_files(user_id);
CREATE INDEX IF NOT EXISTS idx_generated_files_generation_id ON public.generated_files(generation_id);
CREATE INDEX IF NOT EXISTS idx_generated_files_expires_at ON public.generated_files(expires_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_user_id ON public.usage_events(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_generation_id ON public.usage_events(generation_id);
CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON public.user_settings(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_allowed_users_email_lower_unique ON public.allowed_users(LOWER(email));
CREATE INDEX IF NOT EXISTS idx_allowed_users_email_active ON public.allowed_users(LOWER(email)) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_source_resumes_user_id ON public.source_resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_source_resumes_user_active ON public.source_resumes(user_id, is_active) WHERE status = 'active';

-- ============================================
-- PART 3: ENABLE ROW LEVEL SECURITY
-- ============================================

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resume_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.generated_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.usage_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.allowed_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_resumes ENABLE ROW LEVEL SECURITY;

-- ============================================
-- PART 4: DROP ALL EXISTING POLICIES (CLEANUP)
-- ============================================

-- Drop all policies to avoid duplicates
DO $$
DECLARE
    policy_record RECORD;
BEGIN
    FOR policy_record IN 
        SELECT policyname, tablename 
        FROM pg_policies 
        WHERE schemaname = 'public'
          AND tablename IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings', 'allowed_users', 'source_resumes')
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I CASCADE', policy_record.policyname, policy_record.tablename);
    END LOOP;
END $$;

-- ============================================
-- PART 5: CREATE ROW LEVEL SECURITY POLICIES (CLEAN)
-- ============================================

-- User Profiles RLS (SELECT, INSERT, UPDATE only - no DELETE)
CREATE POLICY "user_profiles_select" ON public.user_profiles
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "user_profiles_insert" ON public.user_profiles
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "user_profiles_update" ON public.user_profiles
  FOR UPDATE USING (auth.uid() = user_id);

-- Resume Generations RLS (SELECT, INSERT, UPDATE only - no DELETE)
CREATE POLICY "resume_generations_select" ON public.resume_generations
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "resume_generations_insert" ON public.resume_generations
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "resume_generations_update" ON public.resume_generations
  FOR UPDATE USING (auth.uid() = user_id);

-- Generated Files RLS (SELECT, INSERT, DELETE)
CREATE POLICY "generated_files_select" ON public.generated_files
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "generated_files_insert" ON public.generated_files
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "generated_files_delete" ON public.generated_files
  FOR DELETE USING (auth.uid() = user_id);

-- Usage Events RLS (SELECT, INSERT only - no DELETE, UPDATE)
CREATE POLICY "usage_events_select" ON public.usage_events
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "usage_events_insert" ON public.usage_events
  FOR INSERT WITH CHECK (auth.uid() = user_id);

-- User Settings RLS (SELECT, INSERT, UPDATE only - no DELETE)
CREATE POLICY "user_settings_select" ON public.user_settings
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "user_settings_insert" ON public.user_settings
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "user_settings_update" ON public.user_settings
  FOR UPDATE USING (auth.uid() = user_id);

-- Allowed Users - No client access (backend-only via service role)
REVOKE ALL ON TABLE public.allowed_users FROM anon, authenticated;

-- Source Resumes RLS (SELECT, INSERT, UPDATE only - no DELETE)
CREATE POLICY "source_resumes_select" ON public.source_resumes
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "source_resumes_insert" ON public.source_resumes
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "source_resumes_update" ON public.source_resumes
  FOR UPDATE USING (auth.uid() = user_id);

-- ============================================
-- PART 6: VERIFICATION CHECKLIST
-- ============================================
-- Run the queries below to verify setup

-- Check 1: All required tables exist
SELECT 
  'required_tables_exist' as check_name,
  count(*) = 6 as expected,
  array_agg(table_name order by table_name) as checked_items
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings', 'allowed_users');

-- Check 2: User-owned tables have user_id column
SELECT 
  'user_owned_tables_have_user_id' as check_name,
  count(*) = 5 as expected,
  array_agg(table_name order by table_name) as checked_items
FROM information_schema.columns
WHERE table_schema = 'public'
  AND column_name = 'user_id'
  AND table_name IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings');

-- Check 3: RLS is enabled
SELECT 
  'rls_enabled' as check_name,
  bool_and(relrowsecurity) as expected,
  array_agg(relname order by relname) as checked_items
FROM pg_class
JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
WHERE nspname = 'public'
  AND relname IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings', 'allowed_users');

-- Check 4: Required indexes exist
SELECT 
  'required_indexes_exist' as check_name,
  count(*) = 12 as expected,
  array_agg(indexname order by indexname) as checked_items
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
    'idx_user_profiles_user_id',
    'idx_resume_generations_user_id',
    'idx_resume_generations_user_created',
    'idx_resume_generations_created_at',
    'idx_generated_files_user_id',
    'idx_generated_files_generation_id',
    'idx_generated_files_expires_at',
    'idx_usage_events_user_id',
    'idx_usage_events_generation_id',
    'idx_user_settings_user_id',
    'idx_allowed_users_email_lower_unique',
    'idx_allowed_users_email_active'
  );

-- Check 5: Correct number of RLS policies (should be exactly 14: no DELETE on user data)
SELECT 
  'rls_policies_present' as check_name,
  count(*) = 14 as expected,
  array_agg(tablename || ':' || policyname order by tablename, policyname) as checked_items
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings');

-- ============================================
-- DONE! All tables, indexes, RLS, and policies created.
-- The backend will auto-allow any email on first login.
-- ============================================
