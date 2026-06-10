import type { ATSScore } from '../../types/resume';

interface Props {
  atsScore: ATSScore | null;
  targetPages: number;
  resumeVersionId?: string | null;
  pageCount?: number;
  finalPdfParseStatus?: string;
  className?: string;
}

/**
 * ATS Feedback Card — Honest, transparent scoring breakdown.
 *
 * Shows what is matched, what is missing, what is unsupported, and what is risky.
 * Never presents false confidence — each sub-score is labeled with honest context.
 */
export default function ATSFeedbackCard({ atsScore, targetPages, resumeVersionId, pageCount, finalPdfParseStatus, className = '' }: Props) {
  if (!atsScore) return null;

  const isStale = resumeVersionId && atsScore.resume_version_id && resumeVersionId !== atsScore.resume_version_id;
  const overallScore = Math.round(atsScore.overall_score ?? 0);
  const scoreTier = isStale ? 'stale' : (overallScore >= 85 ? 'strong' : overallScore >= 70 ? 'good' : 'needs-work');
  const scoreColor = isStale ? 'var(--text-muted)' : (scoreTier === 'strong' ? 'var(--status-success)' : scoreTier === 'good' ? 'var(--status-warning)' : 'var(--status-danger)');
  const scoreLabel = isStale ? 'Score is stale — re-validate' : (scoreTier === 'strong' ? 'Strong match' : scoreTier === 'good' ? 'Good match — review gaps below' : 'Needs optimization — see what is missing');

  // Legacy fields
  const missingKeywords = atsScore.missing_keywords ?? [];
  const criticalMissing = atsScore.keyword_score?.critical_missing ?? [];
  const matchedCount = atsScore.keyword_score?.matched_keywords ?? 0;

  // Truth/evidence keywords
  const supportedMatches = atsScore.matched_supported_keywords ?? [];
  const unsupportedKeywords = atsScore.unsupported_jd_keywords ?? [];
  const learningFocusKeywords = atsScore.learning_focus_keywords ?? [];
  const stuffingWarnings = atsScore.stuffing_warnings ?? [];

  // Honest sub-scores
  const kwCoverage = atsScore.keyword_coverage_score ?? atsScore.keyword_score?.coverage_percent ?? 0;
  const supportedCoverage = atsScore.supported_coverage_score ?? 0;
  const fmtReadiness = atsScore.formatting_readiness_score ?? atsScore.format_score ?? 0;
  const seniorityHonest = atsScore.seniority_honesty_score ?? 100;
  const valReadiness = atsScore.validation_readiness_score ?? 100;
  const readabilityWarnCount = atsScore.readability_warnings_count ?? 0;
  const exportReady = atsScore.export_ready ?? false;

  // Page / PDF status
  const pageStatus = pageCount !== undefined && pageCount !== null
    ? (pageCount <= targetPages ? 'fits' : 'overflow')
    : 'unknown';
  const pdfStatus = finalPdfParseStatus || atsScore.final_pdf_parse_status || 'unknown';

  // Seniority honesty label
  const seniorityLabel = seniorityHonest >= 90
    ? 'Title accurately reflects seniority'
    : seniorityHonest >= 60
      ? 'Seniority slightly optimistic'
      : 'Title may overstate seniority';

  return (
    <div className={`ats-feedback-card card ${className}`} style={{ borderLeft: `3px solid ${scoreColor}` }}>
      {/* Header: Score + Status */}
      <div className="ats-feedback-header">
        <div className="ats-feedback-score-ring" style={{ borderColor: scoreColor }}>
          <span className="ats-feedback-score-value" style={{ color: scoreColor }}>{overallScore}</span>
          <span className="ats-feedback-score-label">ATS Score</span>
        </div>

        <div className="ats-feedback-status">
          <div className="ats-feedback-status-title" style={{ color: scoreColor }}>{scoreLabel}</div>
          <div className="ats-feedback-status-desc">
            {matchedCount} keyword{matchedCount !== 1 ? 's' : ''} matched
            {missingKeywords.length > 0 && ` \u00B7 ${missingKeywords.length} missing`}
            {readabilityWarnCount > 0 && ` \u00B7 ${readabilityWarnCount} readability ${readabilityWarnCount === 1 ? 'issue' : 'issues'}`}
          </div>

          {/* Status badges */}
          <div className="ats-feedback-badges">
            {scoreTier === 'strong' && (
              <span className="badge badge-success">\u2713 Optimized for this JD</span>
            )}
            {exportReady && (
              <span className="badge badge-success">\u2713 Ready to export</span>
            )}
            {!exportReady && valReadiness < 80 && (
              <span className="badge badge-warning">\u26A0 Export blocked</span>
            )}
            {pdfStatus === 'success' && (
              <span className="badge badge-info">PDF parsed</span>
            )}
            {pageStatus === 'fits' && pageCount !== undefined && (
              <span className="badge badge-neutral">{pageCount}/{targetPages} page{pageCount > 1 ? 's' : ''}</span>
            )}
            {pageStatus === 'overflow' && (
              <span className="badge badge-warning">{pageCount}/{targetPages} pages \u2014 compressed</span>
            )}
            {stuffingWarnings.length > 0 && (
              <span className="badge badge-warning">Keyword density flagged</span>
            )}
          </div>
        </div>
      </div>

      {/* Honest sub-scores grid */}
      <div className="ats-feedback-subscore-grid" style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
        gap: '8px',
        margin: 'var(--space-md) 0',
      }}>
        <SubScoreCard label="Keyword Coverage" value={kwCoverage} detail="Raw JD keyword match across sections" />
        <SubScoreCard label="Evidence Backed" value={supportedCoverage} detail="Verified by your profile skills" />
        <SubScoreCard label="Formatting" value={fmtReadiness} detail="Section structure and completeness" />
        <SubScoreCard
          label="Seniority Honesty"
          value={seniorityHonest}
          detail={seniorityLabel}
          detailColor={seniorityHonest < 70 ? 'var(--status-danger)' : undefined}
        />
        <SubScoreCard
          label="Export Readiness"
          value={valReadiness}
          detail={exportReady ? 'Passes all validation checks' : 'Blocking issues found'}
          detailColor={!exportReady ? 'var(--status-danger)' : undefined}
        />
      </div>

      {/* Legacy metric bars */}
      <div className="ats-feedback-metrics">
        <MetricBar label="Required Skills" value={atsScore.skill_score?.required_coverage_percent ?? 0} />
        <MetricBar label="Responsibilities" value={atsScore.responsibility_score ?? 0} />
        <MetricBar label="Format" value={atsScore.format_score ?? 0} />
        <MetricBar label="Title Match" value={atsScore.title_alignment_score ?? 0} />
      </div>

      {/* Score notes / warnings */}
      {(atsScore.warnings ?? []).length > 0 && (
        <details className="ats-feedback-details" open={!exportReady}>
          <summary className="ats-feedback-details-summary">Score notes</summary>
          <div className="ats-feedback-details-content">
            {(atsScore.warnings ?? []).slice(0, 5).map((warning) => (
              <p key={warning} className="ats-feedback-missing-hint" style={{
                color: warning.toLowerCase().includes('block') || warning.toLowerCase().includes('cap')
                  ? 'var(--status-danger)' : 'var(--text-secondary)',
              }}>{warning}</p>
            ))}
          </div>
        </details>
      )}

      {/* Missing Critical Keywords — actionable */}
      {criticalMissing.length > 0 && (
        <div className="ats-feedback-missing">
          <div className="ats-feedback-missing-title">
            <span className="ats-feedback-missing-icon">{'\u26A0'}</span>
            Missing critical keywords
          </div>
          <div className="ats-feedback-missing-tags">
            {criticalMissing.slice(0, 12).map((kw) => (
              <span key={kw} className="keyword-tag keyword-missing">{kw}</span>
            ))}
            {criticalMissing.length > 12 && (
              <span className="keyword-tag keyword-missing">+{criticalMissing.length - 12} more</span>
            )}
          </div>
          <p className="ats-feedback-missing-hint" style={{ color: 'var(--status-danger)', fontWeight: 500 }}>
            These JD keywords are missing from your resume. Adding them to your skills or
            summary is the fastest way to improve your ATS score.
          </p>
        </div>
      )}

      {/* Evidence-aware keyword review */}
      {(supportedMatches.length > 0 || unsupportedKeywords.length > 0 || learningFocusKeywords.length > 0) && (
        <details className="ats-feedback-details" open={unsupportedKeywords.length > 0}>
          <summary className="ats-feedback-details-summary">
            Evidence-aware keyword review
          </summary>
          <div className="ats-feedback-details-content">
            {supportedMatches.length > 0 && (
              <KeywordTags title="Supported matches" items={supportedMatches} variant="found" />
            )}
            {learningFocusKeywords.length > 0 && (
              <KeywordTags title="Learning focus" items={learningFocusKeywords} variant="found" />
            )}
            {unsupportedKeywords.length > 0 && (
              <>
                <KeywordTags title="Unsupported JD keywords" items={unsupportedKeywords} variant="missing" />
                <p className="ats-feedback-missing-hint" style={{ color: 'var(--status-warning)' }}>
                  These JD terms are not supported by your profile evidence. The resume honestly
                  avoids claiming hands-on experience with them.
                </p>
              </>
            )}
          </div>
        </details>
      )}

      {/* Matched Keywords — expandable */}
      {matchedCount > 0 && (
        <details className="ats-feedback-details">
          <summary className="ats-feedback-details-summary">
            View {matchedCount} matched keyword{matchedCount !== 1 ? 's' : ''}
          </summary>
          <div className="ats-feedback-details-content">
            <div className="ats-feedback-matched-tags">
              {(atsScore.keyword_score?.details ?? [])
                .filter((d) => d.found)
                .slice(0, 30)
                .map((d) => (
                  <span key={d.keyword} className="keyword-tag keyword-found">{d.keyword}</span>
                ))}
            </div>
          </div>
        </details>
      )}

      {/* Seniority honesty note */}
      {seniorityHonest < 80 && (
        <div className="ats-feedback-missing" style={{ borderLeft: '3px solid var(--status-warning)' }}>
          <div className="ats-feedback-missing-title">
            <span className="ats-feedback-missing-icon">{'\u26A0'}</span>
            Seniority honesty notice
          </div>
          <p className="ats-feedback-missing-hint" style={{ color: 'var(--status-warning)' }}>
            The resume title may overstate your seniority. ATS systems and recruiters
            penalize inflated titles. Consider adjusting to more accurately reflect
            your experience level.
          </p>
        </div>
      )}

      {/* Readability issues */}
      {readabilityWarnCount > 0 && (
        <details className="ats-feedback-details">
          <summary className="ats-feedback-details-summary">
            {readabilityWarnCount} readability {readabilityWarnCount === 1 ? 'issue' : 'issues'} found
          </summary>
          <div className="ats-feedback-details-content">
            {(atsScore.readability_score?.issues ?? []).slice(0, 8).map((issue) => (
              <p key={issue} className="ats-feedback-missing-hint" style={{ color: 'var(--text-secondary)' }}>
                {'\u2022'} {issue}
              </p>
            ))}
          </div>
        </details>
      )}

      {/* Score breakdown */}
      {atsScore.score_breakdown && (
        <details className="ats-feedback-details">
          <summary className="ats-feedback-details-summary">
            View detailed score breakdown
          </summary>
          <div className="ats-feedback-details-content">
            <div className="ats-feedback-breakdown">
              {Object.entries(atsScore.score_breakdown).map(([key, value]) => (
                <div key={key} className="ats-feedback-breakdown-row">
                  <span className="ats-feedback-breakdown-label">{formatBreakdownLabel(key)}</span>
                  <span className="ats-feedback-breakdown-value">
                    {typeof value === 'number' ? `${Math.round(value * 100)}%` : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </details>
      )}

      {/* Recommendations */}
      {(atsScore.recommendations ?? []).length > 0 && (
        <details className="ats-feedback-details">
          <summary className="ats-feedback-details-summary">
            Recommendations ({atsScore.recommendations.length})
          </summary>
          <div className="ats-feedback-details-content">
            {(atsScore.recommendations ?? []).slice(0, 5).map((rec) => (
              <p key={rec} className="ats-feedback-missing-hint" style={{ color: 'var(--text-secondary)' }}>
                {'\u2022'} {rec}
              </p>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function SubScoreCard({ label, value, detail, detailColor }: {
  label: string;
  value: number;
  detail?: string;
  detailColor?: string;
}) {
  const rounded = Math.round(value);
  const color = rounded >= 85 ? 'var(--status-success)' : rounded >= 60 ? 'var(--status-warning)' : 'var(--status-danger)';

  return (
    <div style={{
      background: 'var(--bg-glass-strong)',
      border: '1px solid var(--border-subtle)',
      borderRadius: '8px',
      padding: '10px',
      textAlign: 'center',
    }}>
      <div style={{ fontSize: '1.15rem', fontWeight: 700, color, lineHeight: 1.2 }}>{rounded}%</div>
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', marginTop: '3px', fontWeight: 500 }}>{label}</div>
      {detail && (
        <div style={{
          color: detailColor || 'var(--text-muted)',
          fontSize: '0.65rem',
          marginTop: '2px',
          fontStyle: 'italic',
          lineHeight: 1.3,
        }}>
          {detail}
        </div>
      )}
    </div>
  );
}

function KeywordTags({ title, items, variant }: { title: string; items: string[]; variant: 'found' | 'missing' }) {
  return (
    <div style={{ marginBottom: 'var(--space-sm)' }}>
      <div className="form-label" style={{ marginBottom: 'var(--space-xs)' }}>{title}</div>
      <div className="ats-feedback-missing-tags">
        {items.slice(0, 12).map((item) => (
          <span key={item} className={`keyword-tag keyword-${variant}`}>{item}</span>
        ))}
      </div>
    </div>
  );
}

function MetricBar({ label, value }: { label: string; value: number }) {
  const rounded = Math.round(value);
  const color = rounded >= 85 ? 'var(--status-success)' : rounded >= 70 ? 'var(--status-warning)' : 'var(--status-danger)';

  return (
    <div className="ats-feedback-metric">
      <div className="ats-feedback-metric-label">{label}</div>
      <div className="ats-feedback-metric-bar">
        <div
          className="ats-feedback-metric-fill"
          style={{ width: `${rounded}%`, backgroundColor: color }}
        />
      </div>
      <div className="ats-feedback-metric-value" style={{ color }}>{rounded}%</div>
    </div>
  );
}

function formatBreakdownLabel(key: string): string {
  const labels: Record<string, string> = {
    exact_jd_keywords: 'JD Keyword Coverage',
    required_skills: 'Required Skills/Tools',
    responsibility: 'Responsibility Alignment',
    title_seniority: 'Title & Seniority Match',
    evidence_supported: 'Evidence Supported Claims',
    bullet_quality: 'Bullet Quality & Impact',
    pdf_parseability: 'PDF Parseability',
    page_fit_structure: 'Page Fit & Structure',
    content_score: 'Content Quality',
    keyword_score: 'Keyword Match',
    skill_score: 'Skills Coverage',
    format_score: 'Formatting',
    title_alignment_score: 'Title Match',
    responsibility_score: 'Responsibilities',
    quality_score: 'Overall Quality',
    structure_score: 'Structure',
  };
  return labels[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
