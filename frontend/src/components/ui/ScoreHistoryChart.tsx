interface ScoreHistoryChartProps {
  scoreHistory: number[];
  strategyHistory?: string[];
}

export function ScoreHistoryChart({ scoreHistory, strategyHistory }: ScoreHistoryChartProps) {
  if (!scoreHistory || scoreHistory.length < 2) return null;

  const isMobile = typeof window !== 'undefined' && window.innerWidth < 768;

  if (isMobile) {
    const improvement = scoreHistory[scoreHistory.length - 1] - scoreHistory[0];
    return (
      <div
        className="card"
        style={{
          padding: 'var(--space-md)',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
        }}
      >
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
          Score improved by +{improvement.toFixed(0)} points across {scoreHistory.length} passes
        </div>
      </div>
    );
  }

  const svgWidth = 480;
  const svgHeight = 160;
  const padding = { top: 20, right: 20, bottom: 32, left: 40 };
  const chartW = svgWidth - padding.left - padding.right;
  const chartH = svgHeight - padding.top - padding.bottom;

  const minScore = Math.max(0, Math.min(...scoreHistory) - 10);
  const maxScore = Math.min(100, Math.max(...scoreHistory) + 5);

  const points = scoreHistory.map((score, i) => ({
    x: padding.left + (i / (scoreHistory.length - 1)) * chartW,
    y: padding.top + chartH - ((score - minScore) / (maxScore - minScore)) * chartH,
    score,
    strategy: strategyHistory?.[i] || '',
    label: `Pass ${i + 1}`,
  }));

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  const areaPath = `${linePath} L ${points[points.length - 1].x} ${padding.top + chartH} L ${points[0].x} ${padding.top + chartH} Z`;

  const improvement = scoreHistory[scoreHistory.length - 1] - scoreHistory[0];

  return (
    <div
      className="card"
      style={{
        padding: 'var(--space-lg)',
        background: 'var(--bg-card)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
      }}
    >
      <div style={{ fontWeight: 700, fontSize: '0.95rem', marginBottom: 4 }}>
        Score progression across {scoreHistory.length} optimisation passes
      </div>

      <svg viewBox={`0 0 ${svgWidth} ${svgHeight}`} style={{ width: '100%', height: 'auto', marginTop: 8 }}>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
          const y = padding.top + chartH * (1 - frac);
          const val = minScore + frac * (maxScore - minScore);
          return (
            <g key={frac}>
              <line x1={padding.left} y1={y} x2={padding.left + chartW} y2={y} stroke="var(--border-subtle, #e2e8f0)" strokeWidth={1} strokeDasharray="4 4" />
              <text x={padding.left - 6} y={y + 4} textAnchor="end" fill="var(--text-muted, #94a3b8)" fontSize={10}>
                {Math.round(val)}
              </text>
            </g>
          );
        })}

        {/* Area fill */}
        <path d={areaPath} fill="url(#scoreGradient)" opacity={0.3} />

        {/* Line */}
        <path d={linePath} fill="none" stroke="#1D9E75" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />

        {/* Dots + labels */}
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r={4} fill="#1D9E75" stroke="#fff" strokeWidth={2} />
            <text x={p.x} y={p.y - 10} textAnchor="middle" fill="var(--text-primary, #0f172a)" fontSize={10} fontWeight={600}>
              {p.score.toFixed(0)}
            </text>
            <text x={p.x} y={padding.top + chartH + 16} textAnchor="middle" fill="var(--text-muted, #94a3b8)" fontSize={9}>
              {p.label}
            </text>
          </g>
        ))}

        <defs>
          <linearGradient id="scoreGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1D9E75" />
            <stop offset="100%" stopColor="#1D9E75" stopOpacity={0} />
          </linearGradient>
        </defs>
      </svg>

      <div style={{ marginTop: 8, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
        <span style={{ fontWeight: 600 }}>{scoreHistory[0].toFixed(0)}</span>
        {' → '}
        <span style={{ fontWeight: 600 }}>{scoreHistory[scoreHistory.length - 1].toFixed(0)}</span>
        {' '}
        <span style={{ color: '#1D9E75', fontWeight: 600 }}>
          (+{improvement.toFixed(0)} points)
        </span>
      </div>
    </div>
  );
}
