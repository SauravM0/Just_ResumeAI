import { useNavigate } from 'react-router-dom';
import type { ATSScore } from '../types/resume';
import type { ATSAlignmentReport } from '../types/alignment';

interface AlignmentMetricsPanelProps {
  alignmentReport: ATSAlignmentReport | null;
  atsScore: ATSScore | null;
}

export default function AlignmentMetricsPanel({ alignmentReport, atsScore }: AlignmentMetricsPanelProps) {
  const navigate = useNavigate();

  if (!alignmentReport && !atsScore) {
    return null;
  }

  const getScoreColor = (score: number): string => {
    if (score >= 80) return 'var(--status-success)';
    if (score >= 60) return 'var(--status-warning)';
    return 'var(--status-danger)';
  };

  const getScoreBg = (score: number): string => {
    if (score >= 80) return 'rgba(34, 197, 94, 0.1)';
    if (score >= 60) return 'rgba(234, 179, 8, 0.1)';
    return 'rgba(239, 68, 68, 0.1)';
  };

  const overallScore = atsScore?.overall_score ?? alignmentReport?.overall_alignment_percent ?? 0;
  const keywordCoverage = atsScore?.keyword_score.coverage_percent ?? alignmentReport?.keyword_coverage_percent ?? 0;
  const requiredSkillsCoverage = atsScore?.skill_score.required_coverage_percent ?? 0;
  const responsibilityCoverage = atsScore?.responsibility_score ?? 0;
  const formattingScore = atsScore?.format_score ?? alignmentReport?.formatting_score ?? 100;

  return (
    <div className="card" style={{ 
      marginBottom: 'var(--space-xl)', 
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border-color)',
      padding: 'var(--space-md)'
    }}>
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        marginBottom: 'var(--space-md)',
        flexWrap: 'wrap',
        gap: 'var(--space-sm)'
      }}>
        <div className="card-title" style={{ marginBottom: 0 }}>📊 ATS Alignment</div>
        
        {overallScore < 80 && (
          <button 
            className="btn btn-secondary btn-sm"
            onClick={() => navigate('/jd')}
            style={{ fontSize: '0.8rem' }}
          >
            🔄 Regenerate for higher score
          </button>
        )}
        {overallScore >= 90 && (
          <div style={{ 
            color: 'var(--status-success)', 
            fontWeight: 600,
            fontSize: '0.85rem'
          }}>
            ✓ Ready for PDF generation
          </div>
        )}
      </div>

      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', 
        gap: 'var(--space-sm)',
        marginBottom: 'var(--space-md)'
      }}>
        <ScoreIndicator 
          label="Overall" 
          value={Math.round(overallScore)} 
          color={getScoreColor(overallScore)}
          bg={getScoreBg(overallScore)}
        />
        <ScoreIndicator 
          label="Keywords" 
          value={Math.round(keywordCoverage)} 
          color={getScoreColor(keywordCoverage)}
          bg={getScoreBg(keywordCoverage)}
        />
        <ScoreIndicator 
          label="Required Skills" 
          value={Math.round(requiredSkillsCoverage)} 
          color={getScoreColor(requiredSkillsCoverage)}
          bg={getScoreBg(requiredSkillsCoverage)}
        />
        <ScoreIndicator 
          label="Responsibility" 
          value={Math.round(responsibilityCoverage)} 
          color={getScoreColor(responsibilityCoverage)}
          bg={getScoreBg(responsibilityCoverage)}
        />
        <ScoreIndicator 
          label="Format" 
          value={Math.round(formattingScore)} 
          color={getScoreColor(formattingScore)}
          bg={getScoreBg(formattingScore)}
        />
      </div>

      {alignmentReport && (
        <>
          {alignmentReport.keywords_included.length > 0 && (
            <div style={{ marginBottom: 'var(--space-sm)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                Included Keywords
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                {alignmentReport.keywords_included.slice(0, 15).map((keyword) => (
                  <span 
                    key={keyword} 
                    style={{
                      background: 'rgba(34, 197, 94, 0.15)',
                      color: 'var(--status-success)',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                    }}
                  >
                    {keyword}
                  </span>
                ))}
              </div>
            </div>
          )}

          {alignmentReport.keywords_missing.length > 0 && (
            <div style={{ marginBottom: 'var(--space-sm)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                Missing Keywords
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                {alignmentReport.keywords_missing.slice(0, 12).map((keyword) => (
                  <span 
                    key={keyword} 
                    style={{
                      background: 'rgba(239, 68, 68, 0.15)',
                      color: 'var(--status-danger)',
                      padding: '2px 8px',
                      borderRadius: '4px',
                      fontSize: '0.75rem',
                    }}
                  >
                    {keyword}
                  </span>
                ))}
              </div>
            </div>
          )}

          {(alignmentReport.suggestions.length > 0 || (atsScore?.recommendations && atsScore.recommendations.length > 0)) && (
            <div style={{ marginTop: 'var(--space-sm)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
                Suggestions
              </div>
              {[
                ...(alignmentReport.suggestions || []),
                ...(atsScore?.recommendations || [])
              ].slice(0, 5).map((suggestion, i) => (
                <div 
                  key={i} 
                  style={{ 
                    fontSize: '0.8rem', 
                    color: 'var(--text-secondary)',
                    marginBottom: '4px',
                    paddingLeft: '8px',
                    borderLeft: '2px solid var(--border-color)'
                  }}
                >
                  → {suggestion}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {atsScore?.missing_keywords && atsScore.missing_keywords.length > 0 && !alignmentReport && (
        <div style={{ marginTop: 'var(--space-sm)' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '4px' }}>
            Missing Keywords (from scoring)
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
            {atsScore.missing_keywords.slice(0, 10).map((keyword) => (
              <span 
                key={keyword} 
                style={{
                  background: 'rgba(239, 68, 68, 0.15)',
                  color: 'var(--status-danger)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  fontSize: '0.75rem',
                }}
              >
                {keyword}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ScoreIndicator({ 
  label, 
  value, 
  color, 
  bg 
}: { 
  label: string; 
  value: number; 
  color: string;
  bg: string;
}) {
  return (
    <div style={{ 
      textAlign: 'center',
      padding: 'var(--space-sm)',
      background: bg,
      borderRadius: '8px',
      border: '1px solid var(--border-color)'
    }}>
      <div style={{ 
        fontSize: '1.5rem', 
        fontWeight: 700, 
        color,
        lineHeight: 1
      }}>
        {value}
      </div>
      <div style={{ 
        fontSize: '0.7rem', 
        color: 'var(--text-secondary)',
        marginTop: '2px'
      }}>
        {label}
      </div>
    </div>
  );
}