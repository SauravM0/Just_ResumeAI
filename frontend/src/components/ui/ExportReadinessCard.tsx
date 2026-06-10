import type { ATSScore, ResumeRecommendation, ValidationStatus } from '../../types/resume';

interface Props {
  recommendation: ResumeRecommendation;
  atsScore: ATSScore | null;
  exportError?: string | null;
  validating?: boolean;
  onValidate?: () => void;
  className?: string;
  /** Whether the validation gate repaired the resume before export */
  validationRepaired?: boolean;
  /** Validation warnings from the gate */
  validationWarnings?: string[];
  /** Standardized validation status object from backend */
  validationStatus?: ValidationStatus | null;
}

export default function ExportReadinessCard({
  recommendation,
  atsScore,
  exportError,
  validating = false,
  onValidate,
  className = '',
  validationRepaired = false,
  validationWarnings = [],
  validationStatus,
}: Props) {
  const isStale = recommendation?.version_id && atsScore?.resume_version_id && recommendation.version_id !== atsScore.resume_version_id;
  
  // Merge legacy warnings with standardized validation_status
  const recommendationWarnings = recommendation.warnings ?? [];
  const scoreWarnings = atsScore?.warnings ?? [];
  const mergedWarnings = [
    ...new Set([
      ...recommendationWarnings,
      ...scoreWarnings,
      ...(validationStatus?.warnings ?? []),
    ])
  ];
  const blocked = Boolean(exportError) || validationStatus?.severity === 'blocked';
  const hasScore = Boolean(atsScore) && !isStale;
  const state = blocked ? 'blocked' : isStale ? 'stale' : hasScore ? 'ready' : 'check';

  return (
    <section className={`export-readiness card export-readiness-${state} ${className}`} aria-live="polite">
      <div className="export-readiness-head">
        <div className="export-readiness-mark" aria-hidden="true">
          {blocked ? '!' : isStale ? '↻' : hasScore ? 'OK' : '?'}
        </div>
        <div>
          <h2>{blocked ? 'Export blocked by validation' : isStale ? 'Score out of sync' : hasScore ? 'Export-ready check' : 'Check before export'}</h2>
          <p>
            {blocked
              ? 'Resolve the validation message, then save and export again.'
              : isStale
                ? 'Your resume has manual edits. Re-run validation to ensure export readiness.'
                : hasScore
                  ? 'ATS feedback and resume warnings are visible before you download.'
                  : 'Refresh ATS after edits so the review screen can explain export readiness.'}
          </p>
        </div>
      </div>

      {validationRepaired && !blocked && (
        <div className="warning-banner warning-info" style={{ marginBottom: 'var(--space-sm)' }}>
          <span>🛠</span>
          <div>
            <strong>Auto-repaired before export</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              The validation gate automatically fixed minor issues.{(validationWarnings ?? []).length > 0 && ` ${(validationWarnings ?? []).length} warning(s) resolved.`}
            </p>
          </div>
        </div>
      )}

      {/* Standardized blocked reasons from validation_status */}
      {validationStatus?.blocked_reasons && validationStatus.blocked_reasons.length > 0 && (
        <div className="export-readiness-blocker" role="alert">
          {validationStatus.blocked_reasons.map((reason, i) => (
            <p key={i} style={{ margin: i > 0 ? '4px 0 0' : 0 }}>{reason}</p>
          ))}
        </div>
      )}

      {exportError && (
        <div className="export-readiness-blocker" role="alert">
          {exportError}
        </div>
      )}

      {mergedWarnings.length > 0 ? (
        <div className="export-readiness-warnings">
          <div className="section-label">Validation notes</div>
          {mergedWarnings.slice(0, 5).map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      ) : (
        <p className="export-readiness-clear">No resume validation warnings are currently shown.</p>
      )}

      {onValidate && (
        <button className="btn btn-secondary" onClick={onValidate} disabled={validating}>
          {validating ? <><span className="spinner" /> Checking...</> : 'Refresh ATS Check'}
        </button>
      )}
    </section>
  );
}
