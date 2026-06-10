import type { ATSAlignmentReport } from '../types/alignment';
import type { ATSScore } from '../types/resume';

interface ATSCompactScoreCardProps {
  atsScore: ATSScore | null;
  alignmentReport: ATSAlignmentReport | null;
  resumeVersionId?: string | null;
  onOptimizeClick?: () => void;
  compact?: boolean;
}

function scoreColor(score: number): string {
  if (score >= 85) return 'var(--status-success)';
  if (score >= 70) return 'var(--status-warning)';
  return 'var(--status-danger)';
}

function statusText(score: number): string {
  if (score >= 85) return 'Strong match — good ATS readiness';
  if (score >= 70) return 'Good match — review gaps below';
  return 'Needs optimization — see what is missing';
}

function dedupe(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  values.forEach((value) => {
    const cleaned = value.trim();
    const key = cleaned.toLowerCase();
    if (!cleaned || seen.has(key)) return;
    seen.add(key);
    result.push(cleaned);
  });

  return result;
}

function honestyLabel(value: number | undefined, low: string, mid: string, high: string): string {
  if (value === undefined || value === null) return mid;
  if (value >= 85) return high;
  if (value >= 60) return mid;
  return low;
}

export default function ATSCompactScoreCard({
  atsScore,
  alignmentReport,
  resumeVersionId,
  onOptimizeClick,
  compact = false,
}: ATSCompactScoreCardProps) {
  if (!atsScore && !alignmentReport) return null;

  const isStale = resumeVersionId && atsScore?.resume_version_id && resumeVersionId !== atsScore.resume_version_id;
  const overallScore = atsScore?.overall_score ?? alignmentReport?.overall_alignment_percent ?? 0;
  const keywordScore = atsScore?.keyword_score.coverage_percent ?? alignmentReport?.keyword_coverage_percent ?? 0;
  const formatScore = atsScore?.format_score ?? alignmentReport?.formatting_score ?? 0;

  const breakdown = atsScore?.score_breakdown || {};
  
  const kwCoverage = atsScore?.keyword_coverage_score ?? keywordScore;
  const exactJdKeywords = (breakdown.exact_jd_keywords ?? 0) / 0.25;
  const requiredSkills = (breakdown.required_skills ?? 0) / 0.20;
  const responsibility = (breakdown.responsibility ?? 0) / 0.15;
  const titleSeniority = (breakdown.title_seniority ?? 0) / 0.10;
  const evidenceSupported = (breakdown.evidence_supported ?? 0) / 0.10;
  const bulletQuality = (breakdown.bullet_quality ?? 0) / 0.10;
  const pdfParseability = (breakdown.pdf_parseability ?? 0) / 0.05;
  const pageFitStructure = (breakdown.page_fit_structure ?? 0) / 0.05;
  const supportedCoverage = atsScore?.supported_coverage_score ?? 0;
  const fmtReadiness = atsScore?.formatting_readiness_score ?? formatScore;
  const seniorityHonest = atsScore?.seniority_honesty_score ?? 100;
  const valReadiness = atsScore?.validation_readiness_score ?? 100;
  const readabilityWarnCount = atsScore?.readability_warnings_count ?? 0;
  const exportReady = atsScore?.export_ready ?? false;

  const includedKeywords = dedupe([
    ...(alignmentReport?.keywords_included ?? []),
    ...(atsScore?.keyword_score.details.filter((detail) => detail.found).map((detail) => detail.keyword) ?? []),
  ]);
  const missingKeywords = dedupe([
    ...(alignmentReport?.keywords_missing ?? []),
    ...(atsScore?.missing_keywords ?? []),
    ...(atsScore?.keyword_score.details.filter((detail) => !detail.found).map((detail) => detail.keyword) ?? []),
  ]);
  const suggestions = dedupe([
    ...(alignmentReport?.suggestions ?? []),
    ...(atsScore?.recommendations ?? []),
  ]);

  return (
    <div
      className="card"
      style={{
        padding: compact ? 'var(--space-md)' : 'var(--space-lg)',
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border-medium)',
        width: compact ? 'auto' : '100%',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
        <div
          style={{
            minWidth: compact ? 72 : 92,
            textAlign: 'center',
            padding: compact ? '6px 10px' : '10px 14px',
            borderRadius: '8px',
            background: 'var(--bg-glass-strong)',
            border: '1px solid var(--border-medium)',
          }}
        >
          <div style={{ fontSize: compact ? '1.45rem' : '2rem', fontWeight: 700, color: isStale ? 'var(--text-muted)' : scoreColor(overallScore), lineHeight: 1 }}>
            {Math.round(overallScore)}
          </div>
          <div style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', marginTop: '3px' }}>
            {isStale ? 'Stale Match' : 'ATS Match'}
          </div>
        </div>

        <div style={{ minWidth: 180, flex: 1 }}>
          <div style={{ fontWeight: 700, color: isStale ? 'var(--text-muted)' : scoreColor(overallScore) }}>
            {isStale ? 'Resume changed — re-validate' : statusText(overallScore)}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '4px' }}>
            {isStale ? 'Changes detected. Click Validate to update score.' : (
              kwCoverage >= 70
                ? `${Math.round(kwCoverage)}% keyword coverage`
                : `${Math.round(kwCoverage)}% keyword coverage — gap affects score`
            )}
            {!isStale && readabilityWarnCount > 0 && ` · ${readabilityWarnCount} readability ${readabilityWarnCount === 1 ? 'issue' : 'issues'}`}
          </div>
          {!isStale && !exportReady && (
            <div style={{ color: 'var(--status-danger)', fontSize: '0.75rem', marginTop: '2px' }}>
              ⚠ Export blocked — fix validation issues
            </div>
          )}
          {isStale && (
            <div style={{ color: 'var(--status-warning)', fontSize: '0.75rem', marginTop: '2px' }}>
              ⚠ Score is out of sync with edits
            </div>
          )}
        </div>

        {onOptimizeClick && (
          <button className="btn btn-secondary btn-sm" onClick={onOptimizeClick}>
            Optimize
          </button>
        )}
      </div>

      {/* Honest sub-scores grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(72px, 1fr))' : 'repeat(auto-fit, minmax(100px, 1fr))',
          gap: '8px',
          marginTop: 'var(--space-md)',
        }}
      >
        <HonestMetric label="Keyword coverage" value={kwCoverage} subtitle="Match across resume" />
        <HonestMetric label="Evidence backed" value={supportedCoverage} subtitle="Supported by profile" />
        <HonestMetric label="Formatting" value={fmtReadiness} subtitle="Structure & sections" />
        <HonestMetric
          label="Seniority honesty"
          value={seniorityHonest}
          subtitle={honestyLabel(seniorityHonest, 'Title inflated', 'Accurate level', 'Honest title')}
        />
        <HonestMetric
          label="Export readiness"
          value={valReadiness}
          subtitle={exportReady ? 'Ready to export' : 'Blocking issues'}
        />
      </div>

      {/* Compact metric bars for legacy compatibility */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(72px, 1fr))' : 'repeat(auto-fit, minmax(110px, 1fr))',
          gap: '8px',
          marginTop: 'var(--space-md)',
        }}
      >
        <Metric label="JD Keywords" value={exactJdKeywords} />
        <Metric label="Required Skills" value={requiredSkills} />
        <Metric label="Responsibilities" value={responsibility} />
        <Metric label="Title Match" value={titleSeniority} />
        <Metric label="Evidence Truth" value={evidenceSupported} />
        <Metric label="Bullet Quality" value={bulletQuality} />
        <Metric label="Parseability" value={pdfParseability} />
        <Metric label="Page Structure" value={pageFitStructure} />
      </div>

      {/* Evidence-aware keyword details */}
      {atsScore && (atsScore.matched_supported_keywords?.length || atsScore.unsupported_jd_keywords?.length || atsScore.learning_focus_keywords?.length) && (
        <div style={{ marginTop: 'var(--space-md)' }}>
          <details>
            <summary style={{ cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.82rem', fontWeight: 600 }}>
              Evidence-aware keyword review
            </summary>
            <div style={{ marginTop: 'var(--space-sm)', display: 'grid', gap: 'var(--space-sm)' }}>
              {atsScore.matched_supported_keywords && atsScore.matched_supported_keywords.length > 0 && (
                <KeywordGroup title="Supported matches" items={atsScore.matched_supported_keywords.slice(0, 15)} variant="found" />
              )}
              {atsScore.unsupported_jd_keywords && atsScore.unsupported_jd_keywords.length > 0 && (
                <KeywordGroup title="Unsupported (not claimed in resume)" items={atsScore.unsupported_jd_keywords.slice(0, 10)} variant="missing" />
              )}
              {atsScore.learning_focus_keywords && atsScore.learning_focus_keywords.length > 0 && (
                <KeywordGroup title="Learning focus (honest adjacent terms)" items={atsScore.learning_focus_keywords.slice(0, 10)} variant="found" />
              )}
            </div>
          </details>
        </div>
      )}

      <div style={{ display: 'grid', gap: '8px', marginTop: 'var(--space-md)' }}>
        <KeywordDetails title="View keyword details" included={includedKeywords} missing={missingKeywords} />
        <CollapsedList title="Suggestions" items={suggestions} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div style={{ background: 'var(--bg-glass)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '8px' }}>
      <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{Math.round(value)}%</div>
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.68rem', marginTop: '2px' }}>{label}</div>
    </div>
  );
}

function HonestMetric({ label, value, subtitle }: { label: string; value: number; subtitle?: string }) {
  const color = scoreColor(value);
  return (
    <div style={{
      background: 'var(--bg-glass)',
      border: '1px solid var(--border-subtle)',
      borderRadius: '8px',
      padding: '8px',
      position: 'relative',
    }}>
      <div style={{ fontWeight: 700, fontSize: '0.95rem', color }}>{Math.round(value)}%</div>
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.68rem', marginTop: '2px' }}>{label}</div>
      {subtitle && (
        <div style={{ color: 'var(--text-muted)', fontSize: '0.62rem', marginTop: '1px', fontStyle: 'italic' }}>
          {subtitle}
        </div>
      )}
    </div>
  );
}

function KeywordDetails({
  title,
  included,
  missing,
}: {
  title: string;
  included: string[];
  missing: string[];
}) {
  if (included.length === 0 && missing.length === 0) return null;

  return (
    <details>
      <summary style={{ cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.82rem', fontWeight: 600 }}>
        {title}
      </summary>
      <div style={{ marginTop: 'var(--space-sm)', display: 'grid', gap: 'var(--space-sm)' }}>
        <KeywordGroup title="Included keywords" items={included.slice(0, 20)} variant="found" />
        <KeywordGroup title="Missing keywords" items={missing.slice(0, 20)} variant="missing" />
      </div>
    </details>
  );
}

function KeywordGroup({ title, items, variant }: { title: string; items: string[]; variant: 'found' | 'missing' }) {
  if (items.length === 0) return null;

  return (
    <div>
      <div className="form-label" style={{ marginBottom: 'var(--space-xs)' }}>{title}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
        {items.map((item) => (
          <span key={item} className={`keyword-tag ${variant === 'found' ? 'keyword-found' : 'keyword-missing'}`}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function CollapsedList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;

  return (
    <details>
      <summary style={{ cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.82rem', fontWeight: 600 }}>
        {title}
      </summary>
      <div style={{ marginTop: 'var(--space-sm)' }}>
        {items.slice(0, 6).map((item) => (
          <div key={item} style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginBottom: '6px' }}>
            {item}
          </div>
        ))}
      </div>
    </details>
  );
}
