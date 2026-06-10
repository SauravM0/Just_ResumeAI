import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { analyzeJD, generateResumePipeline } from '../lib/api';
import { getMyProfile } from '../lib/profileApi';
import { sanitizeProfile } from '../lib/profile';
import { useAppStore } from '../store/useAppStore';
import PageHeader from '../components/ui/PageHeader';
import PrimaryActionBar from '../components/ui/PrimaryActionBar';
import FlowStepper from '../components/ui/FlowStepper';
import type { FlowStep } from '../components/ui/FlowStepper';
import type { MasterProfile } from '../types/profile';
import type { JDAnalyzeResponse, JDKeyword, ParsedJD } from '../types/jd';

function hasSavedProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

const RESUME_FLOW_STEPS: FlowStep[] = [
  { id: 'profile', label: 'Profile', shortLabel: 'Profile', icon: '👤' },
  { id: 'jd', label: 'Job Description', shortLabel: 'JD', icon: '📋' },
  { id: 'settings', label: 'Settings', shortLabel: 'Settings', icon: '⚙' },
  { id: 'generate', label: 'Generate', shortLabel: 'Generate', icon: '✨' },
  { id: 'review', label: 'Review & Export', shortLabel: 'Review', icon: '📄' },
];

export default function JDInput() {
  const navigate = useNavigate();
  const [rawJD, setRawJD] = useState('');
  const [blockingError, setBlockingError] = useState<string | null>(null);
  const [targetPages, setTargetPages] = useState(1);
  const [generatePdfAfterReview, setGeneratePdfAfterReview] = useState(false);
  const [jdAnalysis, setJdAnalysis] = useState<JDAnalyzeResponse | null>(null);
  const [analyzeLoading, setAnalyzeLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const {
    setGenerationId,
    setParsedJD,
    setPipelineWarnings,
    setRecommendation,
    setAtsScore,
    setAlignmentReport,
    setLatexSource,
    setPipelinePdf,
    setValidationStatus,
    setStep,
    setActiveProfile,
  } = useAppStore();

  const pipelineMutation = useMutation({
    mutationFn: generateResumePipeline,
    onSuccess: (data) => {
      setGenerationId(data.generation_id);
      setParsedJD(data.parsed_jd);
      setPipelineWarnings(data.warnings ?? data.parsed_jd.quality_warnings ?? []);
      setRecommendation(data.recommendation);
      setAtsScore(data.ats_score);
      setAlignmentReport(data.alignment_report);
      setLatexSource(data.latex_source);
      setPipelinePdf(data.pdf);
      if (data.validation_status) {
        setValidationStatus(data.validation_status);
      }
      setStep('resume-review');
      navigate(`/review/${data.generation_id}`);
    },
  });

  const handleAnalyzeJD = async () => {
    if (rawJD.trim().length < 100) return null;
    setAnalyzeLoading(true);
    setAnalysisError(null);
    try {
      const analysis = await analyzeJD({ raw_jd_text: rawJD });
      setJdAnalysis(analysis);
      return analysis;
    } catch (error) {
      setAnalysisError(error instanceof Error ? error.message : 'Unable to analyse this job description.');
      return null;
    } finally {
      setAnalyzeLoading(false);
    }
  };

  useEffect(() => {
    setJdAnalysis(null);
    setAnalysisError(null);
    if (rawJD.trim().length <= 200) return;
    const timer = window.setTimeout(() => {
      void handleAnalyzeJD();
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [rawJD]);

  const matchPreview = useMemo(
    () => jdAnalysis?.parsed_jd ? calculateMatchPreview(useAppStore.getState().activeProfile, jdAnalysis.parsed_jd) : { covered: 0, total: 0, percent: 0 },
    [jdAnalysis],
  );

  const handleGenerate = async () => {
    if (rawJD.trim().length < 50) return;
    if (!jdAnalysis) {
      await handleAnalyzeJD();
      return;
    }
    try {
      const savedProfile = (await getMyProfile()).profile_json;
      if (!hasSavedProfile(savedProfile)) {
        setActiveProfile(null);
        setBlockingError('Your profile needs a name before we can generate a resume. Please update your profile first.');
        return;
      }

      const normalizedProfile = sanitizeProfile(savedProfile);
      setActiveProfile(normalizedProfile);
      setBlockingError(null);
      pipelineMutation.mutate({
        profile: normalizedProfile,
        raw_jd_text: rawJD,
        target_pages: targetPages,
        allow_two_pages_for_senior: targetPages === 2,
        generate_pdf: generatePdfAfterReview,
        additional_alignment_text: undefined,
      });
    } catch (error) {
      setBlockingError(error instanceof Error ? error.message : 'Unable to load your master profile.');
    }
  };

  const charCount = rawJD.length;
  const isValid = charCount >= 50;
  const isLongJD = charCount > 12000;
  const canGenerate = isValid && Boolean(jdAnalysis) && !analyzeLoading;

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Create Your Resume"
        subtitle="Follow the steps below to generate an ATS-optimized resume tailored to a specific job."
      />

      {/* Guided flow stepper */}
      <FlowStepper steps={RESUME_FLOW_STEPS} currentStep={1} completedSteps={[0]} />

      {/* Step 2: Paste Job Description */}
      <div className="card">
        <div className="card-title" style={{ marginBottom: 'var(--space-xs)' }}>
          Step 2: Paste the Job Description
        </div>
        <p className="card-subtitle" style={{ marginBottom: 'var(--space-md)' }}>
          Paste the full job posting below. The more detail you include, the better your resume will match.
        </p>

        <div className="form-group">
          <label className="form-label" htmlFor="jd-textarea">Job Description</label>
          <textarea
            id="jd-textarea"
            className="form-textarea"
            value={rawJD}
            onChange={(e) => setRawJD(e.target.value)}
            placeholder={`Paste the complete job description here...\n\nTip: Include the job title, company, responsibilities, required skills, and qualifications.`}
            style={{ minHeight: '250px', fontFamily: 'var(--font-sans)' }}
            disabled={pipelineMutation.isPending}
            aria-describedby="jd-hint"
          />
          <div id="jd-hint" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-xs)' }}>
            <span className={`form-hint ${!isValid ? 'text-warning' : ''}`}>
              {charCount === 0
                ? 'Paste a job description to get started'
                : charCount < 50
                ? `${50 - charCount} more characters needed`
                : `${charCount.toLocaleString()} characters — looks good`}
            </span>
            {isLongJD && (
              <span className="badge badge-warning">Long JD — may take a moment</span>
            )}
          </div>
        </div>

        <div className="form-hint" style={{ marginTop: 'calc(-1 * var(--space-sm))', marginBottom: 'var(--space-md)', textAlign: 'right' }}>
          {charCount.toLocaleString()} / 15,000 characters
        </div>

        {(analyzeLoading || jdAnalysis || analysisError) && (
          <JDAnalysisPanel
            analysis={jdAnalysis}
            loading={analyzeLoading}
            error={analysisError}
            matchPreview={matchPreview}
            onRetry={handleAnalyzeJD}
          />
        )}

        {/* Step 3: Page count + settings */}
        <div style={{ marginTop: 'var(--space-lg)' }}>
          <div className="card-title" style={{ marginBottom: 'var(--space-xs)' }}>
            Step 3: Resume Settings
          </div>
          <p className="card-subtitle" style={{ marginBottom: 'var(--space-md)' }}>
            Choose your preferred resume length and options.
          </p>

          <div className="form-group">
            <label className="form-label">Resume Length</label>
            <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
              <label
                className={`compact-setting ${targetPages === 1 ? '' : ''}`}
                style={{
                  borderColor: targetPages === 1 ? 'var(--border-accent)' : undefined,
                  background: targetPages === 1 ? 'var(--accent-gradient-soft)' : undefined,
                  color: targetPages === 1 ? 'var(--text-accent)' : undefined,
                }}
              >
                <input
                  type="radio"
                  name="targetPages"
                  checked={targetPages === 1}
                  onChange={() => setTargetPages(1)}
                  disabled={pipelineMutation.isPending}
                />
                <span>1 page — Standard</span>
              </label>
              <label
                className="compact-setting"
                style={{
                  borderColor: targetPages === 2 ? 'var(--border-accent)' : undefined,
                  background: targetPages === 2 ? 'var(--accent-gradient-soft)' : undefined,
                  color: targetPages === 2 ? 'var(--text-accent)' : undefined,
                }}
              >
                <input
                  type="radio"
                  name="targetPages"
                  checked={targetPages === 2}
                  onChange={() => setTargetPages(2)}
                  disabled={pipelineMutation.isPending}
                />
                <span>2 pages — Senior roles</span>
              </label>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Options</label>
            <label className="compact-setting">
              <input
                type="checkbox"
                checked={generatePdfAfterReview}
                onChange={(e) => setGeneratePdfAfterReview(e.target.checked)}
                disabled={pipelineMutation.isPending}
              />
              <span>Compile PDF after review</span>
            </label>
          </div>
        </div>

        {/* Generation status */}
        {pipelineMutation.isPending && (
          <div className="generation-status" style={{ marginTop: 'var(--space-lg)' }}>
            <span className="spinner" />
            <div>
              <strong>Generating your tailored resume...</strong>
              <p>Analyzing the job description → Writing your resume → Scoring ATS match</p>
            </div>
          </div>
        )}

        {pipelineMutation.isError && (
          <div className="warning-banner warning-error" style={{ marginTop: 'var(--space-lg)' }}>
            <span>⚠️</span>
            <div>
              <strong>Generation failed</strong>
              <p style={{ margin: 0, marginTop: '4px', fontSize: '0.8rem' }}>
                {(pipelineMutation.error as Error).message || 'Something went wrong. Please try again.'}
              </p>
            </div>
          </div>
        )}

        {blockingError && (
          <div className="warning-banner warning-error" style={{ marginTop: 'var(--space-lg)' }}>
            <span>⚠️</span>
            <div>
              <strong>Profile needed</strong>
              <p style={{ margin: 0, marginTop: '4px', fontSize: '0.8rem' }}>
                {blockingError}
              </p>
            </div>
          </div>
        )}

        {/* Step 4: Generate */}
        <PrimaryActionBar>
          <div style={{ display: 'flex', gap: 'var(--space-sm)', width: '100%', justifyContent: 'flex-end' }}>
            <button className="btn btn-ghost" onClick={() => setRawJD('')} disabled={!rawJD || pipelineMutation.isPending}>
              Clear
            </button>
            <button
              className="btn btn-primary btn-lg"
              onClick={handleGenerate}
              disabled={!canGenerate || pipelineMutation.isPending}
            >
              {pipelineMutation.isPending ? (
                <>
                  <span className="spinner" />
                  Generating...
                </>
              ) : (
                <>
                  <span>✨</span>
                  Generate optimised resume
                </>
              )}
            </button>
          </div>
        </PrimaryActionBar>
      </div>

      {/* Tips card */}
      <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
        <div className="card-title" style={{ marginBottom: 'var(--space-md)' }}>💡 Tips for the best results</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 'var(--space-md)' }}>
          {[
            { icon: '📋', text: 'Paste the complete job description — including responsibilities, required skills, and qualifications.' },
            { icon: '🎯', text: 'The AI matches your profile against the JD keywords to create a tailored resume.' },
            { icon: '📄', text: 'Choose 1 page for most roles, 2 pages for senior positions with 10+ years of experience.' },
          ].map((tip, i) => (
            <div key={i} style={{ display: 'flex', gap: 'var(--space-sm)', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              <span style={{ flexShrink: 0, fontSize: '1.1rem' }}>{tip.icon}</span>
              <span>{tip.text}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function JDAnalysisPanel({
  analysis,
  loading,
  error,
  matchPreview,
  onRetry,
}: {
  analysis: JDAnalyzeResponse | null;
  loading: boolean;
  error: string | null;
  matchPreview: { covered: number; total: number; percent: number };
  onRetry: () => Promise<JDAnalyzeResponse | null>;
}) {
  if (loading) {
    return (
      <section className="jd-analysis-panel">
        <div className="skeleton-line" />
        <div className="skeleton-line short" />
        <div className="jd-chip-row">
          {Array.from({ length: 8 }).map((_, index) => <span className="jd-chip-skeleton" key={index} />)}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="warning-banner warning-error" style={{ marginTop: 'var(--space-lg)' }}>
        <div>
          <strong>JD analysis failed</strong>
          <p style={{ margin: '4px 0 0', fontSize: '0.8rem' }}>{error}</p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={() => void onRetry()}>Retry</button>
      </section>
    );
  }

  if (!analysis) return null;

  const jd = analysis.parsed_jd;
  const critical = jd.keywords.filter((keyword) => keyword.importance === 'critical').slice(0, 8);
  const high = jd.keywords.filter((keyword) => keyword.importance === 'high').slice(0, 8);
  const medium = jd.keywords.filter((keyword) => keyword.importance === 'medium' || keyword.importance === 'low').slice(0, 6);
  const mustHave = jd.requirements.filter((req) => req.is_required).slice(0, 5);
  const niceToHave = jd.requirements.filter((req) => !req.is_required).slice(0, 5);
  const matchTone = matchPreview.percent >= 70 ? 'success' : matchPreview.percent >= 50 ? 'warning' : 'danger';

  return (
    <section className="jd-analysis-panel">
      <div className="jd-analysis-head">
        <div>
          <h3>Detected: {jd.job_title || 'Role'}{jd.company ? ` at ${jd.company}` : ''}</h3>
          <p>{formatSeniority(jd.seniority)} level{jd.location ? ` | ${jd.location}` : ''}</p>
        </div>
        <span className="badge badge-info">{jd.keywords.length} keywords detected</span>
      </div>

      <div className="jd-chip-row">
        <span className="badge badge-info">{jd.job_title || 'Role detected'}</span>
        <span className="badge badge-info">{formatSeniority(jd.seniority)}</span>
        {jd.location && <span className="badge badge-info">{jd.location}</span>}
      </div>

      <KeywordGroup title="Critical" keywords={critical} tone="critical" />
      <KeywordGroup title="High importance" keywords={high} tone="high" />
      <KeywordGroup title="Good to have" keywords={medium} tone="medium" />

      <div className="jd-requirements-grid">
        <RequirementList title="Must-have" items={mustHave.map((req) => req.text)} />
        <details className="jd-requirement-card">
          <summary>Nice-to-have</summary>
          <ul>{niceToHave.map((req) => <li key={req.text}>{req.text}</li>)}</ul>
        </details>
      </div>

      <div className="jd-match-preview">
        <div>
          <strong>Your profile covers {matchPreview.covered} of {matchPreview.total} critical requirements</strong>
          <div className="jd-progress-track">
            <span className={`jd-progress-fill ${matchTone}`} style={{ width: `${matchPreview.percent}%` }} />
          </div>
        </div>
        <span className={`badge badge-${matchTone}`}>{matchPreview.percent}%</span>
      </div>
    </section>
  );
}

function KeywordGroup({ title, keywords, tone }: { title: string; keywords: JDKeyword[]; tone: string }) {
  if (keywords.length === 0) return null;
  return (
    <div className="jd-keyword-group">
      <h4>{title}</h4>
      <div className="jd-chip-row">
        {keywords.map((keyword) => (
          <span className={`jd-keyword-chip ${tone}`} key={`${tone}-${keyword.keyword}`}>{keyword.keyword}</span>
        ))}
      </div>
    </div>
  );
}

function RequirementList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="jd-requirement-card">
      <h4>{title}</h4>
      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </div>
  );
}

function calculateMatchPreview(profile: MasterProfile | null, jd: ParsedJD) {
  const requirements = jd.requirements.filter((req) => req.is_required);
  const haystack = profile ? JSON.stringify(profile).toLowerCase() : '';
  const covered = requirements.filter((req) => req.text.toLowerCase().split(/\W+/).some((word) => word.length > 3 && haystack.includes(word))).length;
  const total = requirements.length;
  return { covered, total, percent: total ? Math.round((covered / total) * 100) : 0 };
}

function formatSeniority(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}
