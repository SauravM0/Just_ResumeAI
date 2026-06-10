interface Props {
  icon: string;
  iconBgClass?: string;
  value: string | number;
  valueClass?: string;
  label: string;
  accentIndex?: number;
}

/**
 * Reusable stat card for dashboard metrics.
 * Supports color-coded values and accent top borders.
 */
export default function StatCard({ icon, iconBgClass = '', value, valueClass = '', label, accentIndex = 0 }: Props) {
  const accentColors = [
    'var(--accent-gradient)',
    'linear-gradient(90deg, #10b981, #6ee7b7)',
    'linear-gradient(90deg, #8b5cf6, #a855f7)',
    'linear-gradient(90deg, #f59e0b, #fbbf24)',
  ];

  const iconBgs = [
    'var(--accent-gradient-soft)',
    'rgba(16, 185, 129, 0.1)',
    'rgba(139, 92, 246, 0.1)',
    'rgba(245, 158, 11, 0.1)',
  ];

  const idx = accentIndex % 4;

  return (
    <div
      className="card dashboard-stat-card"
      style={{ position: 'relative', overflow: 'hidden' }}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: accentColors[idx],
        }}
      />
      <div
        className={`stat-icon ${iconBgClass || iconBgs[idx]}`}
        style={{
          fontSize: '1.2rem',
          marginBottom: 'var(--space-sm)',
          width: 36,
          height: 36,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: 'var(--radius-md)',
        }}
      >
        {icon}
      </div>
      <div className={`stat-value ${valueClass}`}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
