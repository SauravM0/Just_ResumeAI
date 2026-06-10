import type { ATSScore } from '../../types/resume';

interface Props {
  atsScore: ATSScore | null;
  overallScore: number | null;
  onReOptimize: () => void;
  onFixSection: (section: string) => void;
  className?: string;
}

export default function LowScoreCTA({
  atsScore,
  overallScore,
  onReOptimize,
  onFixSection,
  className = '',
}: Props) {
  const needsImprovement = overallScore !== null && overallScore < 85;
  if (!needsImprovement) return null;

  const kwCoverage = Math.round(atsScore?.keyword_coverage_score ?? atsScore?.keyword_score?.coverage_percent ?? 0);
  const bulletQuality = Math.round(atsScore?.bullet_quality_score ?? 0);
  const skillCoverage = Math.round(atsScore?.skill_score?.required_coverage_percent ?? 0);
  const criticalMissing = atsScore?.keyword_score?.critical_missing ?? [];
  const missingKeywords = atsScore?.missing_keywords ?? [];
  const allMissing = criticalMissing.length > 0 ? criticalMissing : missingKeywords;

  const actions: { text: string; section: string }[] = [];

  if (kwCoverage < 70 && allMissing.length > 0) {
    const topMissing = allMissing.slice(0, 3).join(', ');
    actions.push({
      text: `Add these ${allMissing.length > 3 ? 'top ' : ''}missing keywords to your skills section: ${topMissing}${allMissing.length > 3 ? ' and more' : ''}`,
      section: 'skills',
    });
  }

  if (bulletQuality < 70) {
    actions.push({
      text: 'Strengthen your weakest bullets with measurable outcomes and metrics',
      section: 'experience',
    });
  }

  if (skillCoverage < 80 && allMissing.length > 0) {
    const firstMissing = allMissing[0];
    actions.push({
      text: `Add "${firstMissing}" to your skills — it appears in the job description`,
      section: 'skills',
    });
  }

  if (actions.length === 0) return null;

  return (
    <div className={`card ${className}`} style={{
      borderLeft: '3px solid var(--status-warning)',
      borderColor: 'var(--status-warning)',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 'var(--space-md)',
        marginBottom: 'var(--space-md)',
      }}>
        <div style={{
          width: 40,
          height: 40,
          borderRadius: 'var(--radius-md)',
          background: 'var(--status-warning-bg)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '1.2rem',
          flexShrink: 0,
        }}>
          🚀
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: '1rem', marginBottom: '2px' }}>
            Improve your score to 90+
          </div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
            Specific actions you can take right now:
          </div>
        </div>
      </div>

      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-sm)',
        marginBottom: 'var(--space-md)',
      }}>
        {actions.map((action, idx) => (
          <div
            key={idx}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 'var(--space-sm)',
              padding: 'var(--space-sm) var(--space-md)',
              background: 'var(--bg-glass)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div style={{
              width: 24,
              height: 24,
              borderRadius: 'var(--radius-full)',
              background: 'var(--accent-gradient-soft)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '0.7rem',
              fontWeight: 700,
              color: 'var(--text-accent)',
              flexShrink: 0,
            }}>
              {idx + 1}
            </div>
            <div style={{ flex: 1, fontSize: '0.85rem', lineHeight: 1.4, minWidth: 0 }}>
              {action.text}
            </div>
            <button
              className="btn btn-sm btn-secondary"
              onClick={() => onFixSection(action.section)}
              style={{ flexShrink: 0 }}
            >
              Fix this
            </button>
          </div>
        ))}
      </div>

      <button
        className="btn btn-primary"
        onClick={onReOptimize}
        style={{ width: '100%' }}
      >
        Optimize to 100% ATS
      </button>
    </div>
  );
}
