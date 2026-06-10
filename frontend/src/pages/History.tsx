import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getHistory, deleteHistory, type HistoryItem } from '../lib/historyApi';
import PageHeader from '../components/ui/PageHeader';
import AppCard from '../components/ui/AppCard';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';

const PAGE_SIZE = 20;

function formatAtsScore(score: number | null | undefined): { label: string; variant: 'high' | 'mid' | 'low' } {
  if (score === null || score === undefined) return { label: '--', variant: 'mid' };
  if (score >= 80) return { label: `${Math.round(score)}`, variant: 'high' };
  if (score >= 60) return { label: `${Math.round(score)}`, variant: 'mid' };
  return { label: `${Math.round(score)}`, variant: 'low' };
}

function getRelativeDate(dateStr: string | null): string {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function SkeletonItem() {
  return (
    <div className="history-list-item" style={{ cursor: 'default', pointerEvents: 'none' }}>
      <div className="history-list-item-text" style={{ flex: 1 }}>
        <div className="skeleton skeleton-p" style={{ width: '60%', marginBottom: 8 }} />
        <div className="skeleton skeleton-p" style={{ width: '40%', height: 12 }} />
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <div className="skeleton" style={{ width: 60, height: 22, borderRadius: 9999 }} />
          <div className="skeleton" style={{ width: 70, height: 22, borderRadius: 9999 }} />
        </div>
      </div>
      <div className="skeleton" style={{ width: 20, height: 20, borderRadius: '50%' }} />
    </div>
  );
}

function DeleteConfirmDialog({
  deleting,
  onConfirm,
  onCancel,
}: {
  deleting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialogRef = useCallback((node: HTMLDivElement | null) => {
    if (node) {
      const firstBtn = node.querySelector('button');
      firstBtn?.focus();
    }
  }, []);

  return (
    <div
      className="sidebar-overlay open"
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
      onClick={onCancel}
    >
      <div
        ref={dialogRef}
        className="card"
        style={{
          width: 'min(400px, calc(100vw - 32px))',
          padding: 'var(--space-xl)',
          textAlign: 'center',
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Confirm deletion"
      >
        <div style={{ fontSize: '2.5rem', marginBottom: 'var(--space-md)' }}>🗑️</div>
        <h3 style={{ margin: '0 0 var(--space-xs)' }}>Delete this generation?</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: '0 0 var(--space-lg)' }}>
          This will archive the generation. You can still regenerate from your profile data.
        </p>
        <div style={{ display: 'flex', gap: 'var(--space-sm)', justifyContent: 'center' }}>
          <button className="btn btn-ghost btn-sm" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn btn-danger btn-sm" onClick={onConfirm} disabled={deleting}>
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function History() {
  const navigate = useNavigate();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchPage = useCallback(async (pageNum: number, append: boolean = false) => {
    setLoading(true);
    setError(null);
    try {
      const data = await getHistory(PAGE_SIZE, pageNum * PAGE_SIZE);
      setItems((prev) => (append ? [...prev, ...data] : data));
      setHasMore(data.length >= PAGE_SIZE);
    } catch (e) {
      setError((e as Error).message || 'Failed to load history');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPage(0);
  }, [fetchPage]);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteHistory(deleteTarget);
      setItems((prev) => prev.filter((i) => i.generation_id !== deleteTarget));
    } catch (e) {
      console.error('Delete failed:', e);
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  // ── Loading skeleton (initial) ─────────────────────────────────────
  if (loading && items.length === 0) {
    return (
      <div className="animate-fade-in">
        <PageHeader title="History" subtitle="Your past resume generations" />
        <AppCard>
          <div className="history-list">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonItem key={i} />
            ))}
          </div>
        </AppCard>
      </div>
    );
  }

  // ── Error state ────────────────────────────────────────────────────
  if (error && items.length === 0) {
    return (
      <div className="animate-fade-in">
        <PageHeader title="History" subtitle="Your past resume generations" />
        <ErrorState
          message={error}
          onRetry={() => fetchPage(0)}
        />
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────
  if (!loading && items.length === 0) {
    return (
      <div className="animate-fade-in">
        <PageHeader title="History" subtitle="Your past resume generations" />
        <EmptyState
          icon="📋"
          title="No resume history yet"
          description="Your generated resumes will appear here. Paste a job description to create your first one."
          action={
            <button className="btn btn-primary btn-lg" onClick={() => navigate('/jd')}>
              Create Your First Resume
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
            const isFailed = item.status === 'failed';
            const isArchived = item.status === 'archived';
            const isExpired = item.file_expiry_info?.is_expired;
            const hasPdf = item.file_expiry_info?.pdf_available;
            const hasDocx = item.file_expiry_info?.docx_available;
            const statusBadge = isFailed ? 'danger' : isArchived ? 'neutral' : item.status === 'completed' ? 'success' : 'warning';

            return (
              <div
                key={item.generation_id}
                className="history-list-item"
                style={{ position: 'relative' }}
              >
                {/* Main clickable area — navigate to detail */}
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 'var(--space-md)',
                    flex: 1,
                    cursor: 'pointer',
                    padding: 'var(--space-sm) 0',
                    minHeight: 48,
                  }}
                  onClick={() => navigate(`/history/${item.generation_id}`)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') navigate(`/history/${item.generation_id}`); }}
                  role="button"
                  tabIndex={0}
                >
                  {/* Left: Company initials + job info */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', minWidth: 0, flex: 1 }}>
                    <div
                      style={{
                        width: 40,
                        height: 40,
                        borderRadius: 'var(--radius-md)',
                        background: 'var(--accent-gradient-soft)',
                        border: '1px solid var(--border-medium)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontWeight: 700,
                        fontSize: '0.85rem',
                        color: 'var(--text-accent)',
                        flexShrink: 0,
                      }}
                    >
                      {(item.company || item.job_title || '?').charAt(0).toUpperCase()}
                    </div>

                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className="history-list-item-title">
                        {item.job_title || 'Untitled'}
                      </div>
                      <div className="history-list-item-meta">
                        {[item.company, getRelativeDate(item.created_at)].filter(Boolean).join(' · ')}
                      </div>
                    </div>
                  </div>

                  {/* Middle: Score + status badges */}
                  <div className="history-list-item-badges" style={{ flexShrink: 0 }}>
                    {!isFailed && !isArchived && (
                      <span
                        className={`badge ${ats.variant === 'high' ? 'badge-success' : ats.variant === 'low' ? 'badge-danger' : 'badge-info'}`}
                        style={{ fontWeight: 700, fontSize: '0.8rem' }}
                      >
                        {ats.label}
                      </span>
                    )}
                    <span className={`badge badge-${statusBadge}`}>
                      {isFailed ? 'Failed' : isArchived ? 'Archived' : item.status.charAt(0).toUpperCase() + item.status.slice(1)}
                    </span>
                    {hasPdf && !isExpired && <span className="badge badge-neutral">PDF</span>}
                    {hasDocx && !isExpired && <span className="badge badge-neutral">DOCX</span>}
                  </div>

                  {/* Right: Chevron */}
                  <div className="history-list-item-chevron">→</div>
                </div>

                {/* Delete button — positioned absolute top-right */}
                {!isArchived && (
                  <button
                    className="btn btn-ghost btn-icon-sm"
                    style={{
                      position: 'absolute',
                      top: 4,
                      right: 0,
                      padding: 4,
                      minWidth: 32,
                      minHeight: 32,
                      fontSize: '0.85rem',
                      color: 'var(--text-tertiary)',
                      opacity: 0,
                      transition: 'opacity var(--transition-fast)',
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleteTarget(item.generation_id);
                    }}
                    onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.opacity = '1'; }}
                    onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.opacity = '0'; }}
                    title="Delete"
                    aria-label="Delete generation"
                  >
                    🗑️
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {/* Pagination: Load more */}
        {hasMore && (
          <div style={{ textAlign: 'center', padding: 'var(--space-md)', borderTop: '1px solid var(--border-subtle)' }}>
            <button
              className="btn btn-ghost"
              onClick={() => {
                const nextPage = page + 1;
                setPage(nextPage);
                fetchPage(nextPage, true);
              }}
              disabled={loading}
              style={{ minWidth: 200 }}
            >
              {loading ? (
                <span className="spinner" style={{ width: 14, height: 14 }} />
              ) : (
                'Load More'
              )}
            </button>
          </div>
        )}
      </AppCard>

      {/* Delete confirmation dialog */}
      {deleteTarget && (
        <DeleteConfirmDialog
          deleting={deleting}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}
