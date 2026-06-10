import { createClient } from '@supabase/supabase-js';
import type { SupabaseClient } from '@supabase/supabase-js';
import { getRuntimeConfig } from './env';

export function requireSupabaseConfig(): { supabaseUrl: string; supabaseAnonKey: string } {
  const runtime = getRuntimeConfig();
  const supabaseUrl = runtime.VITE_SUPABASE_URL?.trim() || import.meta.env.VITE_SUPABASE_URL?.trim();
  const supabaseAnonKey = runtime.VITE_SUPABASE_ANON_KEY?.trim() || import.meta.env.VITE_SUPABASE_ANON_KEY?.trim();

  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error('VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are required.');
  }

  return { supabaseUrl, supabaseAnonKey };
}

let supabaseClient: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
  if (!supabaseClient) {
    const config = requireSupabaseConfig();
    supabaseClient = createClient(config.supabaseUrl, config.supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false,
        flowType: 'pkce',
      },
    });
  }
  return supabaseClient;
}
