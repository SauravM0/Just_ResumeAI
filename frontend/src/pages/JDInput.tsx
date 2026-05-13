/**
 * JD Input page — user pastes a job description, AI analyzes it.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { generateResumePipeline } from '../lib/api';
import { getDefaultProfile, saveRecentResumeSnapshot } from '../lib/db';
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
  const [strictOnePage, setStrictOnePage] = useState(true);
  const [generatePdfAfterReview, setGeneratePdfAfterReview] = useState(false);
  const {
    setSessionId,
    setParsedJD,
    setRecommendation,
    setAtsScore,
    setAlignmentReport,
    setLatexSource,
    setPipelinePdf,
    setStep,
    setActiveProfile,
  } = useAppStore();

  const pipelineMutation = useMutation({
    mutationFn: generateResumePipeline,
    onSuccess: (data) => {
      void saveRecentResumeSnapshot({
        sessionId: data.session_id,
        parsedJD: data.parsed_jd,
        recommendation: data.recommendation,
        atsScore: data.ats_score,
        pipelinePdf: data.pdf,
      });
      setSessionId(data.session_id);
      setParsedJD(data.parsed_jd);
      setRecommendation(data.recommendation);
      setAtsScore(data.ats_score);
      setAlignmentReport(data.alignment_report);
      setLatexSource(data.latex_source);
      setPipelinePdf(data.pdf);
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
    pipelineMutation.mutate({
      profile: normalizedProfile,
      raw_jd_text: rawJD,
      target_pages: 1,
      allow_two_pages_for_senior: !strictOnePage,
      generate_pdf: generatePdfAfterReview,
      additional_alignment_text: undefined,
    });
  };

  const charCount = rawJD.length;
  const isValid = charCount >= 50;

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <h1 className="page-title">Paste JD & Generate One-Page Resume</h1>
        <p className="page-subtitle">
          Paste the job description and generate a tailored resume for review.
        </p>
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

        <div className="compact-settings" aria-label="Resume generation settings">
          <label className="compact-setting">
            <input
              type="checkbox"
              checked={strictOnePage}
              onChange={(e) => setStrictOnePage(e.target.checked)}
              disabled={pipelineMutation.isPending}
            />
            <span>Strict one-page resume</span>
          </label>
          <label className="compact-setting">
            <input
              type="checkbox"
              checked={generatePdfAfterReview}
              onChange={(e) => setGeneratePdfAfterReview(e.target.checked)}
              disabled={pipelineMutation.isPending}
            />
            <span>Generate PDF after review</span>
          </label>
          <label className="compact-setting compact-setting-disabled">
            <input type="checkbox" disabled />
            <span>Cover letter after resume</span>
            <span className="badge badge-neutral">Later</span>
          </label>
        </div>

        {pipelineMutation.isPending && (
          <div className="generation-status" style={{ marginBottom: 'var(--space-md)' }}>
            <span className="spinner" />
            <div>
              <strong>Generating ATS resume...</strong>
              <p>Analyzing JD → Optimizing keywords → Writing resume → Scoring match</p>
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
                Generating ATS resume...
              </>
            ) : (
              'Generate One-Page ATS Resume'
            )}
          </button>
        </div>
      </div>

      <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
        <div className="card-title" style={{ marginBottom: 'var(--space-md)' }}>Tips for Best Results</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 'var(--space-md)' }}>
          {[
            'Paste complete JD for best keyword extraction.',
            'Include responsibilities and required skills.',
          ].map((tip, i) => (
            <div key={i} style={{ display: 'flex', gap: 'var(--space-sm)', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <span>✓</span>
              <span>{tip}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
