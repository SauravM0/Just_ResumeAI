# JustResume AI

This repo is split into:

- `frontend/`: Vite + React client
- `backend/`: FastAPI API and LaTeX/PDF pipeline

## Required Backend Environment Variables

Create `backend/.env` from `backend/.env.example` and set the values before running the backend.

Required:

- `GEMINI_API_KEY`: Google Gemini API key used by the active AI endpoints

Common local defaults:

- `GEMINI_MODEL=gemini-2.5-flash`
- `DEBUG=true`
- `CORS_ORIGINS=["http://localhost:5173"]`
- Vercel production frontend: set `VITE_API_BASE=https://your-backend.onrender.com/api/v1`
- Render production backend: set `CORS_ORIGINS=https://your-frontend.vercel.app`

Notes:

- No real API keys or secrets should be committed to the repo.
- The active backend config falls back to an empty `GEMINI_API_KEY`, so runtime does not depend on a committed secret.
- PDF compilation also requires a local LaTeX toolchain such as `pdflatex`.


cd "/mnt/data/justresume/Just resume/backend"
python -m venv .venv
# activate venv
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

cd "/mnt/data/justresume/Just resume/frontend"
npm install
npm run dev

