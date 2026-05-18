export default function DashboardSkeleton() {
  return (
    <div className="animate-fade-in">
      <div className="page-header app-page-header">
        <div className="page-header-content">
          <div>
            <div className="skeleton skeleton-h2" style={{ width: 240, marginBottom: 8 }} />
            <div className="skeleton skeleton-p" style={{ width: 360 }} />
          </div>
          <div className="skeleton skeleton-btn" style={{ width: 140 }} />
        </div>
      </div>

      <div className="dashboard-stats-row">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="card dashboard-stat-card">
            <div className="skeleton skeleton-stat-icon" style={{ marginBottom: 12 }} />
            <div className="skeleton skeleton-stat-value" style={{ width: 60, marginBottom: 6 }} />
            <div className="skeleton skeleton-stat-label" style={{ width: 100 }} />
          </div>
        ))}
      </div>

      <div className="skeleton skeleton-card" style={{ height: 180, marginBottom: 16 }} />
      <div className="skeleton skeleton-card" style={{ height: 260 }} />
    </div>
  );
}
