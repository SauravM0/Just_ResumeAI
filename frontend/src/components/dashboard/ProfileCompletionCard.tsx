import { useNavigate } from 'react-router-dom';
import type { MasterProfile } from '../../types/profile';

function getProfileCompletion(profile: MasterProfile | null): { score: number; missingSections: string[] } {
  if (!profile) return { score: 0, missingSections: ['Complete your profile to get started'] };
  const missing: string[] = [];
  if (!profile.contact.full_name) missing.push('Full Name');
  if (!profile.contact.email) missing.push('Email');
  if (!profile.summary) missing.push('Professional Summary');
  if (profile.work_experience.length === 0) missing.push('Work Experience');
  if (profile.education.length === 0) missing.push('Education');
  if (profile.skills.length === 0) missing.push('Skills');
  const totalSections = 6;
  const completed = totalSections - missing.length;
  const score = Math.round((completed / totalSections) * 100);
  return { score, missingSections: missing };
}

interface Props {
  profile: MasterProfile | null;
}

export default function ProfileCompletionCard({ profile }: Props) {
  const navigate = useNavigate();
  const { score, missingSections } = getProfileCompletion(profile);
  const isComplete = score === 100;
  const sectionLabel = profile
    ? `${profile.contact.full_name || 'Unknown'}`
    : 'No profile';

  return (
    <div className={`card profile-completion-card ${isComplete ? 'complete' : 'incomplete'}`}>
      <div className="profile-completion-header">
        <div className="profile-completion-icon">
          {isComplete ? '\u2705' : '\u26A0\uFE0F'}
        </div>
        <div className="profile-completion-info">
          <div className="profile-completion-name">{sectionLabel}</div>
          <div className="profile-completion-subtitle">
            {isComplete ? 'Profile complete' : `${missingSections.length} section${missingSections.length !== 1 ? 's' : ''} missing`}
          </div>
        </div>
        <div className="profile-completion-score">
          <div className={`completion-ring ${isComplete ? 'ring-complete' : score >= 50 ? 'ring-partial' : 'ring-low'}`}>
            <svg width="48" height="48" viewBox="0 0 48 48">
              <circle cx="24" cy="24" r="20" fill="none" stroke="var(--border-subtle)" strokeWidth="4" />
              <circle
                cx="24" cy="24" r="20"
                fill="none"
                stroke="currentColor"
                strokeWidth="4"
                strokeDasharray={`${2 * Math.PI * 20}`}
                strokeDashoffset={`${2 * Math.PI * 20 * (1 - score / 100)}`}
                strokeLinecap="round"
                transform="rotate(-90 24 24)"
                style={{ transition: 'stroke-dashoffset 0.6s ease' }}
              />
            </svg>
            <span className="completion-score-text">{score}%</span>
          </div>
        </div>
      </div>

      {!isComplete && missingSections.length > 0 && (
        <div className="profile-completion-details">
          <div className="missing-sections-title">Missing sections:</div>
          <div className="missing-sections-list">
            {missingSections.map((section) => (
              <span key={section} className="badge badge-warning">{section}</span>
            ))}
          </div>
        </div>
      )}

      <button
        className="btn btn-primary btn-sm"
        onClick={() => navigate('/profile')}
        style={{ marginTop: 'var(--space-md)', width: '100%' }}
      >
        {isComplete ? 'Edit Profile' : 'Complete Profile'}
      </button>
    </div>
  );
}
