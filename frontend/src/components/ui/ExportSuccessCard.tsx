interface Props {
  pdfReady: boolean;
  docxReady: boolean;
  pageCount?: number;
  targetPages: number;
  atsScore?: number;
  onDownloadPdf: () => void;
  onDownloadDocx: () => void;
  onNewResume: () => void;
  onCoverLetter?: () => void;
  blocked?: boolean;
  blockReason?: string;
  className?: string;
  /** Whether the validation gate repaired the resume before export */
  validationRepaired?: boolean;
  /** Validation warnings from the gate */
  validationWarnings?: string[];
}

/**
 * Export Success Card — final step confidence panel.
 * Shows download buttons, file readiness, and next actions.
 */
export default function ExportSuccessCard({
  pdfReady,
  docxReady,
  pageCount,
  targetPages,
  atsScore,
  onDownloadPdf,
  onDownloadDocx,
  onNewResume,
  onCoverLetter,
  blocked = false,
  blockReason,
  className = '',
  validationRepaired = false,
  validationWarnings = [],
}: Props) {
  return (
    <div className={`export-success-card card ${blocked ? 'export-success-blocked' : ''} ${className}`}>
      <div className="export-success-header">
        <div className="export-success-icon">
          <span className="export-success-check">✓</span>
        </div>
        <div className="export-success-title">{blocked ? 'Export needs attention' : 'Your resume is ready'}</div>
        <div className="export-success-desc">
          {atsScore !== undefined && `ATS Score: ${Math.round(atsScore)}% · `}
          {pageCount ? `${pageCount} page${pageCount > 1 ? 's' : ''}` : ''}
          {pageCount && pageCount > targetPages ? ' (compressed)' : ''}
        </div>
      </div>

      {validationRepaired && !blocked && (
        <div className="warning-banner warning-info" style={{ marginBottom: 'var(--space-sm)' }}>
          <span>🛠</span>
          <div>
            <strong>Auto-repaired before export</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              The validation gate automatically fixed minor issues before generating this file.{(validationWarnings ?? []).length > 0 && ` ${(validationWarnings ?? []).length} warning(s) resolved.`}
            </p>
          </div>
        </div>
      )}

      {blocked && (
        <div className="export-success-blocker" role="alert">
          {blockReason || 'Export validation must pass before a new file can be generated.'}
        </div>
      )}

      <div className="export-success-actions">
        {pdfReady ? (
          <button className="btn btn-primary btn-lg export-success-btn" onClick={onDownloadPdf} disabled={blocked}>
            <span className="export-success-btn-icon">📄</span>
            <div className="export-success-btn-text">
              <span className="export-success-btn-label">Download PDF</span>
              <span className="export-success-btn-hint">Ready to submit</span>
            </div>
          </button>
        ) : (
          <button className="btn btn-secondary btn-lg export-success-btn" onClick={onDownloadPdf} disabled={blocked}>
            <span className="export-success-btn-icon">📄</span>
            <div className="export-success-btn-text">
              <span className="export-success-btn-label">Generate PDF</span>
              <span className="export-success-btn-hint">Compiles to your page target</span>
            </div>
          </button>
        )}

        {docxReady ? (
          <button className="btn btn-secondary btn-lg export-success-btn" onClick={onDownloadDocx} disabled={blocked}>
            <span className="export-success-btn-icon">📝</span>
            <div className="export-success-btn-text">
              <span className="export-success-btn-label">Download DOCX</span>
              <span className="export-success-btn-hint">Editable in Word</span>
            </div>
          </button>
        ) : (
          <button className="btn btn-secondary btn-lg export-success-btn" onClick={onDownloadDocx} disabled={blocked}>
            <span className="export-success-btn-icon">📝</span>
            <div className="export-success-btn-text">
              <span className="export-success-btn-label">Export DOCX</span>
              <span className="export-success-btn-hint">Editable format</span>
            </div>
          </button>
        )}
      </div>

      <div className="export-success-next">
        <button className="btn btn-ghost btn-sm" onClick={onNewResume}>
          + New Resume
        </button>
        {onCoverLetter && (
          <button className="btn btn-ghost btn-sm" onClick={onCoverLetter}>
            Generate Cover Letter
          </button>
        )}
      </div>
    </div>
  );
}
