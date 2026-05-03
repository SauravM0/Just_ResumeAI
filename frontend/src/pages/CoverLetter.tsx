/**
 * Cover Letter page — generate and view a tailored cover letter.
 */

import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { generateCoverLetter } from '../lib/api';
import { getDefaultProfile } from '../lib/db';
import { sanitizeProfile } from '../lib/profile';
import { useAppStore } from '../store/useAppStore';
import type { MasterProfile } from '../types/profile';

function hasSavedProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

export default function CoverLetter() {
  const navigate = useNavigate();
  const { sessionId, activeProfile, setActiveProfile, parsedJD, recommendation, setStep } = useAppStore();

  const [tone, setTone] = useState('Professional');
  const [additionalContext, setAdditionalContext] = useState('');
  const [coverLetterText, setCoverLetterText] = useState('');
  const [isCopied, setIsCopied] = useState(false);
  const [resolvedProfile, setResolvedProfile] = useState<MasterProfile | null>(activeProfile);
  const [isLoadingProfile, setIsLoadingProfile] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadProfile() {
      if (activeProfile) {
        setResolvedProfile(activeProfile);
        return;
      }

      setIsLoadingProfile(true);
      setProfileError(null);

      try {
        const saved = await getDefaultProfile();
        if (cancelled) return;

        if (!hasSavedProfile(saved)) {
          setResolvedProfile(null);
          setProfileError('No saved master profile found. Please save your profile first.');
          return;
        }

        const normalized = sanitizeProfile(saved);
        setResolvedProfile(normalized);
        setActiveProfile(normalized);
      } finally {
        if (!cancelled) setIsLoadingProfile(false);
      }
    }

    void loadProfile();

    return () => {
      cancelled = true;
    };
  }, [activeProfile, setActiveProfile]);

  const generateMutation = useMutation({
    mutationFn: generateCoverLetter,
    onSuccess: (data) => {
      setCoverLetterText(data.cover_letter_text);
      setIsCopied(false);
    },
  });

  const handleGenerate = () => {
    if (!sessionId || !resolvedProfile || !parsedJD || !recommendation) return;

    generateMutation.mutate({
      session_id: sessionId,
      profile: resolvedProfile,
      parsed_jd: parsedJD,
      recommendation,
      job_title: recommendation.target_title,
      tone,
      additional_context: additionalContext || undefined,
    });
  };

  const handleRegenerate = () => {
    handleGenerate();
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(coverLetterText);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  const handleGoToResume = () => {
    setStep('jd-input');
    navigate('/jd');
  };

  if (!sessionId || !parsedJD || !recommendation) {
    return (
      <div className="empty-state">
        <div className="empty-icon">✉️</div>
        <div className="empty-title">Resume session required</div>
        <div className="empty-description">
          Please generate and review a resume first before creating a cover letter.
        </div>
        <button className="btn btn-primary" onClick={handleGoToResume}>
          Generate Resume First
        </button>
      </div>
    );
  }

  if (isLoadingProfile) {
    return (
      <div className="loading-state">
        <div className="spinner spinner-lg" />
        <div className="loading-text">Loading your saved profile...</div>
      </div>
    );
  }

  if (profileError) {
    return (
      <div className="empty-state">
        <div className="empty-icon">👤</div>
        <div className="empty-title">Profile required</div>
        <div className="empty-description">{profileError}</div>
        <button className="btn btn-primary" onClick={() => navigate('/profile')}>
          Go to Profile
        </button>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <h1 className="page-title">Tailored Cover Letter</h1>
        <p className="page-subtitle">
          Generate a high-impact cover letter for {parsedJD?.company || 'the job'}.
        </p>
      </div>

      <div className="split-pane">
        <div className="split-pane-left">
          <div className="card">
            <h2 className="card-title" style={{ marginBottom: 'var(--space-md)' }}>Settings</h2>

            <div className="form-group">
              <label className="form-label">Tone</label>
              <select
                className="form-select"
                value={tone}
                onChange={(e) => setTone(e.target.value)}
                disabled={generateMutation.isPending}
              >
                <option>Professional</option>
                <option>Enthusiastic</option>
                <option>Concise</option>
                <option>Bold</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Additional Context</label>
              <textarea
                className="form-textarea"
                placeholder="Add specific points to mention, e.g., particular achievement or interest..."
                value={additionalContext}
                onChange={(e) => setAdditionalContext(e.target.value)}
                disabled={generateMutation.isPending}
                style={{ minHeight: 80 }}
              />
              <div className="form-hint">
                Optional: Add specific details to customize the letter
              </div>
            </div>

            <button
              className="btn btn-primary btn-lg"
              style={{ width: '100%', marginBottom: 'var(--space-sm)' }}
              onClick={handleGenerate}
              disabled={generateMutation.isPending || !resolvedProfile}
            >
              {generateMutation.isPending ? (
                <>
                  <span className="spinner" />
                  Generating...
                </>
              ) : (
                '✨ Generate Cover Letter'
              )}
            </button>

            {coverLetterText && (
              <button
                className="btn btn-secondary btn-lg"
                style={{ width: '100%' }}
                onClick={handleRegenerate}
                disabled={generateMutation.isPending}
              >
                🔄 Regenerate with new settings
              </button>
            )}

            {generateMutation.isError && (
              <div className="warning-banner warning-error" style={{ marginTop: 'var(--space-md)' }}>
                <span>❌</span>
                <span>{generateMutation.error instanceof Error ? generateMutation.error.message : 'Cover letter generation failed.'}</span>
              </div>
            )}
          </div>

          {recommendation && (
            <div className="card" style={{ marginTop: 'var(--space-md)' }}>
              <div className="card-title" style={{ marginBottom: 'var(--space-sm)' }}>Resume Info</div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                <div><strong>Target:</strong> {recommendation.target_title}</div>
                {parsedJD?.company && <div><strong>Company:</strong> {parsedJD.company}</div>}
              </div>
            </div>
          )}
        </div>

        <div className="split-pane-right">
          <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 400 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-md)' }}>
              <h2 className="card-title">Generated Letter</h2>
              {coverLetterText && (
                <button 
                  className={`btn btn-ghost btn-sm ${isCopied ? 'btn-success' : ''}`} 
                  onClick={handleCopy}
                >
                  {isCopied ? '✓ Copied!' : '📋 Copy'}
                </button>
              )}
            </div>

            <div
              className="code-editor"
              style={{
                flex: 1,
                backgroundColor: 'var(--bg-card-hover)',
                whiteSpace: 'pre-wrap',
                fontFamily: 'var(--font-sans)',
                fontSize: '0.95rem',
                padding: 'var(--space-md)',
                overflowY: 'auto',
              }}
            >
              {coverLetterText || (
                <div className="empty-state" style={{ padding: 'var(--space-xl)' }}>
                  <div className="empty-description">
                    Click generate to create a tailored cover letter based on your resume and the job description.
                  </div>
                </div>
              )}
            </div>

            {coverLetterText && (
              <div style={{ 
                marginTop: 'var(--space-sm)', 
                fontSize: '0.8rem', 
                color: 'var(--text-secondary)',
                textAlign: 'right'
              }}>
                {coverLetterText.split(/\s+/).length} words
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}