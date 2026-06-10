import { useNavigate } from 'react-router-dom';
import { useAppStore } from '../../store/useAppStore';

export default function QuickActions() {
  const navigate = useNavigate();
  const { resetGeneration } = useAppStore();

  const handleNewResume = () => {
    resetGeneration();
    navigate('/create-resume');
  };

  const actions = [
    {
      icon: '\uD83D\uDCC4',
      label: 'New Resume',
      desc: 'Create a tailored resume from a job description',
      onClick: handleNewResume,
      primary: true,
    },
    {
      icon: '\uD83D\uDC64',
      label: 'Edit Profile',
      desc: 'Update your professional information',
      onClick: () => navigate('/profile'),
      primary: false,
    },
    {
      icon: '\u23F1\uFE0F',
      label: 'View History',
      desc: 'Browse all your past generations',
      onClick: () => navigate('/history'),
      primary: false,
    },
    {
      icon: '\uD83D\uDCDD',
      label: 'Cover Letter',
      desc: 'Generate a cover letter for any resume',
      onClick: () => navigate('/history'),
      primary: false,
    },
  ];

  return (
    <div className="card quick-actions-card">
      <div className="card-header">
        <div className="card-title">Quick Actions</div>
      </div>
      <div className="quick-actions-grid">
        {actions.map((action) => (
          <button
            key={action.label}
            className={`quick-action-btn ${action.primary ? 'quick-action-primary' : ''}`}
            onClick={action.onClick}
          >
            <span className="quick-action-icon">{action.icon}</span>
            <div className="quick-action-text">
              <span className="quick-action-label">{action.label}</span>
              <span className="quick-action-desc">{action.desc}</span>
            </div>
            <span className="quick-action-arrow">{'\u2192'}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
