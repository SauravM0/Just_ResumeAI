import { create } from 'zustand';
import type { Session, User } from '@supabase/supabase-js';
import { getSupabaseClient } from '../lib/supabase';

interface AuthState {
  session: Session | null;
  user: User | null;
  loading: boolean;
  error: string | null;
  initialized: boolean;
  initialize: () => Promise<void>;
  signInWithGoogle: (redirectPath?: string) => Promise<void>;
  getAccessToken: () => Promise<string | null>;
  signOut: () => Promise<void>;
  clearError: () => void;
}

let authListenerStarted = false;
let initializePromise: Promise<void> | null = null;

export const useAuthStore = create<AuthState>((set, get) => ({
  session: null,
  user: null,
  loading: true,
  error: null,
  initialized: false,

  initialize: async () => {
    if (authListenerStarted && get().initialized) return;
    if (initializePromise) return initializePromise;

    initializePromise = (async () => {
      set({ loading: true, error: null });
      try {
        const supabase = getSupabaseClient();
        const params = new URLSearchParams(window.location.search);
        const code = params.get('code');
        if (code) {
          const { error } = await supabase.auth.exchangeCodeForSession(code);
          if (error) throw error;
          window.history.replaceState({}, document.title, `${window.location.pathname}${window.location.hash}`);
        }

        const { data, error } = await supabase.auth.getSession();
        if (error) throw error;

        set({
          session: data.session,
          user: data.session?.user ?? null,
          loading: false,
          initialized: true,
        });

        if (!authListenerStarted) {
          authListenerStarted = true;
          supabase.auth.onAuthStateChange((_event, session) => {
            set({
              session,
              user: session?.user ?? null,
              loading: false,
              initialized: true,
              error: null,
            });
          });
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unable to initialize authentication.';
        const isConfigError = message.includes('VITE_SUPABASE_URL') || message.includes('VITE_SUPABASE_ANON_KEY');
        set({
          session: null,
          user: null,
          loading: false,
          initialized: true,
          error: isConfigError
            ? 'VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY must be set in your .env file. Copy frontend/.env.example to frontend/.env and fill in the values from your Supabase project.'
            : message,
        });
      } finally {
        initializePromise = null;
      }
    })();

    return initializePromise;
  },

  signInWithGoogle: async (redirectPath = '/dashboard') => {
    set({ loading: true, error: null });
    try {
      const supabase = getSupabaseClient();
      const normalizedPath = redirectPath.startsWith('/') ? redirectPath : '/dashboard';
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}${normalizedPath}`,
          queryParams: {
            access_type: 'offline',
            prompt: 'consent',
          },
        },
      });
      if (error) throw error;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Google sign-in failed.';
      const isConfigError = message.includes('VITE_SUPABASE_URL') || message.includes('VITE_SUPABASE_ANON_KEY');
      set({
        loading: false,
        error: isConfigError
          ? 'Supabase is not configured. Check your .env file for VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.'
          : message,
      });
    }
  },

  getAccessToken: async () => {
    const existingToken = get().session?.access_token;
    const expiresAt = get().session?.expires_at;
    const nowInSeconds = Math.floor(Date.now() / 1000);

    if (existingToken && expiresAt && expiresAt > nowInSeconds + 60) {
      return existingToken;
    }

    try {
      const supabase = getSupabaseClient();
      const { data, error } = await supabase.auth.getSession();
      if (error) throw error;

      if (data.session?.expires_at && data.session.expires_at > nowInSeconds + 60) {
        set({
          session: data.session,
          user: data.session?.user ?? null,
        });
        return data.session.access_token ?? null;
      }

      const { data: refreshData, error: refreshError } = await supabase.auth.refreshSession();
      if (refreshError) throw refreshError;

      set({
        session: refreshData.session,
        user: refreshData.session?.user ?? null,
      });
      return refreshData.session?.access_token ?? null;
    } catch {
      set({ session: null, user: null });
      return null;
    }
  },

  signOut: async () => {
    set({ loading: true, error: null });
    try {
      const supabase = getSupabaseClient();
      const { error } = await supabase.auth.signOut();
      if (error) throw error;
      set({ session: null, user: null, loading: false, initialized: true });
    } catch (error) {
      set({
        session: null,
        user: null,
        loading: false,
        error: error instanceof Error ? error.message : 'Sign out failed.',
        initialized: true,
      });
    }
  },

  clearError: () => set({ error: null }),
}));
