interface PipelineStep {
  name: string;
  status: string;
  detail?: string;
}

interface Props {
  steps: PipelineStep[];
  isPending: boolean;
  className?: string;
}

/**
 * Generation Status Card — shows real-time pipeline progress.
 * Each step shows: icon, name, status, optional detail.
 * Animated spinner during generation.
 */
export default function GenerationStatusCard({ steps, isPending, className = '' }: Props) {
  if (steps.length === 0 && !isPending) return null;

  const stepIcons: Record<string, string> = {
    success: '✓',
    failed: '✕',
    skipped: '—',
  };

  const stepColors: Record<string, string> = {
    success: 'var(--status-success)',
    failed: 'var(--status-danger)',
    skipped: 'var(--text-tertiary)',
  };

  return (
    <div className={`generation-status-card card ${className}`}>
      <div className="generation-status-card-header">
        {isPending ? (
          <>
            <span className="spinner" />
            <span>Generating your resume...</span>
          </>
        ) : (
          <>
            <span style={{ color: 'var(--status-success)' }}>✓</span>
            <span>Generation complete</span>
          </>
        )}
      </div>

      <div className="generation-status-card-steps">
        {steps.map((step, index) => {
          const icon = step.status === 'success' ? stepIcons.success
            : step.status === 'failed' ? stepIcons.failed
            : stepIcons.skipped;
          const color = stepColors[step.status] || 'var(--text-tertiary)';

          return (
            <div key={index} className="generation-status-card-step">
              <span className="generation-status-card-step-icon" style={{ color }}>
                {isPending && index === steps.length - 1 && step.status !== 'success' && step.status !== 'failed' ? (
                  <span className="spinner" style={{ width: 14, height: 14 }} />
                ) : (
                  icon
                )}
              </span>
              <div className="generation-status-card-step-info">
                <span className="generation-status-card-step-name">{step.name}</span>
                {step.detail && (
                  <span className="generation-status-card-step-detail">{step.detail}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
