import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../store/useAuthStore';

export function AuthLoadingScreen() {
  return (
    <div className="auth-loading-screen">
      <div className="auth-loading-card">
        <div className="logo-icon auth-loading-logo">JR</div>
        <div className="spinner spinner-lg" />
        <div>
          <h1>JustResume AI</h1>
          <p>Preparing your workspace...</p>
        </div>
      </div>
    </div>
  );
}

interface ProtectedRouteProps {
  children: ReactNode;
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const location = useLocation();
  const { session, loading, initialized, error } = useAuthStore();

  if (loading || !initialized) {
    return <AuthLoadingScreen />;
  }

  if (!session) {
    if (error) {
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
                <h2>Authentication unavailable</h2>
                <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                  {error}
                </p>
              </div>
            </div>
          </section>
        </main>
      );
    }
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
}
