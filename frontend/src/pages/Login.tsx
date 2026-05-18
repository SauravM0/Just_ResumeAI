import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../store/useAuthStore';
import { getAppConfig } from '../lib/appConfig';

function isSupabaseConfigError(error: string | null): boolean {
  if (!error) return false;
  return error.includes('VITE_SUPABASE_URL') || error.includes('VITE_SUPABASE_ANON_KEY');
}

export default function Login() {
  const location = useLocation();
  const { session, loading, error, signInWithGoogle, clearError } = useAuthStore();
  const fromPath = (location.state as { from?: { pathname?: string; search?: string } } | null)?.from;
  const redirectPath = fromPath?.pathname ? `${fromPath.pathname}${fromPath.search ?? ''}` : '/dashboard';
  const isConfigError = isSupabaseConfigError(error);
  const config = getAppConfig();

  if (session) {
    return <Navigate to={redirectPath} replace />;
  }

  const handleGoogleLogin = () => {
    clearError();
    void signInWithGoogle(redirectPath);
  };

  if (isConfigError) {
    return (
      <main className="login-page">
        <section className="login-panel">
          <div className="login-brand">
            <div className="logo-icon login-logo">JR</div>
            <div>
              <h1>JustResume AI</h1>
              <p>Create tailored ATS-friendly resumes from your master profile.</p>
            </div>
          </div>

          <div className="login-card">
            <div className="login-copy">
              <span className="badge badge-danger">Configuration Required</span>
              <h2>Supabase not configured</h2>
              <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                This application requires Supabase credentials to run. Set the following
                environment variables in your <code>frontend/.env</code> file:
              </p>
              <div
                style={{
                  marginTop: 'var(--space-lg)',
                  padding: 'var(--space-md)',
                  background: 'var(--bg-code, #f5f5f5)',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.8rem',
                  lineHeight: 1.8,
                  textAlign: 'left',
                }}
              >
                <div>VITE_SUPABASE_URL=https://your-project.supabase.co</div>
                <div>VITE_SUPABASE_ANON_KEY=your-anon-key</div>
                <div>VITE_API_BASE=http://localhost:8000/api/v1</div>
              </div>
              <p style={{ marginTop: 'var(--space-md)', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                Copy <code>frontend/.env.example</code> to <code>frontend/.env</code> and fill in the values
                from your Supabase project dashboard.
              </p>
              {config.isDevelopment && (
                <p style={{ fontSize: '0.8rem', color: 'var(--text-tertiary, #999)' }}>
                  API Base: {config.apiBase}
                </p>
              )}
            </div>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="login-brand">
          <div className="logo-icon login-logo">JR</div>
          <div>
            <h1>JustResume AI</h1>
            <p>Create tailored ATS-friendly resumes from your master profile.</p>
          </div>
        </div>

        <div className="login-card">
          <div className="login-copy">
            <span className="badge badge-info">Secure workspace</span>
            <h2>Sign in to continue</h2>
            <p>Your profile and resume history stay attached to your account.</p>
          </div>

          {error && (
            <div className="warning-banner warning-error login-error">
              <span>{error}</span>
            </div>
          )}

          <button
            type="button"
            className="btn btn-primary btn-lg google-login-button"
            onClick={handleGoogleLogin}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="spinner" />
                Connecting...
              </>
            ) : (
              <>
                <span className="google-mark">G</span>
                Continue with Google
              </>
            )}
          </button>
        </div>
      </section>
    </main>
  );
}
