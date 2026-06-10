import { useState } from 'react';
import type { MasterProfile } from '../../types/profile';

interface Props {
  profile: MasterProfile | null;
  loading: boolean;
  error: boolean;
  onContinue: () => void;
  onEditProfile: () => void;
  onSkip: () => void;
}

export default function ProfileSelector({ profile, loading, error, onContinue, onEditProfile, onSkip }: Props) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const hasName = Boolean(profile?.contact.full_name?.trim());
  const hasExperience = (profile?.work_experience?.length ?? 0) > 0;
  const hasEducation = (profile?.education?.length ?? 0) > 0;
  const hasSkills = (profile?.skills?.length ?? 0) > 0;
  const hasSummary = Boolean(profile?.summary?.trim());

  const completionSections = [
    { label: 'Contact Info', done: hasName },
    { label: 'Work Experience', done: hasExperience },
    { label: 'Education', done: hasEducation },
    { label: 'Skills', done: hasSkills },
    { label: 'Summary', done: hasSummary },
  ];

  const completedCount = completionSections.filter((s) => s.done).length;
  const completionPercent = Math.round((completedCount / completionSections.length) * 100);

  if (loading) {
    return (
      <div className="card profile-selector-card">
        <div className="profile-selector-loading">
          <div className="spinner spinner-lg" />
          <p>Loading your profile...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card profile-selector-card">
        <div className="profile-selector-error">
          <div className="profile-selector-icon">⚠️</div>
          <h3>Unable to load profile</h3>
          <p>We couldn't retrieve your profile data. Please try again or create a new one.</p>
          <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', marginTop: 'var(--space-md)' }}>
            <button className="btn btn-primary" onClick={onEditProfile}>
              Go to Profile
            </button>
            <button className="btn btn-ghost" onClick={onSkip}>
              Continue anyway
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!hasName) {
    return (
      <div className="card profile-selector-card">
        <div className="profile-selector-empty">
          <div className="profile-selector-icon">👤</div>
          <h3>No profile found</h3>
          <p>
            To generate a tailored resume, we need your professional information first.
            Set up your profile with your contact details, experience, education, and skills.
          </p>
          <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', marginTop: 'var(--space-md)' }}>
            <button className="btn btn-primary btn-lg" onClick={onEditProfile}>
              Set Up Your Profile
            </button>
            <button className="btn btn-ghost" onClick={onSkip}>
              Skip for now
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card profile-selector-card">
      <div className="profile-selector-header">
        <div className="profile-selector-avatar">
          {profile?.contact.full_name?.charAt(0).toUpperCase() ?? '?'}
        </div>
        <div className="profile-selector-info">
          <h3>{profile?.contact.full_name}</h3>
          <p className="profile-selector-subtitle">
            {profile?.contact.email || 'No email set'}
            {profile?.contact.phone && ` · ${profile.contact.phone}`}
          </p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={onEditProfile}>
          Edit
        </button>
      </div>

      <div className="profile-selector-progress">
        <div className="profile-selector-progress-bar">
          <div
            className="profile-selector-progress-fill"
            style={{ width: `${completionPercent}%` }}
          />
        </div>
        <span className="profile-selector-progress-label">
          {completedCount}/{completionSections.length} sections complete
        </span>
      </div>

      {showAdvanced && (
        <div className="profile-selector-sections">
          {completionSections.map((section) => (
            <div
              key={section.label}
              className={`profile-selector-section ${section.done ? 'done' : 'incomplete'}`}
            >
              <span className="profile-selector-section-icon">
                {section.done ? '✓' : '○'}
              </span>
              <span>{section.label}</span>
            </div>
          ))}
        </div>
      )}

      <button
        className="profile-selector-toggle"
        onClick={() => setShowAdvanced(!showAdvanced)}
      >
        {showAdvanced ? 'Hide details' : `Show ${completionSections.length - completedCount} incomplete sections`}
      </button>

      <div className="profile-selector-actions">
        <button className="btn btn-primary btn-lg" onClick={onContinue}>
          Use This Profile
        </button>
      </div>
    </div>
  );
}
