import type { ValidationStatus } from '../../types/resume';

interface Props {
  status: ValidationStatus | null | undefined;
  /** Override to show a blocked state from an export error string */
  exportError?: string | null;
  /** Called when user clicks retry / refresh */
  onRetry?: () => void;
  /** Called when user clicks "Edit JD" */
  onEditJD?: () => void;
  /** Called when user clicks "Edit Profile" */
  onEditProfile?: () => void;
  /** Loading state for retry button */
  validating?: boolean;
  className?: string;
}

export default function ValidationStatusCard({
  status,
  exportError,
  onRetry,
  onEditJD,
  onEditProfile,
  validating = false,
  className = '',
}: Props) {
  // Determine the effective state
  const effectiveError = exportError || (status?.blocked_reasons?.length ? status.blocked_reasons.join('\n') : null);
  const effectiveWarnings = status?.warnings ?? [];
  const effectiveActions = status?.repair_actions ?? [];
  const effectiveUserActions = status?.user_actions ?? [];
  const isBlocked = Boolean(effectiveError) || status?.severity === 'blocked';
  const hasWarnings = effectiveWarnings.length > 0 || effectiveUserActions.length > 0;
  const isPass = status?.severity === 'pass' && !effectiveError && !isBlocked;
  const showCard = isBlocked || hasWarnings || exportError;

  if (!showCard && !isPass) return null;

  const state = isBlocked ? 'blocked' : hasWarnings ? 'warning' : 'pass';

  return (
    <section
      className={`validation-status-card validation-status-${state} ${className}`}
      aria-live="polite"
      role={isBlocked ? 'alert' : 'status'}
    >
      {/* ── Blocked / Error State ── */}
      {(isBlocked || exportError) && (
        <div className="validation-blocked">
          <div className="validation-status-head">
            <span className="validation-status-icon" aria-hidden="true">✕</span>
            <div>
              <h3 className="validation-status-title">Export blocked by validation</h3>
              <p className="validation-status-desc">
                Resolve the issues below, then retry the export.
              </p>
            </div>
          </div>

          {effectiveError && (
            <div className="validation-reasons">
              {effectiveError.split('\n').map((line, i) => (
                <p key={i} className="validation-reason">{line}</p>
              ))}
            </div>
          )}

          {effectiveActions.length > 0 && (
            <div className="validation-actions-taken">
              <h4>🛠 Auto-repair actions applied</h4>
              {effectiveActions.slice(0, 5).map((action, i) => (
                <p key={i} className="validation-action">{action}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Warning State ── */}
      {!isBlocked && hasWarnings && (
        <div className="validation-warning">
          <div className="validation-status-head">
            <span className="validation-status-icon" aria-hidden="true">⚠</span>
            <div>
              <h3 className="validation-status-title">Review validation warnings</h3>
              <p className="validation-status-desc">
                Non-blocking issues to review before exporting.
              </p>
            </div>
          </div>

          {effectiveWarnings.length > 0 && (
            <div className="validation-warnings-list">
              {effectiveWarnings.slice(0, 8).map((warning, i) => (
                <p key={i} className="validation-warning-item">{warning}</p>
              ))}
            </div>
          )}

          {effectiveActions.length > 0 && (
            <div className="validation-actions-taken">
              <h4>🛠 Auto-repair actions applied</h4>
              {effectiveActions.slice(0, 5).map((action, i) => (
                <p key={i} className="validation-action">{action}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── User actions ── */}
      {effectiveUserActions.length > 0 && (
        <div className="validation-user-actions">
          <h4>Suggested fixes</h4>
          {effectiveUserActions.slice(0, 5).map((action, i) => (
            <p key={i} className="validation-user-action">{action}</p>
          ))}
        </div>
      )}

      {/* ── Action buttons ── */}
      <div className="validation-actions-bar">
        {onRetry && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={onRetry}
            disabled={validating}
          >
            {validating ? <><span className="spinner" /> Retrying...</> : 'Retry Export'}
          </button>
        )}
        {onEditJD && (
          <button className="btn btn-ghost btn-sm" onClick={onEditJD}>
            Edit Job Description
          </button>
        )}
        {onEditProfile && (
          <button className="btn btn-ghost btn-sm" onClick={onEditProfile}>
            Edit Profile
          </button>
        )}
      </div>

      {/* ── Pass State (subtle success indicator) ── */}
      {isPass && !exportError && (
        <div className="validation-pass">
          <div className="validation-status-head">
            <span className="validation-status-icon" aria-hidden="true">✓</span>
            <div>
              <h3 className="validation-status-title">Validation passed</h3>
              <p className="validation-status-desc">
                Resume is ready for export. No blocking issues detected.
              </p>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
