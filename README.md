# JustResume AI

Production-oriented resume generation app with Google OAuth, Supabase-backed profiles/history, Gemini generation, ATS scoring, and Supabase Storage exports.

## Architecture

- Frontend: Vite + React app in `frontend/`.
- Backend: FastAPI app in `backend/`.
- Auth: Google OAuth through Supabase Auth. The frontend sends Supabase bearer tokens, and the backend verifies JWTs and checks the allowlist.
- Data: one Supabase `user_profiles` row per user, permanent `resume_generations` history, and `generated_files` metadata.
- Files: generated PDF/DOCX files are uploaded to Supabase Storage and expire after `FILE_EXPIRY_DAYS` days, default `7`.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full flow.

## Local Setup

Backend:

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Docker Compose (backend only):

```bash
docker compose up --build
```

The frontend is not included in Docker Compose. Run it locally with `cd frontend && npm run dev`.
For local development, the frontend connects to the backend at `http://localhost:8000/api/v1`.

## Supabase Setup

1. Create a Supabase project.
2. Run `supabase/migrations/001_initial_schema.sql`.
3. Create a private Storage bucket named `generated-resumes`, or set `SUPABASE_STORAGE_BUCKET` to your bucket name.
4. Add allowed users to the `allowed_users` table.
5. Copy the project URL, anon key, service role key, and JWT secret into backend/frontend env vars.

The schema enforces one master profile per user with a unique `user_profiles.user_id`.

## Google OAuth Setup

1. In Google Cloud Console, create OAuth credentials for a web app.
2. Add Supabase Auth callback URL from Supabase: `https://<project-ref>.supabase.co/auth/v1/callback`.
3. In Supabase Auth Providers, enable Google and paste the Google client ID/secret.
4. In Supabase Auth URL configuration, add local and deployed frontend URLs, for example `http://localhost:5173` and your Vercel domain.

## Environment Variables

Backend required in production:

```env
APP_ENV=production
DEBUG=false
CORS_ORIGINS=https://your-frontend.example
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
GEMINI_REVIEW_MODEL=gemini-2.5-pro
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_JWT_SECRET=...
SUPABASE_SERVICE_ROLE_KEY=...
SUPABASE_STORAGE_BUCKET=generated-resumes
FILE_EXPIRY_DAYS=7
LATEX_OUTPUT_DIR=/app/output
LATEX_TEMPLATE_DIR=/app/templates/latex
```

Frontend required:

```env
VITE_API_BASE=https://your-backend.example/api/v1
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=...
```

Production startup fails if required backend secrets are missing or wildcard CORS origins are configured.

## Deployment

- Backend: deploy with `Dockerfile`, `render.yaml`, or `railway.toml`.
- Frontend: deploy `frontend/` to Vercel or any static host.
- Set backend `CORS_ORIGINS` to the exact frontend origin.
- Set frontend `VITE_API_BASE` to the deployed backend `/api/v1`.
- Configure Supabase Auth redirect URLs for the deployed frontend.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for detailed guides.

## Testing & CI

### Local CI check

Run the same checks CI runs before pushing:

```bash
# macOS / Linux
bash scripts/check.sh

# Windows PowerShell
.\scripts\check.ps1
```

### Individual checks

```bash
cd frontend
npm run build

cd ../backend
python -m compileall app
python -m pytest
```

### CI pipeline

The repository uses GitHub Actions (`.github/workflows/ci.yml`) with these jobs:
1. **Hygiene** — fails if `.env`, `__pycache__`, `*.pyc`, `backend/output/`, `node_modules/`, or `dist/` files are tracked
2. **Backend** — `pip install` → `compileall` → `ruff` → `pytest` → import check
3. **Frontend** — `npm ci` → `tsc` → `lint` → `vitest` → `build`
4. **Security** — `npm audit` (critical-level) and `pip-audit` (warnings only)

### Clean export validation

Verify export services have no syntax errors:

```bash
cd backend
python -c "
from app.services.docx_export_service import export_resume_docx
from app.services.pdf_compile_service import compile_latex_to_pdf
from app.services.latex_render_service import render_resume_latex
print('Export services import OK')
"

# Generated files live in backend/output/ — never committed
rm -rf backend/output/*
```

See [docs/PR_CHECKLIST.md](docs/PR_CHECKLIST.md) for the full pre-merge checklist.

## Production Checklist

- Google OAuth is the only login path.
- Backend verifies Supabase JWTs and enforces `allowed_users`.
- No client-supplied identity headers are trusted.
- One master profile per user is stored in Supabase.
- Resume generation history is stored permanently in Supabase.
- Generated files use Supabase Storage and expire after 7 days.
- CORS origins are explicit, never wildcard in production.
- `.env`, generated files, caches, `node_modules`, build output, and local exports are ignored.
- Visual editor is the user editing surface; raw LaTeX editing is not shipped.
