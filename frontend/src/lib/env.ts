const DEFAULT_LOCAL_API_BASE = 'http://localhost:8000/api/v1';

type RuntimeConfig = Partial<Record<
  'VITE_API_BASE' | 'VITE_SUPABASE_URL' | 'VITE_SUPABASE_ANON_KEY' | 'VITE_APP_ENV' | 'VITE_APP_VERSION',
  string
>>;

declare global {
  interface Window {
    __JUSTRESUME_CONFIG__?: RuntimeConfig;
  }
}

export function getRuntimeConfig(): RuntimeConfig {
  return typeof window === 'undefined' ? {} : window.__JUSTRESUME_CONFIG__ ?? {};
}

function normalizeApiBase(value: string): string {
  return value.replace(/\/+$/, '');
}

export function getApiBase(): string {
  const runtime = getRuntimeConfig();
  const runtimeApiBase = runtime.VITE_API_BASE?.trim();
  const configured = runtimeApiBase || import.meta.env.VITE_API_BASE?.trim();

  if (configured) {
    const normalized = normalizeApiBase(configured);
    if (!runtimeApiBase && import.meta.env.PROD && normalized.includes('localhost')) {
      throw new Error(
        'VITE_API_BASE points to localhost in production. ' +
        'Set VITE_API_BASE to the deployed backend URL, e.g. https://your-backend.onrender.com/api/v1'
      );
    }
    return normalized;
  }

  if (import.meta.env.DEV) {
    console.warn(
      '[JustResume] VITE_API_BASE not set. Using default:',
      DEFAULT_LOCAL_API_BASE,
      'Set VITE_API_BASE in .env to suppress this warning.'
    );
    return DEFAULT_LOCAL_API_BASE;
  }

  throw new Error(
    'VITE_API_BASE is required in production. ' +
    'Set it to your deployed backend URL, e.g. https://your-backend.onrender.com/api/v1'
  );
}

export function toBackendUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const apiBase = getApiBase();
  const backendOrigin = new URL(apiBase).origin;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;

  return `${backendOrigin}${normalizedPath}`;
}
