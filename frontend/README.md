# JustResume AI Frontend

Vite + React client for JustResume AI.

## Local Setup

```bash
cp .env.example .env
npm install
npm run dev
```

Local default:

```env
VITE_API_BASE=http://localhost:8000/api/v1
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_anon_key
```

Production builds must set `VITE_API_BASE`; the app only falls back to localhost during Vite dev.

## Google OAuth

The app uses Supabase Auth with Google OAuth. In Supabase, enable Google under Authentication Providers and add these redirect URLs:

```text
http://localhost:5173/dashboard
https://your-frontend-domain/dashboard
```

Only use the Supabase anon key in frontend env files. Never expose the service role key to Vite.

## Safety Notes

- Do not commit `frontend/.env`.
- Do not commit `node_modules/`, `dist/`, or `coverage/`.
- Backend API requests include the Supabase access token as `Authorization: Bearer <access_token>`.

## Commands

```bash
npm run build
npm run lint
npm run preview
```

