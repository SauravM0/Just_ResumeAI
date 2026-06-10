import { useEffect, useState } from 'react';
import { useAuthStore } from '../store/useAuthStore';
import { getSettings, updateSettings, type UserSettings } from '../lib/settingsApi';
import { getAppConfig, formatEnvironmentLabel } from '../lib/appConfig';
import PageHeader from '../components/ui/PageHeader';
import AppCard from '../components/ui/AppCard';
import LoadingState from '../components/ui/LoadingState';
import ErrorState from '../components/ui/ErrorState';

const TONE_OPTIONS = [
  { value: 'professional', label: 'Professional' },
  { value: 'formal', label: 'Formal' },
  { value: 'conversational', label: 'Conversational' },
  { value: 'enthusiastic', label: 'Enthusiastic' },
  { value: 'confident', label: 'Confident' },
];

const PAGE_OPTIONS = [
  { value: 1, label: '1 page' },
  { value: 2, label: '2 pages' },
];

export default function Settings() {
  const { user, signOut, loading: authLoading } = useAuthStore();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [targetPages, setTargetPages] = useState(1);
  const [preferredTone, setPreferredTone] = useState('professional');
  const [aggressiveAtsDefault, setAggressiveAtsDefault] = useState(false);

  const appConfig = getAppConfig();
  const email = user?.email ?? '';

  const fetchSettings = () => {
    setLoading(true);
    setError(null);
    getSettings()
      .then((data) => {
        setSettings(data);
        setTargetPages(data.target_resume_pages);
        setPreferredTone(data.preferred_tone);
        setAggressiveAtsDefault(Boolean(data.aggressive_ats_default));
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load settings');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const updated = await updateSettings({
        target_resume_pages: targetPages,
        preferred_tone: preferredTone,
        aggressive_ats_default: aggressiveAtsDefault,
      });
      setSettings(updated);
      setSuccess('Settings saved successfully.');
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    await signOut();
  };

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Settings"
        subtitle="Manage your preferences and account."
      />

      {loading ? (
        <LoadingState text="Loading settings..." />
      ) : error && !settings ? (
        <ErrorState message={error} onRetry={fetchSettings} />
      ) : (
        <div className="settings-page-layout">
          <AppCard title="Preferences">
            <div className="settings-form">
              <div className="form-group">
                <label className="form-label">Preferred Resume Tone</label>
                <div className="settings-radio-group">
                  {TONE_OPTIONS.map((opt) => (
                    <label key={opt.value} className={`settings-radio ${preferredTone === opt.value ? 'active' : ''}`}>
                      <input
                        type="radio"
                        name="preferred_tone"
                        value={opt.value}
                        checked={preferredTone === opt.value}
                        onChange={() => setPreferredTone(opt.value)}
                      />
                      <span>{opt.label}</span>
                    </label>
                  ))}
                </div>
                <span className="form-hint">Controls the tone of generated resume content and cover letters.</span>
              </div>

              <div className="form-group">
                <label className="form-label">Target Resume Pages</label>
                <div className="settings-radio-group">
                  {PAGE_OPTIONS.map((opt) => (
                    <label key={opt.value} className={`settings-radio ${targetPages === opt.value ? 'active' : ''}`}>
                      <input
                        type="radio"
                        name="target_pages"
                        value={opt.value}
                        checked={targetPages === opt.value}
                        onChange={() => setTargetPages(opt.value)}
                      />
                      <span>{opt.label}</span>
                    </label>
                  ))}
                </div>
                <span className="form-hint">Senior roles may benefit from a second page.</span>
              </div>

              <div className="form-group">
                <label className="setting-option">
                  <input
                    type="checkbox"
                    checked={aggressiveAtsDefault}
                    onChange={(event) => setAggressiveAtsDefault(event.target.checked)}
                  />
                  <div className="setting-option-content">
                    <strong>Default to Aggressive ATS Mode</strong>
                    <span>Preselect user-approved keyword expansion for new resumes.</span>
                  </div>
                </label>
              </div>

              {error && <div className="text-error" style={{ fontSize: '0.85rem', marginBottom: 'var(--space-md)' }}>{error}</div>}
              {success && <div className="text-success" style={{ fontSize: '0.85rem', marginBottom: 'var(--space-md)' }}>{success}</div>}

              <button
                className="btn btn-primary"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? 'Saving...' : 'Save Preferences'}
              </button>
            </div>
          </AppCard>

          <AppCard title="Account">
            <div className="settings-account-info">
              <div className="settings-info-row">
                <span className="settings-info-label">Email</span>
                <span className="settings-info-value">{email || 'Not available'}</span>
              </div>
              <div className="settings-info-row">
                <span className="settings-info-label">User ID</span>
                <span className="settings-info-value" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                  {user?.id?.slice(0, 12)}...
                </span>
              </div>
              <div className="settings-info-row">
                <span className="settings-info-label">Signed in</span>
                <span className="settings-info-value">Google</span>
              </div>
            </div>
            <button
              className="btn btn-danger"
              onClick={handleLogout}
              disabled={authLoading}
              style={{ marginTop: 'var(--space-md)', width: '100%' }}
            >
              {authLoading ? 'Signing out...' : 'Log out'}
            </button>
          </AppCard>

          <AppCard title="About">
            <div className="settings-about-info">
              <div className="settings-info-row">
                <span className="settings-info-label">Application</span>
                <span className="settings-info-value">{appConfig.appName}</span>
              </div>
              <div className="settings-info-row">
                <span className="settings-info-label">Version</span>
                <span className="settings-info-value">{appConfig.appVersion}</span>
              </div>
              <div className="settings-info-row">
                <span className="settings-info-label">Environment</span>
                <span className="settings-info-value">
                  <span className={`badge badge-${appConfig.isProduction ? 'info' : 'neutral'}`}>
                    {appConfig.appEnv}
                  </span>
                </span>
              </div>
              <div className="settings-info-row">
                <span className="settings-info-label">API Base URL</span>
                <span className="settings-info-value" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                  {appConfig.apiBase}
                </span>
              </div>
              <div className="settings-info-row">
                <span className="settings-info-label">Supabase</span>
                <span className="settings-info-value">
                  <span className={`badge badge-${appConfig.supabaseConfigured ? 'success' : 'warning'}`}>
                    {appConfig.supabaseConfigured ? 'Configured' : 'Not configured'}
                  </span>
                </span>
              </div>
              {appConfig.buildTime && (
                <div className="settings-info-row">
                  <span className="settings-info-label">Build Time</span>
                  <span className="settings-info-value">{appConfig.buildTime}</span>
                </div>
              )}
              {appConfig.commitSha && (
                <div className="settings-info-row">
                  <span className="settings-info-label">Commit</span>
                  <span className="settings-info-value" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                    {appConfig.commitSha.slice(0, 7)}
                  </span>
                </div>
              )}
              <div className="settings-summary-line">
                {formatEnvironmentLabel()}
              </div>
            </div>
          </AppCard>
        </div>
      )}
    </div>
  );
}
