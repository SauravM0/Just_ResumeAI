import { useEffect, useState, useRef } from 'react';
import type { SSEProgressEvent } from '../../lib/api';

export interface GenerationStep {
  id: string;
  label: string;
  detail?: string;
  status: 'pending' | 'in-progress' | 'done' | 'error';
  score?: number;
}

const DEFAULT_STEPS: GenerationStep[] = [
  { id: 'jd_parsing', label: 'Parsing job description', status: 'pending' },
  { id: 'scoring_original', label: 'Scoring your current resume', status: 'pending' },
  { id: 'building_evidence', label: 'Matching experience to requirements', status: 'pending' },
  { id: 'composing', label: 'Writing your resume', status: 'pending' },
  { id: 'repair_pass', label: 'Optimising for ATS', status: 'pending' },
  { id: 'pdf_compile', label: 'Building your PDF', status: 'pending' },
  { id: 'complete', label: 'Done!', status: 'pending' },
];

interface GenerationProgressProps {
  /** True when generation is actively running */
  isRunning: boolean;
  /** SSE progress events from the backend stream */
  sseEvents?: SSEProgressEvent[];
  /** Optional: error message if generation failed */
  errorMessage?: string;
  /** Original score from backend */
  originalScore?: number;
  /** Final score from backend */
  finalScore?: number;
  /** Callback when generation completes */
  onComplete?: () => void;
  /** Current step detail text */
  currentStepDetail?: string;
}

type StepStatusMap = Record<string, 'pending' | 'in-progress' | 'done' | 'error'>;
type StepDetailMap = Record<string, string | undefined>;

export default function GenerationProgress({
  isRunning,
  sseEvents = [],
  errorMessage,
  originalScore,
  finalScore,
  onComplete,
  currentStepDetail,
}: GenerationProgressProps) {
  const [, setElapsed] = useState(0);
  const [stepStatuses, setStepStatuses] = useState<StepStatusMap>({});
  const [stepDetails, setStepDetails] = useState<StepDetailMap>({});
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [progressPct, setProgressPct] = useState(0);
  const startTimeRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const completedRef = useRef(false);
  const hasRecoverableMessage = Boolean(errorMessage && isRunning);

  // Reset when generation starts
  useEffect(() => {
    if (isRunning) {
      startTimeRef.current = Date.now();
      completedRef.current = false;
      setElapsed(0);
      setStepStatuses({});
      setStepDetails({});
      setActiveStepIndex(0);
      setProgressPct(0);

      // Set first step as in-progress
      const initialStatuses: StepStatusMap = {};
      DEFAULT_STEPS.forEach((step, i) => {
        initialStatuses[step.id] = i === 0 ? 'in-progress' : 'pending';
      });
      setStepStatuses(initialStatuses);

      timerRef.current = setInterval(() => {
        setElapsed((prev) => prev + 1);
      }, 1000);

      return () => {
        if (timerRef.current) clearInterval(timerRef.current);
      };
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, [isRunning]);

  // Process SSE events to update steps in real-time
  useEffect(() => {
    if (!sseEvents.length) return;

    const lastEvent = sseEvents[sseEvents.length - 1];
    const event = lastEvent.event;
    const data = lastEvent.data;

    // Build step index map from event
    const eventToStep: Record<string, string> = {
      started: 'jd_parsing',
      jd_parsing: 'jd_parsing',
      jd_parsed: 'jd_parsing',
      scoring_original: 'scoring_original',
      original_scored: 'scoring_original',
      building_evidence: 'building_evidence',
      composing: 'composing',
      repair_pass: 'repair_pass',
      pdf_compile: 'pdf_compile',
      complete: 'complete',
    };

    // For error events, mark the last active/in-progress step as failed
    const stepId = eventToStep[event] || event;
    const isErrorEvent = event === 'error';
    const stepIndex = isErrorEvent
      ? activeStepIndex
      : DEFAULT_STEPS.findIndex((s) => s.id === stepId);

    setStepStatuses((prev) => {
      const updated: StepStatusMap = { ...prev };

      if (isErrorEvent) {
        // Mark the current active step as error
        const currentId = DEFAULT_STEPS[activeStepIndex]?.id;
        if (currentId) {
          updated[currentId] = 'error';
        }
      } else {
        // Mark all steps up to this one as done
        for (let i = 0; i < stepIndex; i++) {
          updated[DEFAULT_STEPS[i].id] = 'done';
        }

        // Mark current step
        if (event === 'complete') {
          updated['complete'] = 'done';
          // Mark all previous steps done
          DEFAULT_STEPS.forEach((s) => {
            if (!updated[s.id] || updated[s.id] === 'pending') {
              updated[s.id] = 'done';
            }
          });
        } else {
          updated[stepId] = 'in-progress';
        }
      }

      return updated;
    });

    // Update details
    if (event === 'jd_parsed' && data) {
      const keywords = (data as Record<string, unknown>).keywords_found;
      const title = (data as Record<string, unknown>).job_title;
      setStepDetails((prev) => ({
        ...prev,
        jd_parsing: `${title ? `${title} — ` : ''}${typeof keywords === 'number' ? keywords : 0} keywords detected`,
      }));
    }

    if (event === 'original_scored' && data) {
      const score = (data as Record<string, unknown>).original_score;
      setStepDetails((prev) => ({
        ...prev,
        scoring_original: `Score: ${typeof score === 'number' ? Math.round(score) : '?'}`,
      }));
    }

    if (event === 'repair_pass' && data) {
      const d = data as Record<string, unknown>;
      const attempt = d.attempt;
      const score = d.score;
      setActiveStepIndex(stepIndex);
      setStepDetails((prev) => ({
        ...prev,
        repair_pass: `Pass ${attempt} — ATS score: ${typeof score === 'number' ? Math.round(score) : '...'}`,
      }));
    }

    // Update progress percentage based on step index
    if (stepIndex >= 0) {
      const pct = Math.min(95, Math.round((stepIndex / (DEFAULT_STEPS.length - 1)) * 100));
      setProgressPct(pct);
    }

    if (event === 'complete') {
      setProgressPct(100);
      if (!completedRef.current) {
        completedRef.current = true;
        onComplete?.();
      }
    }
  }, [sseEvents, onComplete]);

  // Use original/final score for display
  useEffect(() => {
    if (originalScore !== undefined) {
      setStepDetails((prev) => ({
        ...prev,
        scoring_original: `Score: ${Math.round(originalScore)}`,
      }));
    }
  }, [originalScore]);

  useEffect(() => {
    if (finalScore !== undefined) {
      setStepDetails((prev) => ({
        ...prev,
        complete: `ATS Score: ${Math.round(finalScore)}`,
      }));
    }
  }, [finalScore]);

  // Handle error
  useEffect(() => {
    if (errorMessage && !isRunning) {
      setStepStatuses((prev) => ({
        ...prev,
        [DEFAULT_STEPS[activeStepIndex]?.id || '']: 'error',
      }));
    }
  }, [errorMessage, isRunning, activeStepIndex]);

  // Use currentStepDetail
  useEffect(() => {
    if (currentStepDetail) {
      const activeStep = DEFAULT_STEPS[activeStepIndex];
      if (activeStep) {
        setStepDetails((prev) => ({
          ...prev,
          [activeStep.id]: currentStepDetail,
        }));
      }
    }
  }, [currentStepDetail, activeStepIndex]);

  if (!isRunning && Object.keys(stepStatuses).length === 0 && !errorMessage && !finalScore) return null;

  return (
    <div className="card generation-status-card" role="status" aria-live="polite">
      <div className="generation-status-card-header">
        <span>{errorMessage && !hasRecoverableMessage ? '❌' : finalScore ? '✅' : '⚡'}</span>
        <span>
          {errorMessage
            ? (hasRecoverableMessage ? 'Resume generation is still running' : 'Generation failed')
            : finalScore
              ? 'Generation complete'
              : 'Generating your resume...'}
        </span>
      </div>

      {/* Progress bar */}
      {(!errorMessage || hasRecoverableMessage) && (
        <div style={{
          height: 4,
          background: 'var(--bg-glass-strong)',
          borderRadius: 'var(--radius-full)',
          overflow: 'hidden',
          marginBottom: 'var(--space-md)',
        }}>
          <div style={{
            height: '100%',
            width: `${progressPct}%`,
            background: 'var(--accent-gradient)',
            borderRadius: 'var(--radius-full)',
            transition: 'width 0.5s ease',
          }} />
        </div>
      )}

      {/* Step list */}
      <div className="generation-status-card-steps">
        {DEFAULT_STEPS.map((step) => {
          const status = stepStatuses[step.id] || 'pending';
          const detail = stepDetails[step.id];

          return (
            <div key={step.id} className="generation-status-card-step">
              <span className="generation-status-card-step-icon">
                {status === 'done' && (
                  <span style={{ color: 'var(--status-success)' }}>✓</span>
                )}
                {status === 'in-progress' && (
                  <span className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} />
                )}
                {status === 'error' && (
                  <span style={{ color: 'var(--status-danger)' }}>✕</span>
                )}
                {status === 'pending' && (
                  <span style={{ color: 'var(--text-tertiary)' }}>○</span>
                )}
              </span>
              <div className="generation-status-card-step-info">
                <span
                  className="generation-status-card-step-name"
                  style={{
                    color: status === 'done'
                      ? 'var(--text-success)'
                      : status === 'in-progress'
                        ? 'var(--text-accent)'
                        : status === 'error'
                          ? 'var(--text-danger)'
                          : 'var(--text-tertiary)',
                  }}
                >
                  {step.label}
                </span>
                {detail && (
                  <span className="generation-status-card-step-detail">{detail}</span>
                )}
                {status === 'done' && !detail && (
                  <span className="generation-status-card-step-detail">Complete</span>
                )}
                {status === 'in-progress' && !detail && (
                  <span className="generation-status-card-step-detail">Running...</span>
                )}
                {status === 'error' && errorMessage && !hasRecoverableMessage && (
                  <span className="generation-status-card-step-detail" style={{ color: 'var(--text-danger)' }}>
                    {errorMessage}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
