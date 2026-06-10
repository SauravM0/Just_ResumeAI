import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { ErrorBoundary } from './components/ErrorBoundary';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import MasterProfile from './pages/MasterProfile';
import FastResumeBuilder from './pages/FastResumeBuilder';
import ResumeCreationWizard from './pages/ResumeCreationWizard';
import ResumeReview from './pages/ResumeReview';
import History from './pages/History';
import HistoryDetail from './pages/HistoryDetail';
import CoverLetter from './pages/CoverLetter';
import Settings from './pages/Settings';
import AccessDenied from './pages/AccessDenied';
import ProtectedRoute from './components/ProtectedRoute';
import AppShell from './components/layout/AppShell';
import { useAuthStore } from './store/useAuthStore';

function ProtectedLayout({ children, title }: { children: React.ReactNode; title?: string }) {
  const location = useLocation();

  // Update document title on mount/change
  useEffect(() => {
    const baseTitle = 'Just Resume';
    document.title = title ? `${title} | ${baseTitle}` : baseTitle;
  }, [title]);

  return (
    <AppShell title={title}>
      <ErrorBoundary resetKey={location.pathname}>
        {children}
      </ErrorBoundary>
    </AppShell>
  );
}

function LoginPage() {
  useEffect(() => {
    document.title = 'Sign In | Just Resume';
  }, []);
  return <Login />;
}

function AuthCallbackPage() {
  const { session, error } = useAuthStore();
  const params = new URLSearchParams(window.location.search);
  const callbackError = params.get('error_description') || params.get('error');

  if (session) {
    return <Navigate to="/dashboard" replace />;
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
            <span className="badge badge-danger">Authentication callback failed</span>
            <h2>Google sign-in did not create a session</h2>
            <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              {callbackError || error || 'Supabase returned to the app without a valid login session.'}
            </p>
            <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              Confirm <code>http://localhost:3099/auth/callback</code> is in Supabase redirect URLs.
              If it is already there, re-save the Google provider Client ID and Client Secret in Supabase.
            </p>
          </div>
          <a className="btn btn-primary btn-lg google-login-button" href="/login">
            Back to sign in
          </a>
        </div>
      </section>
    </main>
  );
}

export default function App() {
  const { session, initialized, initialize } = useAuthStore();

  useEffect(() => {
    void initialize();
  }, [initialize]);

  if (!initialized) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-card">
          <div className="spinner spinner-lg" />
          <div>
            <h1>Just Resume</h1>
            <p>Loading your workspace...</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        {/* Public routes */}
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/callback" element={<AuthCallbackPage />} />
        <Route path="/access-denied" element={<AccessDenied />} />

        {/* Root redirect */}
        <Route
          path="/"
          element={
            session ? <Navigate to="/dashboard" replace /> : <Navigate to="/login" replace />
          }
        />

        {/* Protected routes with AppShell */}
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="Dashboard">
                <Dashboard />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/profile"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="Profile">
                <MasterProfile />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/create-resume/advanced"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="Advanced Resume Builder">
                <ResumeCreationWizard />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/create-resume"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="Fast Resume Builder">
                <FastResumeBuilder />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/review/:generationId"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="Resume Review">
                <ResumeReview />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/history"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="History">
                <History />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/history/:id"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="History Detail">
                <HistoryDetail />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/cover-letter/:generationId"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="Cover Letter">
                <CoverLetter />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <ProtectedLayout title="Settings">
                <Settings />
              </ProtectedLayout>
            </ProtectedRoute>
          }
        />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
