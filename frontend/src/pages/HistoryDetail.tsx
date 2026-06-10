import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { getHistoryDetail, updateHistory, deleteHistory, type HistoryDetail } from '../lib/historyApi';
import { exportPdf, exportDocx, regenerateExportFile } from '../lib/api';
import ResumeVisualEditor from '../components/resume-editor/ResumeVisualEditor';
import ATSCompactScoreCard from '../components/ATSCompactScoreCard';
import AppCard from '../components/ui/AppCard';
import LoadingState from '../components/ui/LoadingState';
import ErrorState from '../components/ui/ErrorState';
import EmptyState from '../components/ui/EmptyState';
import type { ResumeRecommendation, ATSScore, ExportFileResponse } from '../types/resume';

function downloadExport(file: ExportFileResponse) {
  const url = URL.createObjectURL(file.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = file.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function HistoryDetailPage() {
  const { id: generationId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exportedPdf, setExportedPdf] = useState<ExportFileResponse | null>(null);
  const [exportedDocx, setExportedDocx] = useState<ExportFileResponse | null>(null);
  const [showJd, setShowJd] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deletingGen, setDeletingGen] = useState(false);

  useEffect(() => {
    if (!generationId) return;
    getHistoryDetail(generationId)
      .then(setDetail)
      .catch((e) => setError(e.message || 'Failed to load generation'))
      .finally(() => setLoading(false));
  }, [generationId]);

  const pdfExportMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: exportPdf,
    onSuccess: (data) => {
      setExportedPdf(data);
      downloadExport(data);
    },
  });

  const docxExportMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: exportDocx,
    onSuccess: (data) => {
      setExportedDocx(data);
      downloadExport(data);
    },
  });

  const regeneratePdfMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: (id) => regenerateExportFile(id, 'pdf'),
    onSuccess: (data) => {
      setExportedPdf(data);
      downloadExport(data);
    },
  });

  const regenerateDocxMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: (id) => regenerateExportFile(id, 'docx'),
    onSuccess: (data) => {
      setExportedDocx(data);
      downloadExport(data);
    },
  });

  const handleSaveEditor = async (updated: ResumeRecommendation) => {
    if (!generationId) return;
    try {
      await updateHistory(generationId, {
        resume_json: updated,
        status: 'completed',
      });
      setDetail(prev => prev ? { ...prev, resume_json: updated, ats_score_json: null } : prev);
    } catch (e) {
      console.error('Failed to save:', e);
    }
  };

  if (loading) {
    return <LoadingState text="Loading generation details..." />;
  }

  if (error || !detail) {
    return (
      <div className="animate-fade-in">
        <ErrorState
          message={error || 'The requested generation does not exist.'}
          title="Generation not found"
          variant="error"
          action={
            <button className="btn btn-primary" onClick={() => navigate('/history')}>
              Back to History
            </button>
          }
        />
      </div>
    );
  }

  const resumeJson = detail.resume_json as ResumeRecommendation | null;
  const atsScoreJson = detail.ats_score_json as ATSScore | null;
  const hasDocxFallback = Boolean(detail.docx_fallback_path || detail.pdf_compile_error);

  const getExpiryStatus = () => {
    if (!detail?.file_expiry_info?.has_files) return null;
    const hasExpired = detail.file_expiry_info.is_expired || detail.file_expiry_info.files.some(f => f.is_expired);
    return {
      hasExpired,
      canRegenerate: detail.file_expiry_info.regenerate_available && hasExpired,
      pdfAvailable: detail.file_expiry_info.pdf_available,
      docxAvailable: detail.file_expiry_info.docx_available,
    };
  };

  const expiryStatus = getExpiryStatus();

  return (
    <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
          <div>
            <h1 className="page-title">{detail.job_title || 'Resume Detail'}</h1>
            <p className="page-subtitle">
              {detail.company && <>{detail.company} \u2022 </>}
              {detail.created_at ? new Date(detail.created_at).toLocaleDateString() : ''}
            </p>
          </div>
          <span className={`badge ${detail.status === 'completed' ? 'badge-success' : detail.status === 'failed' ? 'badge-danger' : 'badge-warning'}`}>
            {detail.status}
          </span>
        </div>
      </div>

      {detail.status === 'failed' && (
        <div className="warning-banner warning-error">
          <span>\u26A0\uFE0F</span>
          <div>
            <strong>Generation failed</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              This resume generation did not complete successfully. Try creating a new one.
            </p>
          </div>
        </div>
      )}

      {detail.status === 'completed' && hasDocxFallback && (
        <div className="warning-banner warning-info">
          <span>DOCX</span>
          <div>
            <strong>Word document fallback available</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              PDF generation had a formatting issue, but the resume completed successfully as an editable DOCX.
            </p>
          </div>
        </div>
      )}

      <div
        className="action-bar"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-md)',
          flexWrap: 'wrap',
          padding: 'var(--space-md)',
          borderRadius: 'var(--radius-lg)',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        {atsScoreJson && (
          <ATSCompactScoreCard 
            atsScore={atsScoreJson} 
            alignmentReport={null} 
            resumeVersionId={resumeJson?.version_id}
            compact 
          />
        )}

        <div className="action-bar-actions">
          {resumeJson && (
            <button className="btn btn-primary btn-sm" onClick={() => navigate(`/review/${detail.generation_id}`)}>
              Open Editor
            </button>
          )}

          {expiryStatus?.hasExpired && expiryStatus?.canRegenerate && (
            <>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => generationId && regeneratePdfMutation.mutate(generationId)}
                disabled={regeneratePdfMutation.isPending}
              >
                Refresh PDF
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => generationId && regenerateDocxMutation.mutate(generationId)}
                disabled={regenerateDocxMutation.isPending}
              >
                Refresh DOCX
              </button>
            </>
          )}

          {!expiryStatus?.hasExpired && (
            <>
              {exportedPdf ? (
                <button className="btn btn-primary btn-sm" onClick={() => downloadExport(exportedPdf)}>
                  Download PDF
                </button>
              ) : (
                <button
                  className="btn btn-primary btn-sm"
                  onClick={() => generationId && pdfExportMutation.mutate(generationId)}
                  disabled={pdfExportMutation.isPending}
                >
                  {pdfExportMutation.isPending ? 'Exporting...' : hasDocxFallback ? 'Retry PDF Export' : 'Export PDF'}
                </button>
              )}

              {exportedDocx ? (
                <button className="btn btn-secondary btn-sm" onClick={() => downloadExport(exportedDocx)}>
                  Download DOCX
                </button>
              ) : (
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={() => generationId && docxExportMutation.mutate(generationId)}
                  disabled={docxExportMutation.isPending}
                >
                  {docxExportMutation.isPending ? 'Exporting...' : hasDocxFallback ? 'Download DOCX Fallback' : 'Export DOCX'}
                </button>
              )}
            </>
          )}

          <button className="btn btn-ghost btn-sm" onClick={() => navigate(`/cover-letter/${detail.generation_id}`)}>
            Cover Letter
          </button>

          {detail.raw_jd_text && (
            <button className="btn btn-ghost btn-sm" onClick={() => setShowJd(!showJd)}>
              {showJd ? 'Hide JD' : 'View JD'}
            </button>
          )}

          <button
            className="btn btn-danger btn-sm"
            onClick={() => setShowDeleteConfirm(true)}
            disabled={deletingGen}
          >
            {deletingGen ? 'Deleting...' : 'Delete'}
          </button>

          <button className="btn btn-ghost btn-sm" onClick={() => navigate('/history')}>
            Back
          </button>
        </div>
      </div>

      {/* Delete confirmation */}
      {showDeleteConfirm && (
        <div
          className="sidebar-overlay open"
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 200 }}
          onClick={() => setShowDeleteConfirm(false)}
        >
          <div
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
              <button className="btn btn-ghost btn-sm" onClick={() => setShowDeleteConfirm(false)}>
                Cancel
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={async () => {
                  if (!generationId) return;
                  setDeletingGen(true);
                  try {
                    await deleteHistory(generationId);
                    navigate('/history');
                  } catch (e) {
                    console.error('Delete failed:', e);
                    setDeletingGen(false);
                    setShowDeleteConfirm(false);
                  }
                }}
                disabled={deletingGen}
              >
                {deletingGen ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showJd && detail.raw_jd_text && (
        <AppCard title="Original Job Description" actions={
          <button className="btn btn-ghost btn-sm" onClick={() => setShowJd(false)}>Hide</button>
        }>
          <div style={{
            whiteSpace: 'pre-wrap',
            fontSize: '0.85rem',
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
            maxHeight: '300px',
            overflowY: 'auto',
            padding: 'var(--space-sm)',
            background: 'var(--bg-input)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-subtle)',
          }}>
            {detail.raw_jd_text}
          </div>
        </AppCard>
      )}

      {expiryStatus?.hasExpired && (
        <div className="warning-banner warning-warn">
          <span>\u26A0\uFE0F</span>
          <div>
            <strong>Files have expired</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              {expiryStatus.canRegenerate
                ? 'Your exported files have expired. You can refresh them to get new download links.'
                : 'Your exported files have expired and cannot be refreshed. Export the resume again.'}
            </p>
          </div>
        </div>
      )}

      {exportedPdf?.compressed && (
        <div className="warning-banner warning-info">
          <span>PDF fit</span>
          <div>
            <strong>Compressed to {exportedPdf.page_count ?? 1} page{(exportedPdf.page_count ?? 1) === 1 ? '' : 's'}</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              {(exportedPdf.compression_actions || []).slice(0, 3).join(' ') || 'Optional resume details were shortened while preserving factual anchors.'}
            </p>
          </div>
        </div>
      )}

      {resumeJson && generationId && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <ResumeVisualEditor
            recommendation={resumeJson}
            generationId={generationId}
            onSave={handleSaveEditor}
          />
        </div>
      )}

      {!resumeJson && (
        <EmptyState
          icon="!"
          title="No resume data available"
          description="This generation does not have saved resume data to edit."
          action={
            <button className="btn btn-primary" onClick={() => navigate('/jd')}>
              Create New Resume
            </button>
          }
        />
      )}
    </div>
  );
}
