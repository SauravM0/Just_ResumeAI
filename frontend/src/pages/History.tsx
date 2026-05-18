import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getHistory, type HistoryItem } from '../lib/historyApi';
import PageHeader from '../components/ui/PageHeader';
import AppCard from '../components/ui/AppCard';
import LoadingState from '../components/ui/LoadingState';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';

function formatAtsScore(score: number | null | undefined): { label: string; variant: 'high' | 'mid' | 'low' } {
  if (score === null || score === undefined) return { label: '--', variant: 'mid' };
  if (score >= 80) return { label: `${Math.round(score)}`, variant: 'high' };
  if (score >= 60) return { label: `${Math.round(score)}`, variant: 'mid' };
  return { label: `${Math.round(score)}`, variant: 'low' };
}

export default function History() {
  const navigate = useNavigate();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHistory(50)
      .then(setItems)
      .catch((e) => setError(e.message || 'Failed to load history'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingState text="Loading your resume history..." />;
  }

  if (error) {
    return (
      <div className="animate-fade-in">
        <PageHeader title="History" subtitle="Your past resume generations" />
        <ErrorState
          message={error}
          onRetry={() => { setLoading(true); setError(null); getHistory(50).then(setItems).catch((e) => setError(e.message)).finally(() => setLoading(false)); }}
        />
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="animate-fade-in">
        <PageHeader title="History" subtitle="Your past resume generations" />
        <EmptyState
          icon="\uD83D\uDCCB"
          title="No resume history yet"
          description="Your generated resumes will appear here. Paste a job description to create your first one."
          action={
            <button className="btn btn-primary" onClick={() => navigate('/jd')}>
              Generate Your First Resume
            </button>
          }
        />
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="History"
        subtitle="Your past resume generations"
        badge={<span className="badge badge-info">{items.length} generation{items.length !== 1 ? 's' : ''}</span>}
      />

      <AppCard>
        <div className="history-list">
          {items.map((item) => {
            const ats = formatAtsScore(item.ats_score_summary?.overall_score);
            const isExpired = item.file_expiry_info?.is_expired;
            const hasPdf = item.file_expiry_info?.pdf_available;
            const hasDocx = item.file_expiry_info?.docx_available;
            const hasFiles = item.file_expiry_info?.has_files;
            const canRegen = item.file_expiry_info?.regenerate_available;
            const statusBadge = item.status === 'completed' ? 'success' : item.status === 'failed' ? 'danger' : 'warning';

            return (
              <div
                key={item.generation_id}
                className="history-list-item"
                onClick={() => navigate(`/history/${item.generation_id}`)}
              >
                <div className="history-list-item-text">
                  <div className="history-list-item-title">
                    {item.job_title || 'Untitled'}
                  </div>
                  <div className="history-list-item-meta">
                    {[item.company, item.created_at ? new Date(item.created_at).toLocaleDateString() : null]
                      .filter(Boolean)
                      .join(' | ')}
                  </div>
                  <div className="history-list-item-badges" style={{ marginTop: 'var(--space-xs)' }}>
                    <span className={`badge badge-${ats.variant === 'high' ? 'success' : ats.variant === 'low' ? 'danger' : 'info'}`}
                      style={{ fontWeight: 700 }}
                    >
                      {ats.label} ATS
                    </span>
                    <span className={`badge badge-${statusBadge}`}>
                      {item.status.charAt(0).toUpperCase() + item.status.slice(1)}
                    </span>
                    {hasPdf && !isExpired && <span className="badge badge-neutral">PDF</span>}
                    {hasDocx && !isExpired && <span className="badge badge-neutral">DOCX</span>}
                    {hasFiles && isExpired && (
                      <span className="badge badge-warning">
                        {canRegen ? 'Expired — refresh' : 'Files expired'}
                      </span>
                    )}
                    {item.has_cover_letter && <span className="badge badge-neutral">Cover</span>}
                  </div>
                </div>
                <div className="history-list-item-chevron">\u2192</div>
              </div>
            );
          })}
        </div>
      </AppCard>
    </div>
  );
}
