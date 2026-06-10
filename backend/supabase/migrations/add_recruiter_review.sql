ALTER TABLE resume_generations ADD COLUMN IF NOT EXISTS recruiter_review_json JSONB;
ALTER TABLE resume_generations ADD COLUMN IF NOT EXISTS recruiter_impression DOUBLE PRECISION;
