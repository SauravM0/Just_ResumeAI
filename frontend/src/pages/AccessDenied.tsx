import { useAuthStore } from '../store/useAuthStore';

export default function AccessDenied() {
  const { signOut } = useAuthStore();

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
            <span className="badge badge-warning">Access restricted</span>
            <h2>Private beta — invite only</h2>
            <p style={{ color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              Your account is not yet approved for this private beta.
              Only allowlisted users can access JustResume AI during this phase.
            </p>
            <div
              style={{
                marginTop: 'var(--space-lg)',
                padding: 'var(--space-md)',
                background: 'var(--bg-warning-subtle, #fff8e1)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-warning, #ffe0b2)',
                fontSize: '0.85rem',
                lineHeight: 1.5,
                color: 'var(--text-warning, #e65100)',
              }}
            >
              If you believe you should have access, contact the project administrator
              and ask them to add your Google account email to the allowlist.
            </div>
          </div>

          <button
            type="button"
            className="btn btn-danger btn-lg"
            onClick={() => signOut()}
            style={{ width: '100%', marginTop: 'var(--space-lg)' }}
          >
            Sign out
          </button>
        </div>
      </section>
    </main>
  );
}
