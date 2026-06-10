-- ============================================
-- DIAGNOSTIC: Check what's missing
-- ============================================

-- Check 1: What tables exist?
SELECT 'TABLE CHECK' as check_type, table_name 
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings', 'allowed_users')
ORDER BY table_name;

-- Check 2: What columns exist in each table?
SELECT table_name, column_name 
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings', 'allowed_users')
ORDER BY table_name, column_name;

-- Check 3: What indexes exist?
SELECT indexname 
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings', 'allowed_users')
ORDER BY indexname;

-- Check 4: RLS status on each table
SELECT relname, relrowsecurity 
FROM pg_class
JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
WHERE nspname = 'public'
  AND relname IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings', 'allowed_users')
ORDER BY relname;

-- Check 5: What RLS policies exist?
SELECT tablename, policyname, cmd, permissive
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('user_profiles', 'resume_generations', 'generated_files', 'usage_events', 'user_settings', 'allowed_users')
ORDER BY tablename, policyname;
