import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import ATSCompactScoreCard from '../components/ATSCompactScoreCard';
import ATSScoreBreakdown from '../components/ui/ATSScoreBreakdown';
import LowScoreCTA from '../components/ui/LowScoreCTA';
import ATSFeedbackCard from '../components/ui/ATSFeedbackCard';
import ExportSuccessCard from '../components/ui/ExportSuccessCard';
import ExportReadinessCard from '../components/ui/ExportReadinessCard';
import ValidationStatusCard from '../components/ui/ValidationStatusCard';
import FlowStepper from '../components/ui/FlowStepper';
import JDProcessingNotes from '../components/ui/JDProcessingNotes';
import { RecruiterScoreCard } from '../components/ui/RecruiterScoreCard';
import { ScoreHistoryChart } from '../components/ui/ScoreHistoryChart';
import type { FlowStep } from '../components/ui/FlowStepper';
import ResumeVisualEditor from '../components/resume-editor/ResumeVisualEditor';
import { validateResume, getGeneration, exportPdf, exportDocx, confirmResumeKeywords, generateFastResume } from '../lib/api';
import { getMyProfile } from '../lib/profileApi';
import { sanitizeProfile } from '../lib/profile';
import { recommendationToPlainText } from '../lib/resumeText';
import { useAppStore } from '../store/useAppStore';
// Query key references for future TanStack Query migration:
//   QUERY_KEYS.generation(generationId)
//   CACHE_CONFIG.generation (staleTime: Infinity)
import type { ATSScore, ExportFileResponse, FastResumeGenerateResponse, KeywordConfirmationLevel, ValidationStatus } from '../types/resume';
import type { MasterProfile } from '../types/profile';

const logger = console;

const REVIEW_FLOW_STEPS: FlowStep[] = [
  { id: 'profile', label: 'Profile', icon: '👤' },
  { id: 'jd', label: 'Job Description', icon: '📋' },
  { id: 'settings', label: 'Settings', icon: '⚙' },
  { id: 'generate', label: 'Generate', icon: '✨' },
  { id: 'review', label: 'Review & Export', icon: '📄' },
];

function hasSavedProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

function downloadExport(file: ExportFileResponse) {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = file.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function validationErrorLines(message: string): string[] {
  return message
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
}

function fastResponseToAtsScore(data: FastResumeGenerateResponse): ATSScore {
  const total = data.extracted_keywords.length;
  const matched = data.matched_keywords.length;
  const coverage = total > 0 ? Math.round((matched / total) * 100) : 0;
  return {
    overall_score: data.ats_score,
    keyword_score: {
      total_keywords: total,
      matched_keywords: matched,
      coverage_percent: coverage,
      critical_missing: data.missing_keywords,
      details: data.extracted_keywords.map((keyword) => ({
        keyword,
        found: data.matched_keywords.includes(keyword),
        location: data.matched_keywords.includes(keyword) ? 'resume_json' : 'missing',
      })),
    },
    skill_score: {
      required_total: total,
      required_matched: matched,
      required_coverage_percent: coverage,
      preferred_total: 0,
      preferred_matched: 0,
      preferred_coverage_percent: 0,
    },
    readability_score: { score: 80, avg_bullet_length: 0, issues: [] },
    format_score: 80,
    section_score: {
      score: 80,
      missing_sections: [],
      has_contact: true,
      has_summary: true,
      has_experience: true,
      has_skills: true,
      has_education: true,
    },
    responsibility_score: 70,
    title_alignment_score: 70,
    missing_keywords: data.missing_keywords,
    matched_supported_keywords: data.matched_keywords,
    unsupported_jd_keywords: data.missing_keywords,
    learning_focus_keywords: data.confirmed_keywords.filter((item) => item.level === 'learning').map((item) => item.keyword),
    warnings: [],
    recommendations: [],
  };
}

function uniqueKeywords(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  values.forEach((value) => {
    const cleaned = value.trim();
    const key = cleaned.toLowerCase();
    if (cleaned && !seen.has(key)) {
      seen.add(key);
      result.push(cleaned);
    }
  });
  return result;
}

export default function ResumeReview() {
  const navigate = useNavigate();
  const { generationId } = useParams<{ generationId: string }>();
  const {
    generationId: activeGenerationId,
    parsedJD,
    pipelineWarnings,
    recommendation,
    setRecommendation,
    atsScore,
    setAtsScore,
    alignmentReport,
    setPipelinePdf,
    setStep,
    activeProfile,
    setActiveProfile,
    setAlignmentReport,
    resetJobGeneration,
    setGenerationId,
    setParsedJD,
    validationStatus: storedValidationStatus,
    setValidationStatus: setStoredValidationStatus,
    recruiterReview,
    setRecruiterReview,
    scoreHistory,
    setScoreHistory,
    strategyHistory,
    setStrategyHistory,
  } = useAppStore();

  const [resolvedProfile, setResolvedProfile] = useState<MasterProfile | null>(activeProfile);
  const [isCheckingProfile, setIsCheckingProfile] = useState(false);
  const [blockingError, setBlockingError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const [exportedPdf, setExportedPdf] = useState<ExportFileResponse | null>(null);
  const [exportedDocx, setExportedDocx] = useState<ExportFileResponse | null>(null);
  const [validationRepaired, setValidationRepaired] = useState(false);
  const [validationWarnings, setValidationWarnings] = useState<string[]>([]);
  const [validationStatus, setValidationStatus] = useState<ValidationStatus | null>(storedValidationStatus);
  const [keywordLevels, setKeywordLevels] = useState<Record<string, KeywordConfirmationLevel>>({});
  const [keywordConfirmStatus, setKeywordConfirmStatus] = useState<string | null>(null);

  const currentGenerationId = generationId || activeGenerationId;

  useEffect(() => {
    let cancelled = false;

    async function loadGeneration(): Promise<boolean> {
      if (generationId) {
        try {
          // Query key (for future TanStack Query migration):
          //   QUERY_KEYS.generation(generationId)
          // Cache: staleTime=CACHE_CONFIG.generation.staleTime (Infinity)
          const genData = await getGeneration(generationId);
          if (cancelled) return false;
          if (genData.parsed_jd_json) setParsedJD(genData.parsed_jd_json as any);
          if (genData.resume_json) setRecommendation(genData.resume_json as any);
          if (genData.ats_score_json) setAtsScore(genData.ats_score_json as any);
          if (genData.alignment_report_json) setAlignmentReport(genData.alignment_report_json as any);
          if (genData.recruiter_review) setRecruiterReview(genData.recruiter_review);
          if (genData.score_history) setScoreHistory(genData.score_history);
          if (genData.strategy_history) setStrategyHistory(genData.strategy_history);
          setGenerationId(generationId);
          return Boolean(genData.parsed_jd_json);
        } catch (e) {
          if (!cancelled) {
            logger.error('Failed to load generation:', e);
            setBlockingError('This resume is no longer available. Please generate a new one.');
          }
        }
      }
      return false;
    }

    async function resolveProfile() {
      const loadedParsedJD = generationId ? await loadGeneration() : false;

      if (!currentGenerationId) {
        setResolvedProfile(null);
        setBlockingError('No resume found. Please generate one first.');
        return;
      }

      if (!parsedJD && !loadedParsedJD) {
        setResolvedProfile(null);
        setBlockingError('Missing job description data. Please try generating again.');
        return;
      }

      if (activeProfile) {
        setResolvedProfile(activeProfile);
        return;
      }

      setIsCheckingProfile(true);
      setBlockingError(null);

      try {
        const savedProfile = (await getMyProfile()).profile_json;
        if (cancelled) return;

        if (!hasSavedProfile(savedProfile)) {
          setResolvedProfile(null);
          setActiveProfile(null);
          setBlockingError('No saved profile found. Please update your profile first.');
          return;
        }

        const normalizedProfile = sanitizeProfile(savedProfile);
        setResolvedProfile(normalizedProfile);
        setActiveProfile(normalizedProfile);
      } finally {
        if (!cancelled) setIsCheckingProfile(false);
      }
    }

    void resolveProfile();

    return () => {
      cancelled = true;
    };
  }, [generationId, activeGenerationId, activeProfile, parsedJD, setActiveProfile, setParsedJD, setRecommendation, setAtsScore, setAlignmentReport, setGenerationId, setRecruiterReview, setScoreHistory, setStrategyHistory]);

  const validateMutation = useMutation({
    mutationFn: validateResume,
    onSuccess: (data) => {
      setAtsScore(data.ats_score);
      if (data.validation_status) {
        setValidationStatus(data.validation_status);
        setStoredValidationStatus(data.validation_status);
      }
    },
  });

  const pdfExportMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: exportPdf,
    onSuccess: (data) => {
      setExportedPdf(data);
      downloadExport(data);
      setCopyStatus('PDF downloaded');
      setValidationRepaired(data.validation_repaired ?? false);
      setValidationWarnings(data.validation_warnings ?? []);
      window.setTimeout(() => setCopyStatus(null), 2000);
    },
    onError: (error) => {
      setRenderError(error instanceof Error ? error.message : 'PDF export failed.');
    },
  });

  const docxExportMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: exportDocx,
    onSuccess: (data) => {
      setExportedDocx(data);
      downloadExport(data);
      setCopyStatus('DOCX downloaded');
      setValidationRepaired(data.validation_repaired ?? false);
      setValidationWarnings(data.validation_warnings ?? []);
      window.setTimeout(() => setCopyStatus(null), 2000);
    },
    onError: (error) => {
      setRenderError(error instanceof Error ? error.message : 'DOCX export failed.');
    },
  });

  const improveWithConfirmedKeywordsMutation = useMutation({
    mutationFn: async () => {
      if (!currentGenerationId) throw new Error('No generation is available.');
      if (!resolvedProfile) throw new Error('A saved profile is required to improve this resume.');
      const keywords = Object.entries(keywordLevels).map(([keyword, level]) => ({ keyword, level }));
      await confirmResumeKeywords(currentGenerationId, { keywords });
      return generateFastResume({
        profile: resolvedProfile,
        source_generation_id: currentGenerationId,
        save_to_database: true,
      });
    },
    onSuccess: (data) => {
      setRecommendation(data.resume_json);
      setAtsScore(fastResponseToAtsScore(data));
      setGenerationId(data.generation_id);
      setValidationStatus(null);
      setStoredValidationStatus(null);
      setPipelinePdf(null);
      setRenderError(null);
      setExportedPdf(null);
      setExportedDocx(null);
      setKeywordConfirmStatus('Resume improved with confirmed skills');
      navigate(`/review/${data.generation_id}`, { replace: true });
      window.setTimeout(() => setKeywordConfirmStatus(null), 2500);
    },
    onError: (error) => {
      setKeywordConfirmStatus(error instanceof Error ? error.message : 'Could not improve resume with confirmed skills.');
    },
  });

  const handleCopyResume = () => {
    if (!recommendation) return;
    navigator.clipboard.writeText(recommendationToPlainText(recommendation));
    setCopyStatus('Copied to clipboard');
    window.setTimeout(() => setCopyStatus(null), 2000);
  };

  const handleShareScore = () => {
    const score = atsScore?.overall_score;
    if (score == null) return;
    const text = `My resume just scored ${Math.round(score)}/100 on ATS! Created with Just Resume.`;
    navigator.clipboard.writeText(text);
    setShareStatus('Score copied!');
    window.setTimeout(() => setShareStatus(null), 2000);
  };

  const handleShareResumeLink = () => {
    if (!currentGenerationId) return;
    const url = `${window.location.origin}/history/${currentGenerationId}`;
    navigator.clipboard.writeText(url);
    setShareStatus('Link copied!');
    window.setTimeout(() => setShareStatus(null), 2000);
  };

  const handleStorageExportPdf = () => {
    if (!currentGenerationId) return;
    setRenderError(null);
    pdfExportMutation.mutate(currentGenerationId);
  };

  const handleStorageExportDocx = () => {
    if (!currentGenerationId) return;
    setRenderError(null);
    docxExportMutation.mutate(currentGenerationId);
  };

  const handleVisualEditorSave = (updatedRecommendation: typeof recommendation) => {
    if (!updatedRecommendation || !currentGenerationId) return;
    setRecommendation(updatedRecommendation);
    setAtsScore(null);
    setPipelinePdf(null);
    setRenderError(null);
  };

  const handleNextJD = () => {
    resetJobGeneration();
    setStep('jd-input');
    navigate('/create-resume');
  };

  const handleCoverLetter = () => {
    if (currentGenerationId) navigate(`/cover-letter/${currentGenerationId}`);
  };

  const handleReOptimize = () => {
    // Navigate back to the creation wizard in user-approved aggressive ATS mode.
    resetJobGeneration();
    setStep('jd-input');
    navigate('/create-resume/advanced?ats=aggressive&target=100');
  };

  const handleFixSection = (section: string) => {
    // Scroll to the relevant editor section — the editor tabs handle this
    const editorElement = document.querySelector('.review-editor-section');
    if (editorElement) {
      editorElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
      // Focus the relevant tab after a brief delay for scroll to complete
      setTimeout(() => {
        const tabButtons = document.querySelectorAll('.editor-tab');
        tabButtons.forEach((btn) => {
          if (btn.textContent?.toLowerCase().includes(section)) {
            (btn as HTMLButtonElement).click();
          }
        });
      }, 400);
    }
  };

  if (blockingError) {
    return (
      <div className="empty-state">
        <div className="empty-icon">⚠️</div>
        <div className="empty-title">Cannot open resume</div>
        <div className="empty-description">{blockingError}</div>
        <div style={{ display: 'flex', gap: 'var(--space-md)', marginTop: 'var(--space-md)', flexWrap: 'wrap' }}>
          <button className="btn btn-secondary" onClick={() => navigate('/profile')}>Update Profile</button>
          <button className="btn btn-primary" onClick={handleNextJD}>Create New Resume</button>
        </div>
      </div>
    );
  }

  if (isCheckingProfile) {
    return (
      <div className="loading-state">
        <div className="spinner spinner-lg" />
        <div className="loading-text">Loading your resume...</div>
      </div>
    );
  }

  if (!recommendation) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📄</div>
        <div className="empty-title">No resume available</div>
        <div className="empty-description">
          Paste a job description to generate your first ATS-optimized resume.
        </div>
        <button className="btn btn-primary" onClick={handleNextJD}>Create Resume</button>
      </div>
    );
  }

  const overallScore = atsScore?.overall_score ?? null;
  const missingKeywords = uniqueKeywords([
    ...(atsScore?.keyword_score?.critical_missing ?? []),
    ...(atsScore?.missing_keywords ?? []),
  ]).slice(0, 20);
  const pageCount = exportedPdf?.page_count;
  const targetPages = 1;
  const exportBlocked = false;
  const jdWarnings = [
    ...pipelineWarnings,
    ...(parsedJD?.quality_warnings ?? []),
  ];

  return (
    <div className="animate-fade-in review-layout">
      {/* Flow stepper — shows user is on final step */}
      <FlowStepper steps={REVIEW_FLOW_STEPS} currentStep={4} completedSteps={[0, 1, 2, 3]} />

      {/* Page header */}
      <div className="page-header" style={{ marginBottom: 0 }}>
        <h1 className="page-title">Review Your Resume</h1>
        <p className="page-subtitle">
          Your resume has been generated and tailored to the job description. Review the ATS score, edit content, and export when ready.
        </p>
      </div>

      {/* ATSScoreBreakdown — detailed dimension scores, missing keywords */}
      <ATSScoreBreakdown
        atsScore={atsScore}
        originalScore={null}
        resumeVersionId={recommendation?.version_id}
      />

      {/* Recruiter Impact Score */}
      {recruiterReview && (
        <RecruiterScoreCard review={recruiterReview} />
      )}

      {/* Score History Chart */}
      {scoreHistory.length >= 2 && (
        <ScoreHistoryChart scoreHistory={scoreHistory} strategyHistory={strategyHistory} />
      )}

      {/* Low Score CTA — improvement suggestions */}
      <LowScoreCTA
        atsScore={atsScore}
        overallScore={overallScore}
        onReOptimize={handleReOptimize}
        onFixSection={handleFixSection}
      />

      {/* ATS Feedback Card — score, keywords, missing, status */}
      <ATSFeedbackCard
        atsScore={atsScore}
        targetPages={targetPages}
        resumeVersionId={recommendation?.version_id}
        pageCount={pageCount}
        finalPdfParseStatus={atsScore?.final_pdf_parse_status}
      />

      {missingKeywords.length > 0 && (
        <div className="card" style={{ borderLeft: '3px solid var(--status-warning)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-md)', flexWrap: 'wrap', marginBottom: 'var(--space-md)' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: '1rem' }}>Confirm Missing Keywords</h2>
              <p style={{ margin: '4px 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                Confirm only skills that are true. Unconfirmed skills will not be added as experience.
              </p>
            </div>
            {keywordConfirmStatus && (
              <span style={{ color: keywordConfirmStatus.includes('Could not') ? 'var(--status-danger)' : 'var(--status-success)', fontSize: '0.85rem' }}>
                {keywordConfirmStatus}
              </span>
            )}
          </div>

          <div style={{ display: 'grid', gap: '8px', marginBottom: 'var(--space-md)' }}>
            {missingKeywords.map((keyword) => (
              <div
                key={keyword}
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(120px, 1fr) minmax(160px, 220px)',
                  gap: 'var(--space-sm)',
                  alignItems: 'center',
                }}
              >
                <span className="keyword-tag keyword-missing" style={{ justifySelf: 'start' }}>{keyword}</span>
                <select
                  className="form-select"
                  value={keywordLevels[keyword] ?? 'no'}
                  onChange={(event) => {
                    const level = event.target.value as KeywordConfirmationLevel;
                    setKeywordLevels((current) => ({ ...current, [keyword]: level }));
                  }}
                  aria-label={`Confirmation level for ${keyword}`}
                >
                  <option value="no">No</option>
                  <option value="professional">Professional</option>
                  <option value="project">Project</option>
                  <option value="basic">Basic</option>
                  <option value="learning">Learning</option>
                </select>
              </div>
            ))}
          </div>

          <button
            className="btn btn-primary"
            onClick={() => improveWithConfirmedKeywordsMutation.mutate()}
            disabled={improveWithConfirmedKeywordsMutation.isPending || !currentGenerationId || !resolvedProfile}
          >
            {improveWithConfirmedKeywordsMutation.isPending ? <span className="spinner" style={{ width: 14, height: 14 }} /> : null}
            {improveWithConfirmedKeywordsMutation.isPending ? 'Improving...' : 'Improve Resume With Confirmed Skills'}
          </button>
        </div>
      )}

      {/* Validation Status Card — blocked or warning reasons from the gate */}
      <ValidationStatusCard
        status={validationStatus}
        exportError={renderError}
        onRetry={handleStorageExportPdf}
        onEditJD={handleNextJD}
        onEditProfile={() => navigate('/profile')}
        validating={pdfExportMutation.isPending}
      />

      <JDProcessingNotes warnings={jdWarnings} />

      {recommendation.warnings.some((warning) => warning.includes('title was adjusted to avoid unsupported seniority')) && (
        <div className="warning-banner warning-info">
          <span>i</span>
          <div>
            <strong>Title adjusted for credibility</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              JD seniority exceeds candidate evidence; title was adjusted to avoid unsupported seniority.
            </p>
          </div>
        </div>
      )}

      {/* Compact score card (for quick reference in action bar) */}
      <div
        className="action-bar"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-md)',
          flexWrap: 'wrap',
          padding: 'var(--space-md)',
          borderRadius: 'var(--radius-lg)',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        <ATSCompactScoreCard
          atsScore={atsScore}
          alignmentReport={alignmentReport}
          resumeVersionId={recommendation?.version_id}
          compact
        />

        <div className="action-bar-actions">
          {copyStatus && <span style={{ color: 'var(--status-success)', fontSize: '0.85rem' }}>{copyStatus}</span>}
          <button className="btn btn-ghost btn-sm" onClick={handleCopyResume}>Copy</button>

          {exportedPdf ? (
            <button className="btn btn-primary btn-sm" onClick={() => downloadExport(exportedPdf)}>
              PDF ✓
            </button>
          ) : (
            <button className="btn btn-secondary btn-sm" onClick={handleStorageExportPdf} disabled={pdfExportMutation.isPending || exportBlocked}>
              {pdfExportMutation.isPending ? <span className="spinner" style={{ width: 14, height: 14 }} /> : null}
              {pdfExportMutation.isPending ? '...' : 'PDF'}
            </button>
          )}

          {exportedDocx ? (
            <button className="btn btn-primary btn-sm" onClick={() => downloadExport(exportedDocx)}>
              DOCX ✓
            </button>
          ) : (
            <button className="btn btn-secondary btn-sm" onClick={handleStorageExportDocx} disabled={docxExportMutation.isPending || exportBlocked}>
              {docxExportMutation.isPending ? <span className="spinner" style={{ width: 14, height: 14 }} /> : null}
              {docxExportMutation.isPending ? '...' : 'DOCX'}
            </button>
          )}

          <button className="btn btn-ghost btn-sm" onClick={handleCoverLetter}>
            Cover Letter
          </button>

          <button className="btn btn-ghost btn-sm" onClick={handleNextJD}>
            New Resume
          </button>

          {recommendation && currentGenerationId && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => validateMutation.mutate({ generation_id: currentGenerationId, recommendation })}
              disabled={validateMutation.isPending}
            >
              {validateMutation.isPending ? <span className="spinner" style={{ width: 14, height: 14 }} /> : null}
              Refresh ATS
            </button>
          )}

          {currentGenerationId && (
            <button className="btn btn-ghost btn-sm" onClick={handleShareResumeLink}>
              Share Link
            </button>
          )}

          {overallScore != null && (
            <>
              {shareStatus && <span style={{ color: 'var(--status-success)', fontSize: '0.85rem' }}>{shareStatus}</span>}
              <button className="btn btn-ghost btn-sm" onClick={handleShareScore}>
                Share ATS Score
              </button>
            </>
          )}
        </div>
      </div>

      {/* Render error */}
      {renderError && (
        <div className="warning-banner warning-error">
          <span>⚠️</span>
          <div>
            <strong>Export problem</strong>
            {validationErrorLines(renderError).map((line, index) => (
              <p key={`${line}-${index}`} style={{ margin: index === 0 ? '4px 0 0' : '2px 0 0', fontSize: '0.85rem' }}>
                {line}
              </p>
            ))}
          </div>
        </div>
      )}

      <ExportReadinessCard
        recommendation={recommendation}
        atsScore={atsScore}
        exportError={renderError}
        validating={validateMutation.isPending}
        onValidate={() => currentGenerationId && validateMutation.mutate({ generation_id: currentGenerationId, recommendation })}
      />

      {/* PDF compression info */}
      {exportedPdf?.compressed && (
        <div className="warning-banner warning-info">
          <span>ℹ️</span>
          <div>
            <strong>Compressed to {exportedPdf.page_count ?? 1} page{(exportedPdf.page_count ?? 1) === 1 ? '' : 's'}</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              {(exportedPdf.compression_actions || []).slice(0, 3).join(' ') || 'Resume was adjusted to fit your page target while preserving all key information.'}
            </p>
          </div>
        </div>
      )}

      {/* Visual Editor */}
      {recommendation && currentGenerationId && (
        <div className="card review-editor-section" style={{ padding: 0, overflow: 'hidden' }}>
          <ResumeVisualEditor
            recommendation={recommendation}
            generationId={currentGenerationId}
            onSave={handleVisualEditorSave}
            onImproveBullet={(bulletId) => {
              // Scroll to the bullet and focus it — placeholder for future AI improve
              const bulletEl = document.querySelector(`[data-bullet-id="${bulletId}"]`);
              if (bulletEl) {
                bulletEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
                (bulletEl as HTMLElement).focus();
              }
            }}
          />
        </div>
      )}

      {/* Export Success Card — bottom of page */}
      <ExportSuccessCard
        pdfReady={!!exportedPdf}
        docxReady={!!exportedDocx}
        pageCount={pageCount}
        targetPages={targetPages}
        atsScore={overallScore ?? undefined}
        onDownloadPdf={exportedPdf ? () => downloadExport(exportedPdf) : handleStorageExportPdf}
        onDownloadDocx={exportedDocx ? () => downloadExport(exportedDocx) : handleStorageExportDocx}
        onNewResume={handleNextJD}
        onCoverLetter={handleCoverLetter}
        blocked={exportBlocked}
        blockReason={renderError ?? undefined}
        validationRepaired={validationRepaired}
        validationWarnings={validationWarnings}
      />
    </div>
  );
}
