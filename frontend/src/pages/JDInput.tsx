/**
 * JD Input page — user pastes a job description, AI analyzes it.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { generateResumePipeline } from '../lib/api';
import { getDefaultProfile } from '../lib/db';
import { sanitizeProfile } from '../lib/profile';
import { useAppStore } from '../store/useAppStore';
import type { MasterProfile } from '../types/profile';

function hasSavedProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

export default function JDInput() {
  const navigate = useNavigate();
  const [rawJD, setRawJD] = useState('');
  const [blockingError, setBlockingError] = useState<string | null>(null);
  const {
    setSessionId,
    setParsedJD,
    setRecommendation,
    setAtsScore,
    setLatexSource,
    setEligibility,
    setPipelinePdf,
    setStep,
    addWarning,
    clearWarnings,
    setActiveProfile,
  } = useAppStore();

  const pipelineMutation = useMutation({
    mutationFn: generateResumePipeline,
    onSuccess: (data) => {
      setSessionId(data.session_id);
      setParsedJD(data.parsed_jd);
      setRecommendation(data.recommendation);
      setAtsScore(data.ats_score);
      setLatexSource(data.latex_source);
      setEligibility(data.eligibility);
      setPipelinePdf(data.pdf);
      data.warnings.forEach(addWarning);
      setStep('resume-review');
      navigate('/review');
    },
  });

  const handleAnalyze = async () => {
    if (rawJD.trim().length < 50) return;
    const savedProfile = await getDefaultProfile();
    if (!hasSavedProfile(savedProfile)) {
      setActiveProfile(null);
      setBlockingError('No saved master profile found. Please save your profile before analyzing a job description.');
      return;
    }

    const normalizedProfile = sanitizeProfile(savedProfile);
    setActiveProfile(normalizedProfile);
    setBlockingError(null);
    clearWarnings();
    pipelineMutation.mutate({
      profile: normalizedProfile,
      raw_jd_text: rawJD,
      target_pages: 1,
      allow_two_pages_for_senior: true,
      generate_pdf: false,
    });
  };

  const charCount = rawJD.length;
  const isValid = charCount >= 50;

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <h1 className="page-title">Paste Job Description</h1>
        <p className="page-subtitle">
          Paste the full job description. Our AI will extract requirements, keywords, and scoring criteria.
        </p>
      </div>

      {/* Pipeline indicator */}
      <div className="pipeline-steps" style={{ marginBottom: 'var(--space-xl)' }}>
        <div className="pipeline-step step-done"><span>✓</span><span>Profile</span></div>
        <div className="pipeline-connector" />
        <div className="pipeline-step step-active"><span>📋</span><span>Paste JD</span></div>
        <div className="pipeline-connector" />
        <div className="pipeline-step"><span>🔍</span><span>Analysis</span></div>
        <div className="pipeline-connector" />
        <div className="pipeline-step"><span>👁️</span><span>Review</span></div>
        <div className="pipeline-connector" />
        <div className="pipeline-step"><span>📥</span><span>Export</span></div>
      </div>

      <div className="card">
        <div className="form-group">
          <label className="form-label">Job Description Text</label>
          <textarea
            className="form-textarea"
            value={rawJD}
            onChange={(e) => setRawJD(e.target.value)}
            placeholder={`Paste the full job description here...\n\nInclude:\n- Job title and company\n- Requirements and qualifications\n- Responsibilities\n- Preferred skills\n- Experience requirements`}
            style={{ minHeight: '350px', fontFamily: 'var(--font-sans)' }}
            disabled={pipelineMutation.isPending}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span className="form-hint">
              {charCount < 50
                ? `Minimum 50 characters required (${50 - charCount} more needed)`
                : `${charCount.toLocaleString()} characters`}
            </span>
            {charCount > 12000 && (
              <span className="badge badge-warning">Very long JD — analysis may take longer</span>
            )}
          </div>
        </div>

        {pipelineMutation.isPending && (
          <div className="card" style={{ marginBottom: 'var(--space-md)' }}>
            <div className="card-title" style={{ marginBottom: 'var(--space-sm)' }}>Generating Resume</div>
            <div className="pipeline-steps">
              {['Analyze JD', 'Check fit', 'Create resume', 'Score ATS', 'Render LaTeX'].map((label, index) => (
                <div key={label} className={`pipeline-step ${index === 0 ? 'step-active' : ''}`}>
                  <span>{index === 0 ? <span className="spinner" /> : index + 1}</span>
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {pipelineMutation.isError && (
          <div className="warning-banner warning-error" style={{ marginBottom: 'var(--space-md)' }}>
            <span>❌</span>
            <div>
              <strong>Resume Generation Failed</strong>
              <p style={{ margin: 0, marginTop: '4px', fontSize: '0.8rem' }}>
                {(pipelineMutation.error as Error).message || 'Something went wrong. Please try again.'}
              </p>
            </div>
          </div>
        )}

        {blockingError && (
          <div className="warning-banner warning-error" style={{ marginBottom: 'var(--space-md)' }}>
            <span>❌</span>
            <div>
              <strong>Profile Required</strong>
              <p style={{ margin: 0, marginTop: '4px', fontSize: '0.8rem' }}>
                {blockingError}
              </p>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: 'var(--space-md)', justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={() => setRawJD('')} disabled={!rawJD || pipelineMutation.isPending}>
            Clear
          </button>
          <button
            className="btn btn-primary btn-lg"
            onClick={handleAnalyze}
            disabled={!isValid || pipelineMutation.isPending}
          >
            {pipelineMutation.isPending ? (
              <>
                <span className="spinner" />
                Creating resume...
              </>
            ) : (
              'Analyze JD & Create Resume'
            )}
          </button>
        </div>
      </div>

      {/* Tips */}
      <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
        <div className="card-title" style={{ marginBottom: 'var(--space-md)' }}>💡 Tips for Best Results</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 'var(--space-md)' }}>
          {[
            { icon: '✅', text: 'Include the complete job posting — title, requirements, and responsibilities' },
            { icon: '✅', text: 'Keep formatting — bullet points and sections help our AI understand structure' },
            { icon: '⚠️', text: 'Vague JDs like "looking for a team player" will get quality warnings' },
            { icon: '❌', text: 'Don\'t paste just a job title — we need the full description' },
          ].map((tip, i) => (
            <div key={i} style={{ display: 'flex', gap: 'var(--space-sm)', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <span>{tip.icon}</span>
              <span>{tip.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
