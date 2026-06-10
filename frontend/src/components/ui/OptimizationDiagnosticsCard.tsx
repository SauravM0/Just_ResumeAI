import type { ResumeOptimizationResult } from '../../types/resume';

interface Props {
  optimization: ResumeOptimizationResult | null;
  className?: string;
}

export default function OptimizationDiagnosticsCard({ optimization, className = '' }: Props) {
  if (!optimization || !optimization.diagnostics || optimization.diagnostics.length === 0) {
    return null;
  }

  const { diagnostics, reached_target, target_score, score_explanation } = optimization;
  const lastAttempt = diagnostics[diagnostics.length - 1];
  const initialScore = Math.round(diagnostics[0].json_score.overall_score);
  const finalScore = Math.round(lastAttempt.pdf_text_score?.overall_score ?? lastAttempt.json_score.overall_score);

  return (
    <div className={`optimization-diagnostics card ${className}`}>
      <div className="optimization-header">
        <div className="optimization-icon">
          {reached_target ? '🚀' : '📈'}
        </div>
        <div className="optimization-info">
          <h4 className="optimization-title">
            Auto-Optimization History
          </h4>
          <p className="optimization-subtitle">
            {reached_target 
              ? `Target ATS score of ${target_score}+ achieved honestly.`
              : `Optimized as much as possible using available profile evidence.`}
          </p>
        </div>
      </div>

      <div className="optimization-summary-metrics">
        <div className="opt-metric">
          <span className="opt-metric-label">Initial Score</span>
          <span className="opt-metric-value">{initialScore}</span>
        </div>
        <div className="opt-metric">
          <span className="opt-metric-label">Final Score</span>
          <span className="opt-metric-value text-success">{finalScore}</span>
        </div>
        <div className="opt-metric">
          <span className="opt-metric-label">Attempts</span>
          <span className="opt-metric-value">{optimization.attempts_used}</span>
        </div>
      </div>

      <details className="optimization-history-details">
        <summary>View detailed optimization log</summary>
        <div className="optimization-timeline">
          {diagnostics.map((attempt) => (
            <div key={attempt.attempt} className="optimization-step">
              <div className="step-number">Attempt {attempt.attempt}</div>
              <div className="step-content">
                <div className="step-scores">
                  <span className="badge">JSON: {Math.round(attempt.json_score.overall_score)}</span>
                  {attempt.pdf_text_score && (
                    <span className="badge badge-success">PDF Text: {Math.round(attempt.pdf_text_score.overall_score)}</span>
                  )}
                </div>
                {attempt.repair_actions.length > 0 && (
                  <ul className="step-actions">
                    {attempt.repair_actions.map((action, i) => (
                      <li key={i}>{action}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ))}
        </div>
      </details>

      {score_explanation.length > 0 && (
        <div className="optimization-explanation">
          <h5 className="explanation-title">Optimization Notes</h5>
          <ul className="explanation-list">
            {score_explanation.map((reason, i) => (
              <li key={i} className={reason.includes('Cannot reach 90+') ? 'text-danger fw-bold' : ''}>
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
