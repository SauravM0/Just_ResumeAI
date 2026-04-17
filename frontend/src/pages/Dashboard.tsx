/**
 * Dashboard page — landing view showing session status and quick actions.
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDefaultProfile } from '../lib/db';
import { useAppStore } from '../store/useAppStore';
import type { MasterProfile } from '../types/profile';

export default function Dashboard() {
  const navigate = useNavigate();
  const { resetSession } = useAppStore();
  const [profile, setProfile] = useState<MasterProfile | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getDefaultProfile().then((p) => {
      setProfile(p);
      setLoading(false);
    });
  }, []);

  const hasProfile = Boolean(profile?.contact.full_name);
  const profileSummary = profile
    ? `${profile.contact.full_name} — ${profile.work_experience.length} experiences, ${profile.skills.length} skills`
    : '';

  const handleNewResume = () => {
    resetSession();
    navigate('/jd');
  };

  if (loading) {
    return (
      <div className="loading-state">
        <div className="spinner spinner-lg" />
        <div className="loading-text">Loading...</div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <h1 className="page-title">Welcome to JustResume AI</h1>
        <p className="page-subtitle">
          Generate highly tailored, ATS-friendly resumes in minutes.
        </p>
      </div>

      {/* Quick Actions */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 'var(--space-md)' }}>
        {/* Profile Card */}
        <div className="card" style={{ cursor: 'pointer' }} onClick={() => navigate('/profile')}>
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-md)' }}>👤</div>
          <div className="card-title">
            {hasProfile ? 'Edit Master Profile' : 'Create Master Profile'}
          </div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: 'var(--space-xs)' }}>
            {hasProfile
              ? profileSummary
              : 'Set up your professional profile to get started.'}
          </p>
          {!hasProfile && (
            <span className="badge badge-warning" style={{ marginTop: 'var(--space-sm)' }}>Required</span>
          )}
          {hasProfile && (
            <span className="badge badge-success" style={{ marginTop: 'var(--space-sm)' }}>Ready</span>
          )}
        </div>

        {/* New Resume Card */}
        <div
          className="card"
          style={{ cursor: hasProfile ? 'pointer' : 'default', opacity: hasProfile ? 1 : 0.5 }}
          onClick={hasProfile ? handleNewResume : undefined}
        >
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-md)' }}>📄</div>
          <div className="card-title">Generate New Resume</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: 'var(--space-xs)' }}>
            Paste a job description and let AI create a tailored resume.
          </p>
          {!hasProfile && (
            <span className="badge badge-neutral" style={{ marginTop: 'var(--space-sm)' }}>Profile required first</span>
          )}
        </div>

        {/* Pipeline Info Card */}
        <div className="card">
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-md)' }}>🔬</div>
          <div className="card-title">AI Pipeline</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: 'var(--space-xs)' }}>
            Multi-step process: JD Analysis → Relevance Matching → Composition → Human Review → PDF Export
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: 'var(--space-sm)' }}>
            {['ATS Optimized', 'Human Review', 'LaTeX Rendered'].map((tag) => (
              <span key={tag} className="badge badge-info">{tag}</span>
            ))}
          </div>
        </div>
      </div>

      {/* Pipeline Steps Overview */}
      <div className="card" style={{ marginTop: 'var(--space-xl)' }}>
        <div className="card-title" style={{ marginBottom: 'var(--space-lg)' }}>How It Works</div>
        <div className="pipeline-steps">
          {[
            { icon: '👤', label: 'Master Profile', done: !!hasProfile },
            { icon: '📋', label: 'Paste JD' },
            { icon: '🔍', label: 'AI Analysis' },
            { icon: '🎯', label: 'Relevance Match' },
            { icon: '✍️', label: 'AI Composition' },
            { icon: '👁️', label: 'Human Review' },
            { icon: '📊', label: 'ATS Scoring' },
            { icon: '📑', label: 'LaTeX Render' },
            { icon: '📥', label: 'PDF Export' },
          ].map((step, i, arr) => (
            <div key={step.label} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <div className={`pipeline-step ${step.done ? 'step-done' : ''}`}>
                <span>{step.icon}</span>
                <span>{step.label}</span>
              </div>
              {i < arr.length - 1 && <div className="pipeline-connector" />}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
