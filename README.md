# JustResume AI

JustResume AI is a two-part application for tailoring resumes to a job description.

- `frontend/`: React + Vite UI for profile editing, JD analysis, resume review, LaTeX editing, and cover letter generation
- `backend/`: FastAPI API for JD parsing, resume recommendation, ATS validation, LaTeX rendering, and PDF compilation

## Features

- Analyze a raw job description and store the result in a session
- Generate a targeted resume recommendation from a master profile
- Regenerate the recommendation with locked bullets and rejected items
- Validate ATS score and keyword coverage
- Render the final resume to LaTeX
- Compile LaTeX into PDF
- Generate a cover letter from the selected resume and JD

## Project Structure

```text
.
├── backend/
│   ├── app/
│   ├── templates/
│   ├── tests/
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
└── docker-compose.yml
```

## Prerequisites

### Docker path

If you want the simplest full-stack setup, use Docker Compose:

- Docker Desktop with WSL integration enabled if you are on Windows + WSL
- `docker compose`

### Local path

If you want to run without Docker:

- Python 3.11+ for the backend
- Node.js 20+ and npm for the frontend
- A LaTeX distribution with `pdflatex` if you want PDF generation locally
- A Gemini API key if you want AI-backed JD/resume/cover-letter generation

## Environment Setup

Create the backend env file from the safe example:

```bash
cd backend
cp .env.example .env
```

Set at least:

```env
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.5-flash
DEBUG=true
CORS_ORIGINS=["http://localhost:5173"]
```

Notes:

- Never commit or share `backend/.env`. It is ignored by git and should contain only local secrets.
- `backend/.env.example` must stay in the repo as the safe template.
- The backend will start even if `GEMINI_API_KEY` is empty, but AI-backed flows will fail or fall back depending on the endpoint.
- The frontend uses `VITE_API_BASE`, which defaults to `http://localhost:8000/api/v1`.

## Run With Docker Compose

From the repo root:

```bash
docker compose up --build
```

Services:

- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Health check: `http://localhost:8000/api/v1/health`

If `docker` is not available inside WSL, enable Docker Desktop WSL integration first.

## Run Locally

This is the path that was validated in this workspace.

### 1. Start the backend

From `backend/`:

```bash
python3 -m pip install --user --break-system-packages -r requirements.txt pytest
python3 -m app.main
```

Backend URLs:

- API base: `http://127.0.0.1:8000/api/v1`
- Health check: `http://127.0.0.1:8000/api/v1/health`

Important:

- Use `python3 -m app.main`
- Do not use `python3 app/main.py` locally, because that form does not set up the package import path correctly

### 2. Start the frontend

From `frontend/`:

```bash
npm install
npm run dev -- --host 127.0.0.1
```

Frontend URL:

- `http://127.0.0.1:5173`

### Windows + WSL note

In this environment, `npm` was available but `node` was not exposed directly in the WSL shell. If that happens on your machine, start the frontend through Windows:

```bash
cmd.exe /c npm install
cmd.exe /c npm run dev -- --host 127.0.0.1
```

The frontend launch above was verified from Windows-side HTTP checks in this workspace.

## Verified Commands

The following checks were run successfully here:

```bash
cd backend
python3 -m pytest -q
```

Result:

- `12 passed`

Backend health was also verified successfully:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Expected response:

```json
{"status":"healthy","service":"justresume-api"}
```

Frontend production build was verified successfully:

```bash
cd frontend
npm run build
```

## Deploy To Render And Vercel

This repo includes `render.yaml` for the backend and `frontend/vercel.json` for the Vite frontend.

### Backend on Render

Create a Render Web Service from this repo. The included `render.yaml` uses the backend Dockerfile so the LaTeX packages needed for PDF generation are installed.

Set these Render environment variables:

```env
DEBUG=false
GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.5-flash
GEMINI_REVIEW_MODEL=gemini-2.5-pro
CORS_ORIGINS=https://your-frontend.vercel.app
LATEX_OUTPUT_DIR=/app/output
SESSION_DB_PATH=/app/output/sessions.sqlite3
```

After Render deploys, your API base will be:

```text
https://your-backend.onrender.com/api/v1
```

### Frontend on Vercel

Import the repo in Vercel and set the project root directory to `frontend`.

Set this Vercel environment variable:

```env
VITE_API_BASE=https://your-backend.onrender.com/api/v1
```

After Vercel deploys, copy the final Vercel URL back into Render's `CORS_ORIGINS`.
For multiple allowed frontend URLs, use a comma-separated value:

```env
CORS_ORIGINS=https://your-frontend.vercel.app,https://your-custom-domain.com
```

## Available Frontend Pages

- Dashboard
- Master Profile
- Job Description
- Resume Review
- LaTeX Editor
- Cover Letter

## Main API Endpoints

- `POST /api/v1/jd/analyze`
- `POST /api/v1/resume/recommend`
- `POST /api/v1/resume/regenerate`
- `POST /api/v1/resume/validate`
- `POST /api/v1/resume/render-latex`
- `POST /api/v1/resume/render-pdf`
- `GET /api/v1/resume/download/{filename}`
- `POST /api/v1/cover-letter/generate`
- `GET /api/v1/health`

## Troubleshooting

### `docker: command not found` in WSL

Enable Docker Desktop WSL integration for this distro, then rerun:

```bash
docker compose up --build
```

### `ModuleNotFoundError: No module named 'app'`

Start the backend as a module:

```bash
cd backend
python3 -m app.main
```

### `node: command not found` but `npm` works

Use Windows npm from WSL:

```bash
cd frontend
cmd.exe /c npm install
cmd.exe /c npm run dev -- --host 127.0.0.1
```

### PDF generation fails

Local PDF generation depends on LaTeX tooling. Install a distribution that provides `pdflatex`, or use Docker Compose where the backend image installs the required TeX packages.

## Development Notes

- Backend sessions are persisted with SQLite under the backend output directory
- Rendered files are written under `backend/output/`
- The frontend stores the master profile client-side and uses the backend session ID for server-side flow state

## Create a Clean Shareable Zip

Before sharing the project, remove local secrets, generated files, dependency folders, build output, and caches. From the repo root on PowerShell:

```powershell
.\scripts\create-clean-zip.ps1
```

The script creates `JustResume-clean.zip` and excludes these paths:

- `.git/`
- `.env` and `.env.*` files, except safe `.env.example` templates
- `backend/.env`
- `backend/output/`
- `backend/*.sqlite3`
- `backend/**/__pycache__/`
- `backend/**/*.pyc`
- `backend/.pytest_cache/`
- `.pytest_cache/`
- `frontend/node_modules/`
- `frontend/dist/`
- `.DS_Store`
- `*.log`

If you are creating the zip manually, start from a clean working copy and confirm `backend/.env.example` is present while `backend/.env` is absent.
