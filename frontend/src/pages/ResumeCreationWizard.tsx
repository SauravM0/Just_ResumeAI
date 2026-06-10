import { useState, useEffect, useRef, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getMyProfile } from '../lib/profileApi';
import { getSettings, updateSettings } from '../lib/settingsApi';
import { sanitizeProfile } from '../lib/profile';
import { useAppStore } from '../store/useAppStore';
import { useGeneration } from '../hooks/useGeneration';
import { ApiError, getGenerationResult } from '../lib/api';
import { getErrorMessage, extractErrorCode } from '../lib/errorMessages';
import PageHeader from '../components/ui/PageHeader';
import FlowStepper from '../components/ui/FlowStepper';
import type { FlowStep } from '../components/ui/FlowStepper';
import ProfileSelector from '../components/ui/ProfileSelector';
import ATSFeedbackCard from '../components/ui/ATSFeedbackCard';
import ATSRepairStatus from '../components/ui/ATSRepairStatus';
import OptimizationDiagnosticsCard from '../components/ui/OptimizationDiagnosticsCard';
import ValidationStatusCard from '../components/ui/ValidationStatusCard';
import GenerationProgress from '../components/ui/GenerationProgress';
import JDProcessingNotes from '../components/ui/JDProcessingNotes';
import type { MasterProfile } from '../types/profile';

const WIZARD_STEPS: FlowStep[] = [
  { id: 'profile', label: 'Select Profile', shortLabel: 'Profile', icon: '👤' },
  { id: 'jd', label: 'Job Description', shortLabel: 'JD', icon: '📋' },
  { id: 'settings', label: 'Settings', shortLabel: 'Settings', icon: '⚙' },
  { id: 'generate', label: 'Generate', shortLabel: 'Generate', icon: '✨' },
  { id: 'ats-review', label: 'ATS Review', shortLabel: 'ATS', icon: '📊' },
  { id: 'preview', label: 'Preview', shortLabel: 'Preview', icon: '👁' },
  { id: 'download', label: 'Download', shortLabel: 'Export', icon: '⬇' },
];

type WizardStep = number;

export default function ResumeCreationWizard() {
  const navigate = useNavigate();
  const location = useLocation();
  const [step, setStep] = useState<WizardStep>(0);
  const [rawJD, setRawJD] = useState('');
  const [targetPages, setTargetPages] = useState(1);
  const [generatePdf, setGeneratePdf] = useState(true);
  const [atsOptimizationMode, setAtsOptimizationMode] = useState<'realistic' | 'aggressive'>('aggressive');
  const [showAggressiveConfirm, setShowAggressiveConfirm] = useState(false);
  const [saveAggressiveAsDefault, setSaveAggressiveAsDefault] = useState(false);
  const [profile, setProfile] = useState<MasterProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState(false);
  const [blockingError, setBlockingError] = useState<string | null>(null);
  const [blockingErrorCode, setBlockingErrorCode] = useState<string | null>(null);
  const [autoRetryCountdown, setAutoRetryCountdown] = useState<number | null>(null);
  const [generationStarting, setGenerationStarting] = useState(false);

  // SSE streaming state via hook
  const {
    generate,
    cancel,
    isGenerating,
    activeGenerationId: genIdFromHook,
    rawEvents,
    originalScore: genOriginalScore,
    finalScore: genFinalScore,
    error: streamError,
  } = useGeneration({
    onComplete: () => {
      // Signal that stream completed — the effect below will fetch the result
      setStreamReady(true);
    },
    onError: (codeOrMessage, message) => {
      // First argument might be an error code (e.g. 'JD_INVALID') or a plain message
      const errorConfig = getErrorMessage(codeOrMessage);
      const displayMessage = message || codeOrMessage;
      setBlockingError(displayMessage);
      if (errorConfig.title !== 'Something went wrong') {
        setBlockingErrorCode(codeOrMessage);
      }
    },
  });

  const [generationComplete, setGenerationComplete] = useState(false);
  const [streamReady, setStreamReady] = useState(false);
  const cleanupRef = useRef<(() => void) | null>(null);

  // Keep a ref of the generation ID for the result fetch effect
  const generationId = genIdFromHook;

  // Map hook state to wizard-local state for backward compatibility
  const originalScore = genOriginalScore ?? undefined;
  const finalScore = genFinalScore ?? undefined;

  const {
    setParsedJD,
    setPipelineWarnings,
    setRecommendation,
    setAtsScore,
    setAlignmentReport,
    setLatexSource,
    setValidationStatus,
    setActiveProfile,
    // Read selectors for ATS review & preview
    parsedJD,
    atsScore,
    recommendation,
    validationStatus,
    pipelineWarnings,
  } = useAppStore();

  useEffect(() => {
    let cancelled = false;
    setProfileLoading(true);
    setProfileError(false);

    getMyProfile()
      .then((res) => {
        if (!cancelled) {
          setProfile(res.profile_json);
          setProfileLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProfileError(true);
          setProfileLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('ats') === 'aggressive' || params.get('target') === '100') {
      setAtsOptimizationMode('aggressive');
    }
  }, [location.search]);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((data) => {
        if (!cancelled && data.aggressive_ats_default) {
          setAtsOptimizationMode('aggressive');
        }
      })
      .catch(() => {
        // Settings are optional for generation; keep realistic mode on failure.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // When stream completes, fetch the full result
  useEffect(() => {
    if (!streamReady || !generationId) return;

    const loadResult = async () => {
      try {
        const result = await getGenerationResult(generationId);
        if (result.status === 'draft' || result.status === 'queued' || result.status === 'running') {
          setStreamReady(false);
          setBlockingError(result.message || 'Generation is still running. Please wait and try again shortly.');
          setBlockingErrorCode(null);
          return;
        }
        if (result.status === 'failed' || result.status === 'cancelled') {
          setBlockingError(result.message || `Generation ${result.status}.`);
          setBlockingErrorCode(result.status === 'cancelled' ? 'GENERATION_CANCELLED' : 'PIPELINE_ERROR');
          return;
        }
        // Parse the generation record for pipeline data
        if (result.parsed_jd_json) {
          setParsedJD(result.parsed_jd_json);
        }
        if (result.resume_json) {
          setRecommendation(result.resume_json);
        }
        if (result.ats_score_json) {
          setAtsScore(result.ats_score_json);
        }
        if (result.alignment_report_json) {
          setAlignmentReport(result.alignment_report_json);
        }
        if (result.latex_source) {
          setLatexSource(result.latex_source);
        }
        if (result.validation_status) {
          setValidationStatus(result.validation_status);
        }
        if (result.warnings && Array.isArray(result.warnings)) {
          setPipelineWarnings(result.warnings);
        }

        setGenerationComplete(true);
        setStep(4); // Move to ATS review
      } catch (err) {
        // If result endpoint fails, complete was already emitted — move forward
        const requestId = err instanceof ApiError && err.request_id ? ` Request ID: ${err.request_id}` : '';
        const message = err instanceof Error ? `${err.message}${requestId}` : 'Unable to load generation result.';
        setBlockingError(message);
        setBlockingErrorCode(extractErrorCode(err));
      }
    };

    loadResult();
  }, [streamReady, generationId, setParsedJD, setRecommendation, setAtsScore, setAlignmentReport, setLatexSource, setValidationStatus, setPipelineWarnings]);

  const handleProfileContinue = () => {
    if (!profile?.contact.full_name?.trim()) {
      setBlockingError('Please add your name to your profile before continuing.');
      return;
    }
    setBlockingError(null);
    const normalized = sanitizeProfile(profile);
    setActiveProfile(normalized);
    setStep(1);
  };

  const handleProfileEdit = () => {
    navigate('/profile');
  };

  const handleProfileSkip = () => {
    setActiveProfile(null);
    setStep(1);
  };

  // Cleanup SSE connection on unmount
  useEffect(() => {
    return () => {
      cleanupRef.current?.();
      cancel();
    };
  }, [cancel]);

  const handleGenerate = async () => {
    if (rawJD.trim().length < 50) return;
    if (generationStarting || isGenerating) return;
    if (atsOptimizationMode === 'aggressive' && !showAggressiveConfirm) {
      setShowAggressiveConfirm(true);
      return;
    }
    setShowAggressiveConfirm(false);

    try {
      setGenerationStarting(true);
      if (atsOptimizationMode === 'aggressive' && saveAggressiveAsDefault) {
        void updateSettings({ aggressive_ats_default: true });
      }
      const savedProfile = profile || (await getMyProfile()).profile_json;
      if (!savedProfile?.contact.full_name?.trim()) {
        setBlockingError('A profile with a name is required to generate a resume.');
        return;
      }

      const normalizedProfile = sanitizeProfile(savedProfile);
      setActiveProfile(normalizedProfile);
      setBlockingError(null);

      setGenerationComplete(false);
      setStreamReady(false);

      // Cleanup any previous connection
      cleanupRef.current?.();

      setStep(3);

      // Start generation via the hook — handles all SSE streaming
      const cleanup = await generate({
        profile: normalizedProfile,
        raw_jd_text: rawJD,
        target_pages: targetPages,
        allow_two_pages_for_senior: targetPages === 2,
        generate_pdf: generatePdf,
        additional_alignment_text: undefined,
        ats_optimization_mode: atsOptimizationMode,
        target_ats_score: atsOptimizationMode === 'aggressive' ? 100 : 90,
        max_repair_attempts: atsOptimizationMode === 'aggressive' ? 7 : 3,
      });
      cleanupRef.current = cleanup ?? null;

      // Store the generation ID for result fetching
      // (activeGenerationId is set by the hook's startGeneration call)
    } catch (error) {
      const errCode = extractErrorCode(error);
      const errorConfig = getErrorMessage(errCode);
      setBlockingError(errorConfig.message);
      setBlockingErrorCode(errCode);

      // Auto-retry for retryable errors after 3s countdown
      if (errorConfig.retryable) {
        startAutoRetry(errCode);
      }
    } finally {
      setGenerationStarting(false);
    }
  };

  const handleViewPreview = () => {
    setStep(5);
  };

  const handleGoToDownload = () => {
    setStep(6);
  };

  const handleFinishAndReview = () => {
    const genId = generationId;
    if (genId) {
      navigate(`/review/${genId}`);
    }
  };

  // ── Auto-retry after 3s countdown ────────────────────────────────────
  const autoRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Keep a ref to handleGenerate so the timeout callback always calls the latest version
  const handleGenerateRef = useRef(handleGenerate);
  handleGenerateRef.current = handleGenerate;

  const startAutoRetry = useCallback((_errCode: string) => {
    setAutoRetryCountdown(3);
    const countdown = setInterval(() => {
      setAutoRetryCountdown((prev) => {
        if (prev === null || prev <= 1) {
          clearInterval(countdown);
          setAutoRetryCountdown(null);
          return null;
        }
        return prev - 1;
      });
    }, 1000);

    // Wait 3s then retry one time with the latest state
    autoRetryTimerRef.current = setTimeout(() => {
      setBlockingError(null);
      setBlockingErrorCode(null);
      setAutoRetryCountdown(null);
      clearInterval(countdown);
      handleGenerateRef.current();
    }, 3000);
  }, []); // only stable refs — safe to keep empty deps

  // Cleanup auto-retry timer on unmount
  useEffect(() => {
    return () => {
      if (autoRetryTimerRef.current) clearTimeout(autoRetryTimerRef.current);
    };
  }, []);

  const handleStartOver = () => {
    setRawJD('');
    setTargetPages(1);
    setGeneratePdf(true);
    setStep(0);
    setBlockingError(null);
    setBlockingErrorCode(null);
  };

  const charCount = rawJD.length;
  const jdValid = charCount >= 50;
  const isLongJD = charCount > 12000;

  const completedSteps = Array.from({ length: step }, (_, i) => i);

  return (
    <div className="animate-fade-in wizard-layout">
      <PageHeader
        title="Create Your Resume"
        subtitle="Follow the steps below to create a JD-aligned, ATS-optimized resume."
      />

      <FlowStepper steps={WIZARD_STEPS} currentStep={step} completedSteps={completedSteps} />

      {showAggressiveConfirm && (
        <div className="modal-backdrop">
          <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="aggressive-ats-title">
            <h2 id="aggressive-ats-title">Approve Aggressive ATS Mode</h2>
            <p>
              To maximize ATS score, we may add or rewrite skills, experience, and project details that are not present in your master profile.
            </p>
            <label className="setting-option" style={{ marginBottom: 'var(--space-md)' }}>
              <input
                type="checkbox"
                checked={saveAggressiveAsDefault}
                onChange={(event) => setSaveAggressiveAsDefault(event.target.checked)}
              />
              <div className="setting-option-content">
                <strong>Use this as my default</strong>
                <span>Preselect Optimize to 100% for future resumes.</span>
              </div>
            </label>
            <div className="wizard-actions">
              <button className="btn btn-ghost" onClick={() => setShowAggressiveConfirm(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleGenerate}>
                Approve for this resume
              </button>
            </div>
          </div>
        </div>
      )}

      {blockingError && blockingErrorCode && getErrorMessage(blockingErrorCode).title !== 'Something went wrong' && (
        <div className="error-card animate-fade-in">
          <div className="error-card-header">
            <span className="error-card-icon">⚠️</span>
            <h3 className="error-card-title">{getErrorMessage(blockingErrorCode).title}</h3>
          </div>
          <p className="error-card-message">{blockingError}</p>
          <div className="error-card-actions">
            {getErrorMessage(blockingErrorCode).retryable ? (
              <>
                {autoRetryCountdown !== null ? (
                  <span className="text-muted" style={{ fontSize: '0.85rem' }}>
                    Retrying in {autoRetryCountdown}s...
                  </span>
                ) : (
                  <button className="btn btn-primary" onClick={handleGenerate}>
                    {getErrorMessage(blockingErrorCode).action}
                  </button>
                )}
                <button className="btn btn-ghost" onClick={() => { setStep(2); setBlockingError(null); setBlockingErrorCode(null); }}>
                  Back to Settings
                </button>
              </>
            ) : blockingErrorCode === 'PROFILE_INCOMPLETE' ? (
              <button className="btn btn-primary" onClick={() => navigate('/profile')}>
                {getErrorMessage(blockingErrorCode).action}
              </button>
            ) : blockingErrorCode === 'AUTH_EXPIRED' ? (
              <button className="btn btn-primary" onClick={() => navigate('/login')}>
                {getErrorMessage(blockingErrorCode).action}
              </button>
            ) : (
              <>
                <button className="btn btn-ghost" onClick={handleStartOver}>
                  {getErrorMessage(blockingErrorCode).action}
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {blockingError && !blockingErrorCode && (
        <div className="warning-banner warning-error">
          <span>⚠️</span>
          <div>
            <strong>Action required</strong>
            <p style={{ margin: 0, marginTop: '4px', fontSize: '0.8rem' }}>{blockingError}</p>
          </div>
        </div>
      )}

      {/* Step 0: Profile Selection */}
      {step === 0 && (
        <div className="wizard-step animate-fade-in">
          <div className="wizard-step-header">
            <h2>Step 1: Select Your Profile</h2>
            <p>Choose the profile to use for this resume, or set up a new one.</p>
          </div>
          <ProfileSelector
            profile={profile}
            loading={profileLoading}
            error={profileError}
            onContinue={handleProfileContinue}
            onEditProfile={handleProfileEdit}
            onSkip={handleProfileSkip}
          />
        </div>
      )}

      {/* Step 1: Job Description */}
      {step === 1 && (
        <div className="wizard-step animate-fade-in">
          <div className="wizard-step-header">
            <h2>Step 2: Paste the Job Description</h2>
            <p>
              Paste the full job posting below. The more detail you include, the better your resume will match.
            </p>
          </div>

          <div className="card">
            <div className="form-group">
              <label className="form-label" htmlFor="wizard-jd-textarea">Job Description</label>
              <textarea
                id="wizard-jd-textarea"
                className="form-textarea"
                value={rawJD}
                onChange={(e) => setRawJD(e.target.value)}
                placeholder="Paste the complete job description here..."
                style={{ minHeight: '250px', fontFamily: 'var(--font-sans)' }}
                aria-describedby="wizard-jd-hint"
              />
              <div id="wizard-jd-hint" className="form-hint-row">
                <span className={`form-hint ${!jdValid ? 'text-warning' : ''}`}>
                  {charCount === 0
                    ? 'Paste a job description to continue'
                    : charCount < 50
                      ? `${50 - charCount} more characters needed`
                      : `${charCount.toLocaleString()} characters — looks good`}
                </span>
                {isLongJD && <span className="badge badge-warning">Long JD</span>}
              </div>
            </div>

            <div className="wizard-tips" style={{ marginTop: 'var(--space-lg)' }}>
              <h4>Tips for best results</h4>
              <ul>
                <li>Include the job title, company, and full responsibilities</li>
                <li>Add required skills, qualifications, and preferred experience</li>
                <li>The AI matches your profile against these keywords automatically</li>
              </ul>
            </div>

            <div className="wizard-actions">
              <button className="btn btn-ghost" onClick={() => setStep(0)}>
                Back
              </button>
              <button
                className="btn btn-primary"
                onClick={() => setStep(2)}
                disabled={!jdValid}
              >
                Continue to Settings
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 2: Settings */}
      {step === 2 && (
        <div className="wizard-step animate-fade-in">
          <div className="wizard-step-header">
            <h2>Step 3: Resume Settings</h2>
            <p>Choose your preferred resume length and options.</p>
          </div>

          <div className="card">
            <div className="form-group">
              <label className="form-label">Resume Length</label>
              <div className="setting-options">
                <label
                  className={`setting-option ${targetPages === 1 ? 'selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="wizard-target-pages"
                    checked={targetPages === 1}
                    onChange={() => setTargetPages(1)}
                  />
                  <div className="setting-option-content">
                    <strong>1 Page</strong>
                    <span>Standard — best for most roles</span>
                  </div>
                </label>
                <label
                  className={`setting-option ${targetPages === 2 ? 'selected' : ''}`}
                >
                  <input
                    type="radio"
                    name="wizard-target-pages"
                    checked={targetPages === 2}
                    onChange={() => setTargetPages(2)}
                  />
                  <div className="setting-option-content">
                    <strong>2 Pages</strong>
                    <span>Senior roles — 10+ years experience</span>
                  </div>
                </label>
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Options</label>
              <label className="setting-option">
                <input
                  type="checkbox"
                  checked={generatePdf}
                  onChange={(e) => setGeneratePdf(e.target.checked)}
                />
                <div className="setting-option-content">
                  <strong>Compile PDF</strong>
                  <span>Generate a downloadable PDF file</span>
                </div>
              </label>
            </div>

            <div className="form-group">
              <label className="form-label">ATS Optimization Mode</label>
              <div className="settings-radio-group">
                <label className={`settings-radio ${atsOptimizationMode === 'realistic' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="ats_optimization_mode"
                    value="realistic"
                    checked={atsOptimizationMode === 'realistic'}
                    onChange={() => setAtsOptimizationMode('realistic')}
                  />
                  <span>Realistic 90+</span>
                </label>
                <label className={`settings-radio ${atsOptimizationMode === 'aggressive' ? 'active' : ''}`}>
                  <input
                    type="radio"
                    name="ats_optimization_mode"
                    value="aggressive"
                    checked={atsOptimizationMode === 'aggressive'}
                    onChange={() => setAtsOptimizationMode('aggressive')}
                  />
                  <span>Optimize to 100%</span>
                </label>
              </div>
              <span className="form-hint">
                Realistic mode preserves profile evidence. Optimize to 100% requires approval and may add JD-aligned skills or claims.
              </span>
            </div>

            <div className="wizard-actions">
              <button className="btn btn-ghost" onClick={() => setStep(1)}>
                Back
              </button>
              <button className="btn btn-primary btn-lg" onClick={handleGenerate} disabled={generationStarting || isGenerating}>
                {generationStarting || isGenerating ? 'Generating...' : 'Generate Resume'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Generating */}
      {step === 3 && (
        <div className="wizard-step animate-fade-in">
          <div className="wizard-step-header">
            <h2>Step 4: Generating Your Resume</h2>
            <p>AI is analyzing the job description and tailoring your resume.</p>
          </div>

          <GenerationProgress
            isRunning={isGenerating}
            sseEvents={rawEvents}
            errorMessage={streamError || undefined}
            originalScore={originalScore}
            finalScore={finalScore}
            onComplete={() => {
              // onComplete triggers from SSE events
            }}
          />

          {/* Cancel button while generating */}
          {isGenerating && !generationComplete && (
            <div className="wizard-actions" style={{ marginTop: 'var(--space-md)' }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  cancel();
                  setStep(2);
                }}
              >
                Cancel Generation
              </button>
            </div>
          )}

          {streamError && (
            <div className="wizard-actions" style={{ marginTop: 'var(--space-lg)' }}>
              <button className="btn btn-ghost" onClick={() => setStep(2)}>
                Back to Settings
              </button>
              <button className="btn btn-primary" onClick={handleGenerate}>
                Retry Generate
              </button>
            </div>
          )}

          {generationComplete && !streamError && (
            <div className="wizard-actions" style={{ marginTop: 'var(--space-lg)' }}>
              <button className="btn btn-primary btn-lg" onClick={handleViewPreview}>
                View ATS Results
              </button>
            </div>
          )}
        </div>
      )}

      {/* Step 4: ATS Review */}
      {step === 4 && generationComplete && (
        <div className="wizard-step animate-fade-in">
          <div className="wizard-step-header">
            <h2>Step 5: ATS Score & Keyword Review</h2>
            <p>Review how well your resume matches the job description.</p>
          </div>

          <ATSFeedbackCard
            atsScore={atsScore ?? null}
            targetPages={targetPages}
          />

          <ValidationStatusCard
            status={validationStatus ?? null}
            exportError={null}
            onEditJD={() => { setStep(1); }}
            onEditProfile={() => setStep(0)}
          />

          <JDProcessingNotes
            warnings={[
              ...(pipelineWarnings ?? []),
              ...(parsedJD?.quality_warnings ?? []),
            ]}
          />

          {recommendation?.warnings?.some((warning) => warning.includes('title was adjusted to avoid unsupported seniority')) && (
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

          <ATSRepairStatus
            atsScore={atsScore ?? null}
            resumeVersionId={recommendation?.version_id}
          />

          <OptimizationDiagnosticsCard
            optimization={null}
          />

          <div className="wizard-actions">
            <button className="btn btn-ghost" onClick={() => setStep(3)}>
              Back
            </button>
            <button className="btn btn-primary" onClick={handleGoToDownload}>
              Preview & Download
            </button>
          </div>
        </div>
      )}

      {/* Step 5: Preview */}
      {step === 5 && generationComplete && (
        <div className="wizard-step animate-fade-in">
          <div className="wizard-step-header">
            <h2>Step 6: Preview Your Resume</h2>
            <p>Review the generated content before exporting.</p>
          </div>

          <div className="card preview-summary-card">
            <h4>Resume Summary</h4>
            <div className="preview-meta">
              <div className="preview-meta-item">
                <span className="preview-meta-label">Job Title</span>
                <span className="preview-meta-value">
                  {parsedJD?.job_title || 'Not specified'}
                </span>
              </div>
              <div className="preview-meta-item">
                <span className="preview-meta-label">Company</span>
                <span className="preview-meta-value">
                  {parsedJD?.company || 'Not specified'}
                </span>
              </div>
              <div className="preview-meta-item">
                <span className="preview-meta-label">Target Length</span>
                <span className="preview-meta-value">{targetPages} page{targetPages > 1 ? 's' : ''}</span>
              </div>
              <div className="preview-meta-item">
                <span className="preview-meta-label">ATS Score</span>
                <span className={`preview-meta-value ${
                  (atsScore?.overall_score ?? 0) >= 80
                    ? 'text-success'
                    : (atsScore?.overall_score ?? 0) >= 65
                      ? 'text-warning'
                      : 'text-danger'
                }`}>
                  {Math.round(atsScore?.overall_score ?? 0)}
                </span>
              </div>
            </div>
          </div>

          <div className="warning-banner warning-info">
            <span>ℹ️</span>
            <div>
              <strong>Facts preserved</strong>
              <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
                Your resume was generated using only information from your profile. No facts were invented.
                Content was rewritten for ATS optimization while preserving all original details.
              </p>
            </div>
          </div>

          <div className="wizard-actions">
            <button className="btn btn-ghost" onClick={() => setStep(4)}>
              Back to ATS
            </button>
            <button className="btn btn-primary" onClick={handleFinishAndReview}>
              Open Full Editor
            </button>
          </div>
        </div>
      )}

      {/* Step 6: Download */}
      {step === 6 && generationComplete && (
        <div className="wizard-step animate-fade-in">
          <div className="wizard-step-header">
            <h2>Step 7: Download Your Resume</h2>
            <p>Your resume is ready. Download it in your preferred format.</p>
          </div>

          <div className="card download-card">
            <div className="download-success-icon">✅</div>
            <h3 className="download-title">Resume Ready for Download</h3>
            <p className="download-subtitle">
              Your JD-aligned resume has been generated with an ATS score of{' '}
              <strong>{Math.round(atsScore?.overall_score ?? finalScore ?? 0)}</strong>.
            </p>

            <div className="download-options">
              <button
                className="download-option-btn"
                onClick={handleFinishAndReview}
              >
                <span className="download-option-icon">📄</span>
                <div className="download-option-info">
                  <strong>Download PDF</strong>
                  <span>Professional format, ready to send</span>
                </div>
              </button>
              <button
                className="download-option-btn"
                onClick={handleFinishAndReview}
              >
                <span className="download-option-icon">📝</span>
                <div className="download-option-info">
                  <strong>Download DOCX</strong>
                  <span>Editable Word document</span>
                </div>
              </button>
            </div>

            <div className="download-actions">
              <button className="btn btn-ghost" onClick={() => setStep(5)}>
                Back to Preview
              </button>
              <button className="btn btn-primary btn-lg" onClick={handleFinishAndReview}>
                Open in Full Editor
              </button>
            </div>
          </div>

          <div className="wizard-actions" style={{ marginTop: 'var(--space-lg)' }}>
            <button className="btn btn-ghost" onClick={handleStartOver}>
              Create Another Resume
            </button>
            <button className="btn btn-ghost" onClick={() => navigate('/dashboard')}>
              Go to Dashboard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
