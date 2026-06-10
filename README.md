# JustResume AI

Production-oriented resume generation app with Google OAuth, Supabase-backed profiles/history, Gemini generation, ATS scoring, and Supabase Storage exports.

## Architecture

- Frontend: Vite + React app in `frontend/`.
- Backend: FastAPI app in `backend/`.
- Auth: Google OAuth through Supabase Auth. The frontend sends Supabase bearer tokens, and the backend verifies JWTs and checks the allowlist.
- Data: one Supabase `user_profiles` row per user, permanent `resume_generations` history, and `generated_files` metadata.
- Files: generated PDF/DOCX files are uploaded to Supabase Storage and expire after `FILE_EXPIRY_DAYS` days, default `7`.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full flow.

## Prerequisites

Before running the project, ensure you have the following installed:

*   **Docker & Docker Compose**: For containerized development and deployment.
*   **Python 3.11+**: For backend development (if running without Docker).
*   **Node.js 20+ & npm**: For frontend development (if running without Docker).

## Running without Docker (Local Development)

This method is ideal for local development without containerization, offering faster iteration for code changes.

### Backend

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # On Windows
# source .venv/bin/activate    # On macOS/Linux
pip install -r requirements.txt
cp .env.example .env           # Configure your .env file
uvicorn app.main:app --reload
```
The backend will run on `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env           # Configure your .env file
npm run dev
```
The frontend development server will typically run on `http://localhost:5173`. Ensure `VITE_API_BASE` in your `frontend/.env` points to your backend (e.g., `http://localhost:8000/api/v1`).

## Running with Docker

### Development Mode

Use Docker Compose in development mode for an isolated environment with hot-reloading.

1.  **Create `.env` files**:
    *   Copy `.env.example` to `.env` in the project root.
    *   Copy `backend/.env.example` to `backend/.env`.
    *   Copy `frontend/.env.example` to `frontend/.env`.
2.  **Start the services**:
    ```bash
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
    ```
    This will build the images and start both backend (with hot-reloading and debug logs) and frontend (with its development server and hot-reloading).
3.  **Access the application**:
    *   Backend API: `http://localhost:8000/api/v1`
    *   Frontend: `http://localhost:3000` (The frontend development server runs on port 3000 inside the container and is mapped to 3000 on your host.)

### Production Mode

Use Docker Compose for a production-like environment.

1.  **Create `.env` file**: Copy `.env.example` to `.env` in the project root and configure it with production-ready values (e.g., `DEBUG=false`, `LOG_LEVEL=WARNING`, actual external URLs for `VITE_API_BASE` and `CORS_ORIGINS`).
2.  **Build and start the services**:
    ```bash
    docker compose up --build -d
    ```
    The `-d` flag runs the services in detached mode.
3.  **Access the application**:
    *   Backend API: `http://localhost:8000/api/v1`
    *   Frontend: `http://localhost:3000` (The frontend is served by Nginx on port 80 inside the container, mapped to 3000 on your host.)

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

`LATEX_TEMPLATE_DIR` must point to a directory. The single production resume template is `main.tex` inside that directory.

For final ATS validation, the optimized generation endpoint compiles the resume,
extracts text from the generated PDF with `pypdf`, counts pages, and scores the
extracted PDF text:

```text
POST /api/v1/pipeline/generate/optimized
```

Use this path when the API response must include PDF-text ATS diagnostics and
repair attempts. The existing `/api/v1/pipeline/generate` flow remains available.

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

## Security

### Secret Management
- **Never commit `.env` files** — only `.env.example` templates are tracked.
- All secrets are loaded via environment variables (pydantic-settings).
- The backend logs only confirm whether secrets are "configured" or "MISSING" — **never prints values**.
- Pre-commit hooks scan for secret patterns before each commit.

### Install Pre-commit Hooks
```bash
# Windows PowerShell
.\scripts\install-hooks.ps1

# macOS / Linux
cp .githooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

### Scanned Patterns
The pre-commit hook blocks:
- `.env` files (except `.env.example`)
- Google API keys (`AIzaSy...`)
- JWT tokens (`eyJ...`)
- OpenAI keys (`sk-...`)
- GitHub tokens (`ghp_...`)
- Slack tokens (`xox...`)
- Private keys (`-----BEGIN ... PRIVATE KEY-----`)
- Supabase publishable keys (`sb_publishable_...`)
- `__pycache__`, `.pyc`, `node_modules/`, `dist/`
- `.pem`, `.key`, `.p12`, `.pfx` files

### CI Security
GitHub Actions runs `npm audit` and `pip-audit` on every push/PR. See `.github/workflows/ci.yml`.

### Production Checklist
- [ ] Set `DEBUG=false` and `APP_ENV=production`
- [ ] Use explicit `CORS_ORIGINS` (no wildcards)
- [ ] Rotate all API keys before going live
- [ ] Verify `.env` files are in `.gitignore`
- [ ] Run `.\scripts\install-hooks.ps1` locally
- [ ] Set GitHub repository secrets for CI (not in repo)

## Testing & CI

### Run All Tests (One Command)

```bash
# macOS / Linux
bash scripts/check.sh

# Windows PowerShell
.\scripts\check.ps1
```

### Backend Tests

```bash
cd backend

# All tests
python -m pytest tests/ -v --tb=short

# Pipeline tests (long JD, short JD, fallback, PDF extraction, page count, ATS score)
python -m pytest tests/test_resume_generation_pipeline.py -v

# PDF text extraction tests (content verification)
python -m pytest tests/test_pdf_text_extraction.py -v

# Regression tests (old flows, scoring, repair, budget, quality gate)
python -m pytest tests/test_regression_old_flows.py -v

# Fallback integration tests
python -m pytest tests/test_fallback_integration.py -v

# Optimization loop tests
python -m pytest tests/test_resume_optimization_loop.py -v

# PDF page fit tests
python -m pytest tests/test_pdf_page_fit_service.py -v

# LaTeX render tests
python -m pytest tests/test_latex_render_service.py -v
```

### Frontend Tests

```bash
cd frontend

# All tests
npx vitest run

# Resume creation wizard UI tests
npx vitest run src/__tests__/ResumeCreationWizard.test.tsx

# Mobile responsive smoke tests
npx vitest run src/__tests__/MobileResponsive.test.tsx

# Account isolation tests
npx vitest run src/__tests__/AccountIsolation.test.tsx

# Watch mode
npx vitest
```

### Test Coverage

| Category | Tests | Coverage |
|---|---|---|
| Fallback Integration | 32 | Deterministic fallback path |
| Resume Generation Pipeline | 16 | Long JD, short JD, fallback, PDF, page count, ATS score, hard caps |
| PDF Text Extraction | 12 | Content verification, encoding, scoring |
| Regression Old Flows | 10 | Scoring, repair, budget, quality gate |
| Frontend Wizard UI | 14 | ProfileSelector, ATSRepairStatus, PdfParseStatus, FlowStepper |
| Frontend Mobile | 13 | MobileNav, responsive steppers, cards |
| Frontend Account Isolation | 8 | Store reset, cross-user data leak prevention |

### CI Pipeline

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
from app.services.pdf_compile_service import compile_pdf
from app.services.latex_render_service import render_latex
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
