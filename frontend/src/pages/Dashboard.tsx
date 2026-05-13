/**
 * Dashboard page — landing view showing session status and quick actions.
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDefaultProfile, getRecentResumes, type RecentResume } from '../lib/db';
import { useAppStore } from '../store/useAppStore';
import type { MasterProfile } from '../types/profile';

export default function Dashboard() {
  const navigate = useNavigate();
  const { resetSession } = useAppStore();
  const [profile, setProfile] = useState<MasterProfile | null>(null);
  const [recentResumes, setRecentResumes] = useState<RecentResume[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([getDefaultProfile(), getRecentResumes(5)]).then(([p, recent]) => {
      setProfile(p);
      setRecentResumes(recent);
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

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 'var(--space-md)' }}>
        <div className="card" style={{ cursor: 'pointer' }} onClick={() => navigate('/profile')}>
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-md)' }}>👤</div>
          <div className="card-title">Create/Edit Master Profile</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: 'var(--space-xs)' }}>
            {hasProfile
              ? profileSummary
              : 'Set up your professional profile to get started.'}
          </p>
          {!hasProfile && (
            <span className="badge badge-warning" style={{ marginTop: 'var(--space-sm)' }}>Profile required</span>
          )}
          {hasProfile && (
            <span className="badge badge-success" style={{ marginTop: 'var(--space-sm)' }}>Profile ready</span>
          )}
        </div>

        <div
          className="card"
          style={{ cursor: hasProfile ? 'pointer' : 'default', opacity: hasProfile ? 1 : 0.5 }}
          onClick={hasProfile ? handleNewResume : undefined}
        >
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-md)' }}>📄</div>
          <div className="card-title">Paste JD & Generate Resume</div>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: 'var(--space-xs)' }}>
            Paste a job description and generate a one-page ATS resume.
          </p>
          {!hasProfile && (
            <span className="badge badge-neutral" style={{ marginTop: 'var(--space-sm)' }}>Profile required first</span>
          )}
        </div>
      </div>

      {recentResumes.length > 0 && (
        <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
          <div className="card-title" style={{ marginBottom: 'var(--space-md)' }}>Recent Resumes</div>
          <div style={{ display: 'grid', gap: 'var(--space-sm)' }}>
            {recentResumes.map((resume) => (
              <div
                key={resume.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 'var(--space-md)',
                  padding: 'var(--space-sm) 0',
                  borderTop: '1px solid var(--border-subtle)',
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>{resume.job_title}</div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                    {[resume.company, new Date(resume.date).toLocaleDateString()].filter(Boolean).join(' | ')}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)', flexShrink: 0 }}>
                  {typeof resume.ats_score === 'number' && (
                    <span className="badge badge-info">{Math.round(resume.ats_score)} ATS</span>
                  )}
                  {resume.pdf_url && <span className="badge badge-success">PDF</span>}
                  {resume.cover_letter && <span className="badge badge-neutral">Cover letter</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
