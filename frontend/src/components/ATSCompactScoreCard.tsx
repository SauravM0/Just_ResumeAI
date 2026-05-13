import type { ATSAlignmentReport } from '../types/alignment';
import type { ATSScore } from '../types/resume';

interface ATSCompactScoreCardProps {
  atsScore: ATSScore | null;
  alignmentReport: ATSAlignmentReport | null;
  onOptimizeClick?: () => void;
  compact?: boolean;
}

function scoreColor(score: number): string {
  if (score >= 85) return 'var(--status-success)';
  if (score >= 70) return 'var(--status-warning)';
  return 'var(--status-danger)';
}

function statusText(score: number): string {
  if (score >= 85) return 'Strong match';
  if (score >= 70) return 'Good match';
  return 'Needs optimization';
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

export default function ATSCompactScoreCard({
  atsScore,
  alignmentReport,
  onOptimizeClick,
  compact = false,
}: ATSCompactScoreCardProps) {
  if (!atsScore && !alignmentReport) return null;

  const overallScore = atsScore?.overall_score ?? alignmentReport?.overall_alignment_percent ?? 0;
  const keywordScore = atsScore?.keyword_score.coverage_percent ?? alignmentReport?.keyword_coverage_percent ?? 0;
  const requiredSkillsScore = atsScore?.skill_score.required_coverage_percent ?? 0;
  const responsibilitiesScore = atsScore?.responsibility_score ?? 0;
  const formatScore = atsScore?.format_score ?? alignmentReport?.formatting_score ?? 0;
  const titleScore = atsScore?.title_alignment_score ?? 0;
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
          <div style={{ fontSize: compact ? '1.45rem' : '2rem', fontWeight: 700, color: scoreColor(overallScore), lineHeight: 1 }}>
            {Math.round(overallScore)}
          </div>
          <div style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', marginTop: '3px' }}>
            ATS Match
          </div>
        </div>

        <div style={{ minWidth: 180, flex: 1 }}>
          <div style={{ fontWeight: 700, color: scoreColor(overallScore) }}>
            {statusText(overallScore)}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '4px' }}>
            Overall ATS Match
          </div>
        </div>

        {onOptimizeClick && (
          <button className="btn btn-secondary btn-sm" onClick={onOptimizeClick}>
            Optimize
          </button>
        )}
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(72px, 1fr))' : 'repeat(auto-fit, minmax(110px, 1fr))',
          gap: '8px',
          marginTop: 'var(--space-md)',
        }}
      >
        <Metric label="Keywords" value={keywordScore} />
        <Metric label="Required Skills" value={requiredSkillsScore} />
        <Metric label="Responsibilities" value={responsibilitiesScore} />
        <Metric label="Format" value={formatScore} />
        <Metric label="Title Match" value={titleScore} />
      </div>

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
