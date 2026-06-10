import { getApiBase, getRuntimeConfig } from './env';

const APP_VERSION = import.meta.env.VITE_APP_VERSION || '0.1.0';
const APP_ENV = import.meta.env.VITE_APP_ENV || import.meta.env.MODE || 'development';
const APP_NAME = import.meta.env.VITE_APP_NAME || 'JustResume AI';
const BUILD_TIME = import.meta.env.VITE_BUILD_TIME || null;
const COMMIT_SHA = import.meta.env.VITE_COMMIT_SHA || null;

export interface AppConfig {
  appName: string;
  appVersion: string;
  appEnv: string;
  buildTime: string | null;
  commitSha: string | null;
  apiBase: string;
  isDevelopment: boolean;
  isProduction: boolean;
  supabaseConfigured: boolean;
}

let cachedConfig: AppConfig | null = null;

export function getAppConfig(): AppConfig {
  if (cachedConfig) return cachedConfig;

  const runtime = getRuntimeConfig();
  const apiBase = getApiBase();
  const appEnv = runtime.VITE_APP_ENV || APP_ENV;
  const isProduction = appEnv === 'production' || import.meta.env.PROD;

  cachedConfig = {
    appName: APP_NAME,
    appVersion: runtime.VITE_APP_VERSION || APP_VERSION,
    appEnv,
    buildTime: BUILD_TIME,
    commitSha: COMMIT_SHA,
    apiBase,
    isDevelopment: !isProduction,
    isProduction,
    supabaseConfigured: Boolean(
      (runtime.VITE_SUPABASE_URL || import.meta.env.VITE_SUPABASE_URL) &&
      (runtime.VITE_SUPABASE_ANON_KEY || import.meta.env.VITE_SUPABASE_ANON_KEY)
    ),
  };

  return cachedConfig;
}

export function formatEnvironmentLabel(): string {
  const config = getAppConfig();
  const env = config.appEnv === 'production' ? 'Production' : config.appEnv === 'staging' ? 'Staging' : 'Development';
  return `${config.appName} v${config.appVersion} — ${env}`;
}

