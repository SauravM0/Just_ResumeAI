import { useState } from 'react';

interface Props {
  value: string;
  label: string;
  reason?: string;
  className?: string;
}

export default function LockedField({ value, label, reason = 'This field is verified and cannot be changed', className = '' }: Props) {
  const [showTooltip, setShowTooltip] = useState(false);

  return (
    <div
      className={`form-group ${className}`}
      style={{ position: 'relative' }}
    >
      <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-xs)' }}>
        <span>🔒</span>
        {label}
      </label>
      <div
        style={{
          width: '100%',
          padding: '10px 14px',
          background: 'var(--bg-glass-strong)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          color: 'var(--text-secondary)',
          fontSize: '0.9rem',
          minHeight: 44,
          display: 'flex',
          alignItems: 'center',
          cursor: 'help',
          userSelect: 'none',
          position: 'relative',
        }}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        onFocus={() => setShowTooltip(true)}
        onBlur={() => setShowTooltip(false)}
        tabIndex={0}
        role="note"
        aria-label={`${label}: ${value}. ${reason}`}
      >
        <span style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          flex: 1,
        }}>
          {value || '—'}
        </span>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginLeft: 'var(--space-sm)', flexShrink: 0 }}>
          🔒
        </span>

        {/* Tooltip */}
        {showTooltip && (
          <div
            style={{
              position: 'absolute',
              bottom: 'calc(100% + 8px)',
              left: '50%',
              transform: 'translateX(-50%)',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border-medium)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-sm) var(--space-md)',
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              whiteSpace: 'nowrap',
              maxWidth: 280,
              zIndex: 50,
              boxShadow: 'var(--shadow-lg)',
              pointerEvents: 'none',
            }}
            role="tooltip"
          >
            {reason}
            <div style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              border: '6px solid transparent',
              borderTopColor: 'var(--bg-tertiary)',
            }} />
          </div>
        )}
      </div>
    </div>
  );
}
