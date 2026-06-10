import { useNavigate } from 'react-router-dom';

export default function OnboardingWelcome() {
  const navigate = useNavigate();

  return (
    <section className="card animate-fade-in" style={{ padding: 'var(--space-xl)' }}>
      <div style={{ display: 'grid', gap: 'var(--space-xl)', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(240px, 0.6fr)', alignItems: 'center' }}>
        <div>
          <p style={{ color: 'var(--text-secondary)', fontWeight: 700, marginBottom: 8 }}>Welcome to JustResume AI</p>
          <h2 style={{ fontSize: '2rem', lineHeight: 1.15, margin: 0 }}>Create your first ATS-optimised resume</h2>
          <div style={{ display: 'grid', gap: 12, marginTop: 'var(--space-lg)' }}>
            {['Complete your profile', 'Paste a job description', 'Download your resume'].map((label, index) => (
              <div key={label} style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span style={{ width: 32, height: 32, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'var(--primary, #2563eb)', color: '#fff', fontWeight: 800 }}>
                  {index + 1}
                </span>
                <strong>{label}</strong>
              </div>
            ))}
          </div>
          <button className="btn btn-primary btn-lg" onClick={() => navigate('/profile')} style={{ marginTop: 'var(--space-xl)' }}>
            Start now →
          </button>
          <p style={{ color: 'var(--text-secondary)', marginTop: 'var(--space-md)', marginBottom: 0 }}>
            Join professionals who have already improved their ATS score.
          </p>
        </div>

        <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 'var(--space-lg)', background: 'var(--bg-secondary, #f8fafc)' }}>
          <div style={{ color: 'var(--text-secondary)', fontWeight: 700, marginBottom: 12 }}>Sample ATS lift</div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div>
              <div style={{ fontSize: '2rem', fontWeight: 800, color: '#E24B4A' }}>28</div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Before</div>
            </div>
            <div style={{ fontSize: '1.5rem', color: 'var(--text-secondary)' }}>→</div>
            <div>
              <div style={{ fontSize: '2rem', fontWeight: 800, color: '#1D9E75' }}>87</div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>After</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
