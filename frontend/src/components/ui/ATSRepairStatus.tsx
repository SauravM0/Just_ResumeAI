import type { ATSScore } from '../../types/resume';

interface Props {
  atsScore: ATSScore | null;
  resumeVersionId?: string | null;
  previousScore?: number | null;
  className?: string;
}

export default function ATSRepairStatus({ atsScore, resumeVersionId, previousScore, className = '' }: Props) {
  if (!atsScore) return null;

  const isStale = resumeVersionId && atsScore.resume_version_id && resumeVersionId !== atsScore.resume_version_id;
  const overallScore = Math.round(atsScore.overall_score ?? 0);
  const criticalMissing = atsScore.keyword_score?.critical_missing ?? [];
  const matchedCount = atsScore.keyword_score?.matched_keywords ?? 0;
  const stuffingWarnings = atsScore.stuffing_warnings ?? [];
  const scoreImproved = previousScore !== undefined && previousScore !== null && overallScore > previousScore;
  const scoreDelta = previousScore !== undefined && previousScore !== null ? overallScore - Math.round(previousScore) : 0;

  const repairStatus = criticalMissing.length === 0
    ? 'complete'
    : criticalMissing.length <= 3
      ? 'partial'
      : 'needs-attention';

  return (
    <div className={`ats-repair-status card ${className}`}>
      <div className="ats-repair-header">
        <div className="ats-repair-icon">
          {repairStatus === 'complete' ? '✅' : repairStatus === 'partial' ? '⚡' : '🔧'}
        </div>
        <div className="ats-repair-info">
          <h4 className="ats-repair-title">
            ATS Keyword Repair Status {isStale && <span className="badge badge-warning">Stale</span>}
          </h4>
          <p className="ats-repair-subtitle">
            {isStale
              ? 'Resume content has changed. Re-validate to update status.'
              : repairStatus === 'complete'
                ? 'All critical keywords are covered in your resume.'
                : repairStatus === 'partial'
                  ? `Most critical keywords are covered. ${criticalMissing.length} still missing.`
                  : `${criticalMissing.length} critical keywords need attention.`}
          </p>
        </div>
      </div>

      <div className="ats-repair-metrics">
        <div className="ats-repair-metric">
          <div className="ats-repair-metric-value">{matchedCount}</div>
          <div className="ats-repair-metric-label">Keywords matched</div>
        </div>
        <div className="ats-repair-metric">
          <div className={`ats-repair-metric-value ${criticalMissing.length > 0 ? 'text-warning' : 'text-success'}`}>
            {criticalMissing.length}
          </div>
          <div className="ats-repair-metric-label">Critical missing</div>
        </div>
        <div className="ats-repair-metric">
          <div className={`ats-repair-metric-value ${overallScore >= 80 ? 'text-success' : overallScore >= 65 ? 'text-warning' : 'text-danger'}`}>
            {overallScore}
          </div>
          <div className="ats-repair-metric-label">ATS Score</div>
        </div>
        {scoreImproved && (
          <div className="ats-repair-metric">
            <div className="ats-repair-metric-value text-success">+{scoreDelta}</div>
            <div className="ats-repair-metric-label">Score improved</div>
          </div>
        )}
      </div>

      {criticalMissing.length > 0 && (
        <div className="ats-repair-missing">
          <h5 className="ats-repair-missing-title">Missing critical keywords</h5>
          <div className="ats-repair-missing-tags">
            {criticalMissing.slice(0, 10).map((kw) => (
              <span key={kw} className="keyword-tag keyword-missing">{kw}</span>
            ))}
            {criticalMissing.length > 10 && (
              <span className="keyword-tag keyword-missing">+{criticalMissing.length - 10} more</span>
            )}
          </div>
          <p className="ats-repair-missing-hint">
            These keywords are important for this role. Consider adding them to your skills or summary section.
          </p>
        </div>
      )}

      {stuffingWarnings.length > 0 && (
        <div className="warning-banner warning-warn" style={{ marginTop: 'var(--space-md)' }}>
          <span>⚠️</span>
          <div>
            <strong>Keyword density warning</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              Some keywords appear too frequently. This may trigger ATS filters.
            </p>
          </div>
        </div>
      )}

      {repairStatus === 'complete' && (
        <div className="ats-repair-success" style={{ marginTop: 'var(--space-md)' }}>
          <span className="badge badge-success">✓ Optimized for this JD</span>
          <p style={{ margin: 'var(--space-xs) 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Your resume covers all critical keywords from this job description.
          </p>
        </div>
      )}
    </div>
  );
}
