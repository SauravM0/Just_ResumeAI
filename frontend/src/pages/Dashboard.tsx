import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getHistory, type HistoryItem } from '../lib/historyApi';
import { getMyProfile } from '../lib/profileApi';
import { useAppStore } from '../store/useAppStore';
import { useAuthStore } from '../store/useAuthStore';
// Query-keys (for future TanStack Query migration):
//   profile:  ['profile', user?.id]  staleTime=5min
//   history:  ['generations', user?.id]  staleTime=30s
import PageHeader from '../components/ui/PageHeader';
import AppCard from '../components/ui/AppCard';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import DashboardSkeleton from '../components/dashboard/DashboardSkeleton';
import ProfileCompletionCard from '../components/dashboard/ProfileCompletionCard';
import QuickActions from '../components/dashboard/QuickActions';
import OnboardingWelcome from '../components/OnboardingWelcome';
import type { MasterProfile } from '../types/profile';

const APP_VERSION = import.meta.env.VITE_APP_VERSION || '0.1.0';

function getDaysUntilExpiry(expiryDate: string | null): number | null {
  if (!expiryDate) return null;
  const diff = new Date(expiryDate).getTime() - Date.now();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

function getExpiryLabel(days: number | null): { text: string; variant: 'success' | 'warning' | 'danger' } {
  if (days === null) return { text: 'No expiry', variant: 'success' };
  if (days <= 0) return { text: 'Expired', variant: 'danger' };
  if (days <= 3) return { text: `Expires in ${days}d`, variant: 'danger' };
  if (days <= 14) return { text: `Expires in ${days}d`, variant: 'warning' };
  return { text: `${days}d remaining`, variant: 'success' };
}

function formatAtsScore(score: number | null | undefined): { label: string; variant: 'high' | 'mid' | 'low' } {
  if (score === null || score === undefined) return { label: '--', variant: 'mid' };
  if (score >= 80) return { label: `${Math.round(score)}`, variant: 'high' };
  if (score >= 60) return { label: `${Math.round(score)}`, variant: 'mid' };
  return { label: `${Math.round(score)}`, variant: 'low' };
}

function getProfileCompletionStatus(profile: MasterProfile | null): { label: string; variant: 'success' | 'warning' | 'danger' } {
  if (!profile?.contact.full_name) return { label: 'Not started', variant: 'danger' };
  const hasSummary = Boolean(profile.summary);
  const hasExperience = profile.work_experience.length > 0;
  const hasEducation = profile.education.length > 0;
  const hasSkills = profile.skills.length > 0;
  const sections = [hasSummary, hasExperience, hasEducation, hasSkills];
  const completed = sections.filter(Boolean).length;
  if (completed === 0) return { label: 'Incomplete', variant: 'warning' };
  if (completed < 3) return { label: `${completed}/4 sections`, variant: 'warning' };
  return { label: 'Complete', variant: 'success' };
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { resetGeneration } = useAppStore();
  const user = useAuthStore((s) => s.user);
  const [profile, setProfile] = useState<MasterProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState(false);
  const [recentHistory, setRecentHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(false);
  const [showWhatsNew, setShowWhatsNew] = useState(false);

  const fetchData = useCallback(() => {
    setProfileLoading(true);
    setHistoryLoading(true);
    setProfileError(false);
    setHistoryError(false);

    // ── Query keys (for future TanStack Query migration) ──
    //   profile:   QUERY_KEYS.profile(user?.id)
    //   history:   QUERY_KEYS.generations(user?.id)
    //
    // Cache config reference:
    //   profile:   staleTime=CACHE_CONFIG.profile.staleTime (5 min)
    //   history:   staleTime=CACHE_CONFIG.generations.staleTime (30 s)

    getMyProfile()
      .then((res) => {
        setProfile(res.profile_json);
        setProfileLoading(false);
      })
      .catch(() => {
        setProfileLoading(false);
        setProfileError(true);
      });

    getHistory(10)
      .then((history) => {
        setRecentHistory(history);
        setHistoryLoading(false);
      })
      .catch(() => {
        setHistoryLoading(false);
        setHistoryError(true);
      });
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    const key = 'justresume:lastSeenVersion';
    const previous = window.localStorage.getItem(key);
    if (previous && previous !== APP_VERSION) {
      setShowWhatsNew(true);
    }
    window.localStorage.setItem(key, APP_VERSION);
  }, []);

  const hasProfile = Boolean(profile?.contact.full_name);
  const loading = profileLoading || historyLoading;
  const hasError = profileError && historyError;
  const profileStatus = getProfileCompletionStatus(profile);

  const handleNewResume = () => {
    resetGeneration();
    navigate('/create-resume');
  };

  const averageAts = recentHistory.length > 0
    ? recentHistory.reduce((sum, h) => sum + (h.ats_score_summary?.overall_score ?? 0), 0) / recentHistory.length
    : null;

  const coverLetterCount = recentHistory.filter((h) => h.has_cover_letter).length;

  const earliestExpiry = recentHistory
    .map((h) => h.file_expiry_info?.expires_at ?? h.file_expiry_info?.earliest_expiry ?? null)
    .filter(Boolean)
    .sort()[0] ?? null;

  const expiryDays = getDaysUntilExpiry(earliestExpiry as string | null);
  const expiryInfo = getExpiryLabel(expiryDays);

  const hasExpiredFiles = recentHistory.some((h) => h.file_expiry_info?.is_expired);

  if (loading && !profile && recentHistory.length === 0) {
    return <DashboardSkeleton />;
  }

  // Error state
  if (hasError) {
    return (
      <div className="animate-fade-in">
        <PageHeader title="Dashboard" subtitle="Welcome to JustResume AI" />
        <ErrorState
          message="Failed to load your dashboard data. Check your connection and try again."
          onRetry={fetchData}
        />
      </div>
    );
  }

  // First-time user — no profile
  if (!historyError && recentHistory.length === 0 && !historyLoading && !profileLoading) {
    return (
      <div className="animate-fade-in">
        <PageHeader
          title={`Welcome${user?.user_metadata?.full_name ? `, ${user.user_metadata.full_name.split(' ')[0]}` : ''}!`}
          subtitle="Let's create your first tailored resume."
        />
        <OnboardingWelcome />
        {hasProfile && (
          <div style={{ marginTop: 'var(--space-lg)' }}>
            <ProfileCompletionCard profile={profile} />
          </div>
        )}
      </div>
    );
  }

  if (!hasProfile && !profileLoading && recentHistory.length === 0) {
    return (
      <div className="animate-fade-in">
        <PageHeader
          title={`Welcome${user?.user_metadata?.full_name ? `, ${user.user_metadata.full_name.split(' ')[0]}` : ''}!`}
          subtitle="Let's get started with your first resume."
        />
        <div className="welcome-hero">
          <div className="welcome-hero-icon">\uD83D\uDC4B</div>
          <h2 className="welcome-hero-title">Welcome to JustResume AI</h2>
          <p className="welcome-hero-desc">
            Create tailored, ATS-friendly resumes in minutes. Start by setting up your profile.
          </p>
          <div className="welcome-steps">
            <div className="welcome-step">
              <div className="welcome-step-num">1</div>
              <div>
                <strong>Create your profile</strong>
                <p>Add your contact info, experience, education, and skills.</p>
              </div>
            </div>
            <div className="welcome-step">
              <div className="welcome-step-num">2</div>
              <div>
                <strong>Paste a job description</strong>
                <p>AI analyzes the JD and generates a tailored resume.</p>
              </div>
            </div>
            <div className="welcome-step">
              <div className="welcome-step-num">3</div>
              <div>
                <strong>Review and export</strong>
                <p>Edit visually, check ATS score, and export PDF or DOCX.</p>
              </div>
            </div>
          </div>
          <button className="btn btn-primary btn-lg" onClick={() => navigate('/profile')} style={{ marginTop: 'var(--space-lg)' }}>
            Set Up Your Profile
          </button>
        </div>
      </div>
    );
  }

  // Has profile but no history
  if (hasProfile && !historyError && recentHistory.length === 0 && !historyLoading && !profileLoading) {
    return (
      <div className="animate-fade-in">
        <PageHeader
          title={`Ready${user?.user_metadata?.full_name ? `, ${user.user_metadata.full_name.split(' ')[0]}` : ''}!`}
          subtitle="Your profile is set. Now generate your first resume."
        />
        <div className="dashboard-main-grid">
          <div className="dashboard-left-column">
            <ProfileCompletionCard profile={profile} />
          </div>
          <div className="dashboard-right-column">
            <EmptyState
              icon="\uD83D\uDCCB"
              title="No resumes yet"
              description="Paste a job description to generate your first ATS-optimized, tailored resume."
              action={
                <button className="btn btn-primary btn-lg" onClick={handleNewResume}>
                  Generate Your First Resume
                </button>
              }
            />
          </div>
        </div>
      </div>
    );
  }

  // History error but profile loaded
  if (historyError && hasProfile) {
    return (
      <div className="animate-fade-in">
        <PageHeader
          title={`Welcome${user?.user_metadata?.full_name ? `, ${user.user_metadata.full_name.split(' ')[0]}` : ' back'}`}
          subtitle="Your dashboard overview."
          actions={
            <button className="btn btn-primary" onClick={handleNewResume}>
              + New Resume
            </button>
          }
        />
        <div className="dashboard-main-grid">
          <div className="dashboard-left-column">
            <ProfileCompletionCard profile={profile} />
            <QuickActions />
          </div>
          <div className="dashboard-right-column">
            <AppCard title="Recent Generations">
              <div style={{ textAlign: 'center', padding: 'var(--space-xl) 0' }}>
                <p style={{ color: 'var(--text-secondary)', marginBottom: 'var(--space-md)' }}>
                  Failed to load recent generations.
                </p>
                <button className="btn btn-secondary btn-sm" onClick={fetchData}>Retry</button>
              </div>
            </AppCard>
          </div>
        </div>
      </div>
    );
  }

  // Has history — full dashboard
  const userName = user?.user_metadata?.full_name
    ? user.user_metadata.full_name.split(' ')[0]
    : '';

  return (
    <div className="animate-fade-in">
      {showWhatsNew && (
        <div className="warning-banner warning-info" style={{ marginBottom: 'var(--space-md)' }}>
          <span>New</span>
          <div>
            <strong>What's new in v{APP_VERSION}</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              Improved ATS scoring, export readiness checks, and production monitoring are now live.
            </p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => setShowWhatsNew(false)}>
            Dismiss
          </button>
        </div>
      )}
      <PageHeader
        title={userName ? `Welcome back, ${userName}` : 'Dashboard'}
        subtitle="Here's your resume activity at a glance."
        actions={
          <button className="btn btn-primary" onClick={handleNewResume}>
            + New Resume
          </button>
        }
      />

      <div className="dashboard-stats-row">
        <div className="card dashboard-stat-card">
          <div className="stat-icon stat-icon-profile">\uD83D\uDC64</div>
          <div className={`stat-value stat-${profileStatus.variant}`}>{profileStatus.label}</div>
          <div className="stat-label">Profile</div>
        </div>

        <div className="card dashboard-stat-card">
          <div className="stat-icon stat-icon-ats">\uD83D\uDCCA</div>
          <div className={`stat-value ${averageAts !== null ? `score-${formatAtsScore(averageAts).variant}` : ''}`}>
            {recentHistory.length > 0 ? formatAtsScore(averageAts).label : '--'}
          </div>
          <div className="stat-label">Avg. ATS Score</div>
        </div>

        <div className="card dashboard-stat-card">
          <div className="stat-icon stat-icon-cover">\uD83D\uDCDD</div>
          <div className="stat-value">{coverLetterCount > 0 ? coverLetterCount : 0}</div>
          <div className="stat-label">Cover Letters</div>
        </div>

        <div className="card dashboard-stat-card">
          <div className="stat-icon stat-icon-expiry">\u23F0</div>
          <div className={`stat-value stat-${expiryInfo.variant}`}>{expiryInfo.text}</div>
          <div className="stat-label">File Expiry</div>
        </div>
      </div>

      <div className="dashboard-main-grid">
        <div className="dashboard-left-column">
          {profileLoading ? (
            <div className="skeleton skeleton-card" style={{ height: 180 }} />
          ) : (
            <ProfileCompletionCard profile={profile} />
          )}

          <QuickActions />
        </div>

        <div className="dashboard-right-column">
          {historyLoading ? (
            <div className="skeleton skeleton-card" style={{ height: 300 }} />
          ) : (
            <AppCard
              title="Recent Generations"
              subtitle={recentHistory.length > 0 ? `${recentHistory.length} total` : undefined}
              actions={
                recentHistory.length > 0 ? (
                  <button className="btn btn-ghost btn-sm" onClick={() => navigate('/history')}>
                    View All
                  </button>
                ) : undefined
              }
            >
              {recentHistory.length > 0 ? (
                <div className="recent-generations-list">
                  {recentHistory.slice(0, 5).map((item) => {
                    const ats = formatAtsScore(item.ats_score_summary?.overall_score);
                    const isExpired = item.file_expiry_info?.is_expired;
                    const canRegen = item.file_expiry_info?.regenerate_available;
                    const hasFiles = item.file_expiry_info?.has_files;
                    return (
                      <div key={item.generation_id} className="recent-generation-item">
                        <div className="recent-gen-main" onClick={() => navigate(`/history/${item.generation_id}`)}>
                          <div className="recent-gen-info">
                            <div className="recent-gen-title">{item.job_title || 'Untitled Resume'}</div>
                            <div className="recent-gen-meta">
                              {item.company && <span>{item.company}</span>}
                              {item.created_at && (
                                <>
                                  <span className="meta-sep">\u00B7</span>
                                  <span>{new Date(item.created_at).toLocaleDateString()}</span>
                                </>
                              )}
                              <span className="meta-sep">\u00B7</span>
                              <span className={`badge badge-${item.status === 'completed' ? 'success' : 'neutral'}`}>
                                {item.status}
                              </span>
                              {isExpired && hasFiles && (
                                <>
                                  <span className="meta-sep">\u00B7</span>
                                  <span className="badge badge-warning">Files expired</span>
                                </>
                              )}
                              {item.has_pdf && !isExpired && (
                                <>
                                  <span className="meta-sep">\u00B7</span>
                                  <span className="badge badge-neutral">PDF</span>
                                </>
                              )}
                              {item.file_expiry_info?.docx_available && !isExpired && (
                                <>
                                  <span className="meta-sep">\u00B7</span>
                                  <span className="badge badge-neutral">DOCX</span>
                                </>
                              )}
                            </div>
                          </div>
                          <div className={`recent-gen-score score-${ats.variant}`}>
                            <div className="recent-gen-score-value">{ats.label}</div>
                            <div className="recent-gen-score-label">ATS</div>
                          </div>
                        </div>
                        <div className="recent-gen-actions">
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => navigate(`/history/${item.generation_id}`)}
                          >
                            Open
                          </button>
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => navigate(`/review/${item.generation_id}`)}
                          >
                            Edit
                          </button>
                          {canRegen && isExpired && (
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => navigate(`/history/${item.generation_id}`)}
                            >
                              Refresh Files
                            </button>
                          )}
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => navigate(`/cover-letter/${item.generation_id}`)}
                          >
                            Cover Letter
                          </button>
                        </div>
                      </div>
                    );
                  })}
                  {recentHistory.length > 5 && (
                    <button
                      className="btn btn-ghost"
                      style={{ marginTop: 'var(--space-md)', width: '100%' }}
                      onClick={() => navigate('/history')}
                    >
                      View All {recentHistory.length} Generations \u2192
                    </button>
                  )}
                </div>
              ) : (
                <EmptyState
                  icon="\uD83D\uDCCB"
                  title="No resumes yet"
                  description="Paste a job description to generate your first ATS-optimized resume."
                  action={
                    <button className="btn btn-primary" onClick={handleNewResume}>
                      Generate Your First Resume
                    </button>
                  }
                />
              )}
            </AppCard>
          )}

          {hasExpiredFiles && (
            <div className="warning-banner warning-warn">
              <span>\u26A0\uFE0F</span>
              <div>
                <strong>Some files have expired</strong>
                <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
                  Export files expire after a period. You can regenerate them from the generation detail page.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
