import { useState, useEffect, useRef } from 'react';

interface BulletQualityBadgeProps {
  starScore: number;
  hasAction: boolean;
  hasContext: boolean;
  hasOutcome: boolean;
  hasBannedPhrase: boolean;
  onImprove?: () => void;
}

export function BulletQualityBadge({
  starScore,
  hasAction,
  hasContext,
  hasOutcome,
  hasBannedPhrase,
  onImprove,
}: BulletQualityBadgeProps) {
  const [showDetails, setShowDetails] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showDetails) return;
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDetails(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showDetails]);

  const color = hasBannedPhrase ? 'red' : starScore >= 80 ? 'green' : starScore >= 60 ? 'amber' : 'red';
  const dotColor = { green: '#1D9E75', amber: '#E8920E', red: '#E24B4A' }[color];

  const checks = [
    { label: 'Strong action verb', pass: hasAction },
    { label: 'Technology/context', pass: hasContext },
    { label: 'Outcome/impact', pass: hasOutcome },
  ];
  if (hasBannedPhrase) checks.push({ label: 'No banned phrases', pass: false });

  return (
    <div ref={containerRef} style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setShowDetails(!showDetails)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setShowDetails(!showDetails); }}
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: dotColor,
          cursor: 'pointer',
          flexShrink: 0,
          transition: 'transform 0.1s',
        }}
        title={`Bullet quality: ${starScore}/100. Click for details.`}
      />

      {showDetails && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginTop: 6,
            background: 'var(--bg-card, #fff)',
            border: '1px solid var(--border-subtle, #e2e8f0)',
            borderRadius: 8,
            padding: '10px 12px',
            minWidth: 200,
            zIndex: 50,
            boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
            fontSize: '0.78rem',
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 6, fontSize: '0.82rem' }}>
            Bullet Quality: {starScore}/100
          </div>

          {checks.map((c) => (
            <div key={c.label} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <span style={{ color: c.pass ? '#1D9E75' : '#E24B4A', fontWeight: 600 }}>
                {c.pass ? '✓' : '✗'}
              </span>
              <span style={{ color: 'var(--text-secondary, #64748b)' }}>{c.label}</span>
            </div>
          ))}

          {onImprove && !hasBannedPhrase && starScore < 80 && (
            <button
              className="btn btn-primary btn-sm"
              style={{ marginTop: 8, width: '100%', fontSize: '0.75rem' }}
              onClick={(e) => {
                e.stopPropagation();
                setShowDetails(false);
                onImprove();
              }}
            >
              Improve this bullet
            </button>
          )}
        </div>
      )}
    </div>
  );
}
