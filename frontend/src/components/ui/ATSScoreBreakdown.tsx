import type { ATSScore } from '../../types/resume';

interface Props {
  atsScore: ATSScore | null;
  originalScore?: number | null;
  resumeVersionId?: string | null;
  className?: string;
  onKeywordClick?: (keyword: string) => void;
}

export default function ATSScoreBreakdown({
  atsScore,
  originalScore,
  resumeVersionId,
  className = '',
  onKeywordClick,
}: Props) {
  if (!atsScore) return null;

  const isStale = resumeVersionId && atsScore.resume_version_id && resumeVersionId !== atsScore.resume_version_id;
  const overallScore = Math.round(atsScore.overall_score ?? 0);
  const scoreTier = isStale ? 'stale' : overallScore >= 85 ? 'strong' : overallScore >= 70 ? 'good' : 'needs-work';

  const scoreColor = isStale
    ? 'var(--text-tertiary)'
    : scoreTier === 'strong'
      ? 'var(--status-success)'
      : scoreTier === 'good'
        ? 'var(--status-warning)'
        : 'var(--status-danger)';

  const scoreClass = isStale ? '' : scoreTier === 'strong' ? 'score-high' : scoreTier === 'good' ? 'score-mid' : 'score-low';

  // Extract dimension scores
  const kwCoverage = Math.round(atsScore.keyword_coverage_score ?? atsScore.keyword_score?.coverage_percent ?? 0);
  const skillCoverage = Math.round(atsScore.skill_score?.required_coverage_percent ?? 0);
  const bulletQuality = Math.round(atsScore.bullet_quality_score ?? 0);
  const formatScore = Math.round(atsScore.formatting_readiness_score ?? atsScore.format_score ?? 0);
  const seniorityScore = Math.round(atsScore.seniority_honesty_score ?? 100);
  const validationScore = Math.round(atsScore.validation_readiness_score ?? 100);

  const matchedCount = atsScore.keyword_score?.matched_keywords ?? 0;
  const totalKeywordsCount = atsScore.keyword_score?.total_keywords ?? (matchedCount + (atsScore.missing_keywords?.length ?? 0));

  const criticalMissing = atsScore.keyword_score?.critical_missing ?? [];
  const missingKeywords = atsScore.missing_keywords ?? [];

  const hasBeforeAfter = originalScore !== undefined && originalScore !== null && originalScore > 0;
  const scoreDelta = hasBeforeAfter ? overallScore - Math.round(originalScore!) : 0;

  return (
    <div className={`card ${className}`} style={{ borderLeft: `3px solid ${scoreColor}` }}>
      {/* Top section: big score + before/after */}
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 'var(--space-lg)',
        marginBottom: 'var(--space-lg)',
        flexWrap: 'wrap',
      }}>
        <div className={`score-card`} style={{ flex: '0 0 auto', minWidth: 120, background: 'none', border: 'none', padding: 0 }}>
          <div className={`score-value ${scoreClass}`} style={{ fontSize: '2.8rem' }}>
            {overallScore}
          </div>
          <div className="score-label">ATS Score</div>
          {hasBeforeAfter && (
            <div style={{
              marginTop: 'var(--space-xs)',
              fontSize: '0.82rem',
              color: scoreDelta > 0 ? 'var(--text-success)' : 'var(--text-danger)',
              fontWeight: 600,
            }}>
              {Math.round(originalScore!)} → {overallScore}
              <span style={{ marginLeft: 'var(--space-xs)' }}>
                {scoreDelta > 0 ? `+${scoreDelta}` : scoreDelta}
              </span>
            </div>
          )}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontWeight: 600,
            fontSize: '0.95rem',
            color: scoreColor,
            marginBottom: 'var(--space-xs)',
          }}>
            {isStale
              ? 'Score is stale — re-validate'
              : scoreTier === 'strong'
                ? 'Strong match for this role'
                : scoreTier === 'good'
                  ? 'Good match — review gaps below'
                  : 'Needs optimization'}
          </div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
            {matchedCount} of {totalKeywordsCount || '—'} keywords matched
            {atsScore.readability_warnings_count ? ` · ${atsScore.readability_warnings_count} readability issues` : ''}
          </div>
        </div>
      </div>

      {/* Breakdown grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
        gap: 'var(--space-md)',
        marginBottom: 'var(--space-lg)',
      }}>
        <DimensionBar label="Keyword Coverage" value={kwCoverage} detail={`${matchedCount} of ${totalKeywordsCount} matched`} />
        <DimensionBar label="Required Skills" value={skillCoverage} />
        <DimensionBar label="Bullet Quality" value={bulletQuality} />
        <DimensionBar label="Formatting" value={formatScore} />
        <DimensionBar label="Seniority Honesty" value={seniorityScore} />
        <DimensionBar label="Export Readiness" value={validationScore} />
      </div>

      {/* Missing keywords */}
      {(criticalMissing.length > 0 || missingKeywords.length > 0) && (
        <div style={{
          padding: 'var(--space-md)',
          background: 'var(--status-danger-bg)',
          border: '1px solid rgba(239, 68, 68, 0.15)',
          borderRadius: 'var(--radius-md)',
          marginBottom: 'var(--space-md)',
        }}>
          <div style={{
            fontSize: '0.8rem',
            fontWeight: 600,
            color: 'var(--text-danger)',
            marginBottom: 'var(--space-sm)',
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-xs)',
          }}>
            <span>⚠</span>
            <span>Keywords to add for higher score</span>
          </div>
          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '4px',
          }}>
            {(criticalMissing.length > 0 ? criticalMissing : missingKeywords).slice(0, 12).map((kw) => (
              <button
                key={kw}
                className="keyword-tag keyword-missing"
                onClick={() => onKeywordClick?.(kw)}
                style={{
                  cursor: onKeywordClick ? 'pointer' : 'default',
                  border: 'none',
                  font: 'inherit',
                  fontSize: '0.7rem',
                  transition: 'opacity var(--transition-fast)',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.opacity = '0.8'; }}
                onMouseLeave={(e) => { e.currentTarget.style.opacity = '1'; }}
                title={onKeywordClick ? 'Click to find in resume' : undefined}
              >
                {kw}
              </button>
            ))}
            {(criticalMissing.length > 12 || missingKeywords.length > 12) && (
              <span className="keyword-tag keyword-missing" style={{ border: 'none', background: 'var(--status-danger-bg)' }}>
                +{Math.max(criticalMissing.length, missingKeywords.length) - 12} more
              </span>
            )}
          </div>
          <div style={{
            fontSize: '0.72rem',
            color: 'var(--text-secondary)',
            marginTop: 'var(--space-sm)',
          }}>
            Adding these keywords to your skills or summary is the fastest way to improve your ATS score.
          </div>
        </div>
      )}

      {/* Stale warning */}
      {isStale && (
        <div className="warning-banner warning-warn">
          <span>⚠</span>
          <div>
            <strong>Score out of sync</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              Resume content has changed since this score was calculated. Re-run validation to get an updated score.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function DimensionBar({ label, value, detail }: { label: string; value: number; detail?: string }) {
  const clamped = Math.min(100, Math.max(0, value));
  const color = clamped >= 80 ? 'var(--status-success)' : clamped >= 60 ? 'var(--status-warning)' : 'var(--status-danger)';

  return (
    <div style={{
      padding: 'var(--space-sm)',
      background: 'var(--bg-glass)',
      borderRadius: 'var(--radius-md)',
      border: '1px solid var(--border-subtle)',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 'var(--space-xs)',
      }}>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontWeight: 500 }}>{label}</span>
        <span style={{ fontSize: '0.8rem', fontWeight: 700, color }}>{clamped}%</span>
      </div>
      <div style={{
        height: 6,
        background: 'var(--bg-glass-strong)',
        borderRadius: 'var(--radius-full)',
        overflow: 'hidden',
      }}>
        <div style={{
          height: '100%',
          width: `${clamped}%`,
          background: color,
          borderRadius: 'var(--radius-full)',
          transition: 'width 0.6s ease',
        }} />
      </div>
      {detail && (
        <div style={{ fontSize: '0.65rem', color: 'var(--text-tertiary)', marginTop: 'var(--space-xs)' }}>
          {detail}
        </div>
      )}
    </div>
  );
}
