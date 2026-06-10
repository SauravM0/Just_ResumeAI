# JustResume AI — Docker Run Guide

This project is designed to run locally with Docker. You do not need to install Python or Node.js on your host machine.

The default local Docker setup is lightweight and does not install LaTeX. That keeps local builds fast and small. PDF export that requires `pdflatex` is reserved for the full backend Docker image in `backend/Dockerfile`, which we can use when preparing production hosting.

## Quick Start (Independent Run)

1. **Clone the repository** (if you haven't already).
2. **Setup your environment variables**:
   Copy the example environment file to `.env`:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and fill in your **GEMINI_API_KEY** and **SUPABASE** keys.

3. **Start the application on Windows PowerShell**:
   ```powershell
   .\scripts\dev.ps1
   ```
   This starts the backend and frontend, prints the URLs, then streams backend logs.
   Press `Ctrl+C` to stop watching logs; the containers keep running.

   Use `.\scripts\dev.ps1 -Build` when you intentionally need a rebuild.
   Use `.\scripts\dev.ps1 -NoLogs` when you only want to start the app and print URLs.
   Use `.\scripts\dev.ps1 -VerboseLogs` when you want backend request/activity logs while testing user actions.
   Use `.\scripts\dev.ps1 -Stop` to stop the app.

5. **Access the app**:
   - **Frontend**: [http://localhost:3099](http://localhost:3099)
   - **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Backend Health**: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

   To use a different frontend port, set `FRONTEND_PORT` before starting Docker
   (for example, `FRONTEND_PORT=3000 docker compose up -d` on macOS/Linux or
   `$env:FRONTEND_PORT=3000; docker compose up -d` in PowerShell).

   Do not run `docker compose up --build` every time. It rebuilds the backend image,
   downloads/install packages when cache is cold, and prints large build logs. Use
   `.\scripts\dev.ps1` for normal startup, and rebuild only after dependency or
   Dockerfile changes.

   If you run Compose manually, the build flag has two hyphens:
   ```powershell
   docker compose up --build
   ```
   `docker compose up -build` is invalid and fails with `unknown shorthand flag: 'b'`.

## Google Auth Callback

For local Google sign-in, add this redirect URL in Supabase:

```text
Authentication -> URL Configuration -> Redirect URLs
http://localhost:3099/auth/callback
```

For production, add your hosted frontend callback too:

```text
https://your-frontend-domain.com/auth/callback
```

## Key Container Features

- **Backend (local)**: Lightweight Python API image without LaTeX.
- **Backend (full/prod-ready)**: `backend/Dockerfile` keeps the heavier pdflatex-capable image for future hosting/PDF work.
- **Frontend**: Uses an Nginx alpine server with runtime environment injection.
- **Volumes**: Generated PDFs are persisted in the `backend_output` Docker volume.
- **Healthchecks**: The frontend container waits for the backend to be healthy before starting.

## Environment Variables for Docker

| Variable | Description | Default |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Your Google Gemini API Key | (Required) |
| `SUPABASE_URL` | Your Supabase Project URL | (Required) |
| `VITE_API_BASE` | Backend URL (Browser-accessible) | `http://localhost:8000/api/v1` |
| `FRONTEND_PORT` | Host port for the frontend container | `3099` |

## Maintenance

- **View Backend Logs**: `.\scripts\dev.ps1`
- **View Backend Request/Activity Logs**: `.\scripts\dev.ps1 -VerboseLogs`
- **View Frontend Logs**: `.\scripts\dev.ps1 -Logs frontend`
- **View All Logs**: `.\scripts\dev.ps1 -Logs all`
- **Start Without Logs**: `.\scripts\dev.ps1 -NoLogs`
- **Stop App**: `.\scripts\dev.ps1 -Stop`
- **Clear Data**: `docker compose down -v` (removes generated PDFs)
- **Clear Build Cache**: `.\scripts\dev.ps1 -Clean` (frees cache, but the next rebuild is slower)
