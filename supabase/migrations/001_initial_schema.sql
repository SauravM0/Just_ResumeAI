-- JustResume AI initial Supabase schema.
-- Apply with: supabase db push

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function public.normalize_allowed_user_email()
returns trigger
language plpgsql
as $$
begin
  new.email = lower(trim(new.email));
  return new;
end;
$$;

create table if not exists public.user_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  profile_json jsonb not null default '{}'::jsonb,
  profile_completion_score int default 0 check (
    profile_completion_score >= 0 and profile_completion_score <= 100
  ),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(user_id),
  unique(id, user_id)
);

create table if not exists public.resume_generations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  profile_id uuid references public.user_profiles(id) on delete set null,
  job_title text,
  company text,
  raw_jd_text text not null,
  parsed_jd_json jsonb,
  resume_json jsonb,
  ats_score_json jsonb,
  alignment_report_json jsonb,
  ats_pre_check_json jsonb,
  cover_letter_text text,
  latex_source text,
  status text default 'draft' check (status in ('draft', 'completed', 'failed', 'archived')),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(id, user_id)
);

create table if not exists public.generated_files (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  generation_id uuid not null,
  file_type text not null check (file_type in ('pdf', 'docx', 'tex', 'other')),
  storage_path text not null unique,
  expires_at timestamptz not null,
  deleted_at timestamptz,
  created_at timestamptz default now(),
  foreign key (generation_id, user_id)
    references public.resume_generations(id, user_id)
    on delete cascade
);

create table if not exists public.usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  event_type text not null,
  generation_id uuid,
  metadata_json jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  foreign key (generation_id, user_id)
    references public.resume_generations(id, user_id)
    on delete cascade
);

create table if not exists public.user_settings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  target_resume_pages int default 1 check (target_resume_pages >= 1 and target_resume_pages <= 2),
  preferred_tone text default 'professional',
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique(user_id)
);

create table if not exists public.allowed_users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  is_active boolean default true,
  created_at timestamptz default now()
);

create index if not exists idx_resume_generations_user_created
  on public.resume_generations(user_id, created_at desc);
create index if not exists idx_user_profiles_user_id
  on public.user_profiles(user_id);
create index if not exists idx_resume_generations_user_id
  on public.resume_generations(user_id);
create index if not exists idx_resume_generations_created_at
  on public.resume_generations(created_at desc);
create index if not exists idx_resume_generations_profile_id
  on public.resume_generations(profile_id);
create index if not exists idx_generated_files_user_generation
  on public.generated_files(user_id, generation_id);
create index if not exists idx_generated_files_user_id
  on public.generated_files(user_id);
create index if not exists idx_generated_files_generation_id
  on public.generated_files(generation_id);
create index if not exists idx_generated_files_expires_at
  on public.generated_files(expires_at)
  where deleted_at is null;
create index if not exists idx_usage_events_user_created
  on public.usage_events(user_id, created_at desc);
create index if not exists idx_usage_events_user_id
  on public.usage_events(user_id);
create index if not exists idx_usage_events_generation_id
  on public.usage_events(generation_id);
create index if not exists idx_user_settings_user_id
  on public.user_settings(user_id);
create unique index if not exists idx_allowed_users_email_lower_unique
  on public.allowed_users(lower(email));
create index if not exists idx_allowed_users_email_active
  on public.allowed_users(lower(email))
  where is_active is true;

drop trigger if exists set_user_profiles_updated_at on public.user_profiles;
create trigger set_user_profiles_updated_at
before update on public.user_profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_resume_generations_updated_at on public.resume_generations;
create trigger set_resume_generations_updated_at
before update on public.resume_generations
for each row execute function public.set_updated_at();

drop trigger if exists set_user_settings_updated_at on public.user_settings;
create trigger set_user_settings_updated_at
before update on public.user_settings
for each row execute function public.set_updated_at();

drop trigger if exists normalize_allowed_user_email on public.allowed_users;
create trigger normalize_allowed_user_email
before insert or update on public.allowed_users
for each row execute function public.normalize_allowed_user_email();

alter table public.user_profiles enable row level security;
alter table public.resume_generations enable row level security;
alter table public.generated_files enable row level security;
alter table public.usage_events enable row level security;
alter table public.user_settings enable row level security;
alter table public.allowed_users enable row level security;

drop policy if exists "Users can read own profile" on public.user_profiles;
create policy "Users can read own profile"
on public.user_profiles for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can insert own profile" on public.user_profiles;
create policy "Users can insert own profile"
on public.user_profiles for insert
to authenticated
with check (user_id = auth.uid());

drop policy if exists "Users can update own profile" on public.user_profiles;
create policy "Users can update own profile"
on public.user_profiles for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

drop policy if exists "Users can delete own profile" on public.user_profiles;
create policy "Users can delete own profile"
on public.user_profiles for delete
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can read own generations" on public.resume_generations;
create policy "Users can read own generations"
on public.resume_generations for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can insert own generations" on public.resume_generations;
create policy "Users can insert own generations"
on public.resume_generations for insert
to authenticated
with check (
  user_id = auth.uid()
  and (
    profile_id is null
    or exists (
      select 1
      from public.user_profiles p
      where p.id = profile_id
        and p.user_id = auth.uid()
    )
  )
);

drop policy if exists "Users can update own generations" on public.resume_generations;
create policy "Users can update own generations"
on public.resume_generations for update
to authenticated
using (user_id = auth.uid())
with check (
  user_id = auth.uid()
  and (
    profile_id is null
    or exists (
      select 1
      from public.user_profiles p
      where p.id = profile_id
        and p.user_id = auth.uid()
    )
  )
);

drop policy if exists "Users can delete own generations" on public.resume_generations;
create policy "Users can delete own generations"
on public.resume_generations for delete
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can read own generated files" on public.generated_files;
create policy "Users can read own generated files"
on public.generated_files for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can insert own generated files" on public.generated_files;
create policy "Users can insert own generated files"
on public.generated_files for insert
to authenticated
with check (
  user_id = auth.uid()
  and storage_path = (
    'users/' || auth.uid()::text || '/generations/' || generation_id::text ||
    case file_type
      when 'pdf' then '/resume.pdf'
      when 'docx' then '/resume.docx'
      when 'tex' then '/resume.tex'
      else '/resume.' || file_type
    end
  )
);

drop policy if exists "Users can update own generated files" on public.generated_files;
create policy "Users can update own generated files"
on public.generated_files for update
to authenticated
using (user_id = auth.uid())
with check (
  user_id = auth.uid()
  and storage_path = (
    'users/' || auth.uid()::text || '/generations/' || generation_id::text ||
    case file_type
      when 'pdf' then '/resume.pdf'
      when 'docx' then '/resume.docx'
      when 'tex' then '/resume.tex'
      else '/resume.' || file_type
    end
  )
);

drop policy if exists "Users can delete own generated files" on public.generated_files;
create policy "Users can delete own generated files"
on public.generated_files for delete
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can read own usage events" on public.usage_events;
create policy "Users can read own usage events"
on public.usage_events for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can insert own usage events" on public.usage_events;
create policy "Users can insert own usage events"
on public.usage_events for insert
to authenticated
with check (user_id = auth.uid());

drop policy if exists "Users can read own settings" on public.user_settings;
create policy "Users can read own settings"
on public.user_settings for select
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can insert own settings" on public.user_settings;
create policy "Users can insert own settings"
on public.user_settings for insert
to authenticated
with check (user_id = auth.uid());

drop policy if exists "Users can update own settings" on public.user_settings;
create policy "Users can update own settings"
on public.user_settings for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

drop policy if exists "Users can delete own settings" on public.user_settings;
create policy "Users can delete own settings"
on public.user_settings for delete
to authenticated
using (user_id = auth.uid());

-- Intentionally no client policies for allowed_users.
-- Access is reserved for trusted backend service-role logic.
revoke all on table public.allowed_users from anon, authenticated;
