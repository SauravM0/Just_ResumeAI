-- JustResume Supabase verification checklist.
-- Run in the Supabase SQL editor after applying migrations.
-- Expected result: all checks return rows with expected=true.

with required_tables(table_name) as (
  values
    ('user_profiles'),
    ('resume_generations'),
    ('generated_files'),
    ('usage_events'),
    ('user_settings'),
    ('allowed_users')
)
select
  'required_tables_exist' as check_name,
  count(*) = 6 as expected,
  array_agg(required_tables.table_name order by required_tables.table_name) as checked_items
from required_tables
join information_schema.tables t
  on t.table_schema = 'public'
 and t.table_name = required_tables.table_name;

with user_owned(table_name) as (
  values
    ('user_profiles'),
    ('resume_generations'),
    ('generated_files'),
    ('usage_events'),
    ('user_settings')
)
select
  'user_owned_tables_have_user_id' as check_name,
  count(*) = 5 as expected,
  array_agg(user_owned.table_name order by user_owned.table_name) as checked_items
from user_owned
join information_schema.columns c
  on c.table_schema = 'public'
 and c.table_name = user_owned.table_name
 and c.column_name = 'user_id';

select
  'rls_enabled' as check_name,
  bool_and(relrowsecurity) as expected,
  array_agg(relname order by relname) as checked_items
from pg_class
join pg_namespace on pg_namespace.oid = pg_class.relnamespace
where nspname = 'public'
  and relname in (
    'user_profiles',
    'resume_generations',
    'generated_files',
    'usage_events',
    'user_settings',
    'allowed_users'
  );

select
  'user_owned_rls_policies_present' as check_name,
  count(*) >= 17 as expected,
  array_agg(tablename || ':' || policyname order by tablename, policyname) as checked_items
from pg_policies
where schemaname = 'public'
  and tablename in (
    'user_profiles',
    'resume_generations',
    'generated_files',
    'usage_events',
    'user_settings'
  )
  and (
    qual ilike '%user_id = auth.uid()%'
    or with_check ilike '%user_id = auth.uid()%'
  );

select
  'generated_files_storage_path_policy_scoped' as check_name,
  count(*) >= 2 as expected,
  array_agg(policyname order by policyname) as checked_items
from pg_policies
where schemaname = 'public'
  and tablename = 'generated_files'
  and with_check ilike '%storage_path%'
  and with_check ilike '%users/%'
  and with_check ilike '%generation_id%';

select
  'resume_generations_profile_policy_scoped' as check_name,
  count(*) >= 2 as expected,
  array_agg(policyname order by policyname) as checked_items
from pg_policies
where schemaname = 'public'
  and tablename = 'resume_generations'
  and with_check ilike '%user_profiles%'
  and with_check ilike '%profile_id%';

select
  'allowed_users_has_no_client_policies' as check_name,
  count(*) = 0 as expected,
  coalesce(array_agg(policyname order by policyname), array[]::text[]) as checked_items
from pg_policies
where schemaname = 'public'
  and tablename = 'allowed_users';

with required_indexes(index_name) as (
  values
    ('idx_user_profiles_user_id'),
    ('idx_resume_generations_user_id'),
    ('idx_resume_generations_user_created'),
    ('idx_resume_generations_created_at'),
    ('idx_generated_files_user_id'),
    ('idx_generated_files_generation_id'),
    ('idx_generated_files_expires_at'),
    ('idx_usage_events_user_id'),
    ('idx_usage_events_generation_id'),
    ('idx_user_settings_user_id'),
    ('idx_allowed_users_email_lower_unique'),
    ('idx_allowed_users_email_active')
)
select
  'required_indexes_exist' as check_name,
  count(*) = 12 as expected,
  array_agg(required_indexes.index_name order by required_indexes.index_name) as checked_items
from required_indexes
join pg_indexes
  on pg_indexes.schemaname = 'public'
 and pg_indexes.indexname = required_indexes.index_name;
