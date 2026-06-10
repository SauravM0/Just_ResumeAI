interface Props {
  pageCount?: number;
  targetPages: number;
  pdfParseStatus?: string;
  pdfCompiled: boolean;
  pdfCompressed?: boolean;
  compressionActions?: string[];
  className?: string;
}

export default function PdfParseStatus({
  pageCount,
  targetPages,
  pdfParseStatus,
  pdfCompiled,
  pdfCompressed,
  compressionActions,
  className = '',
}: Props) {
  const pageStatus = pageCount
    ? pageCount <= targetPages
      ? 'fits'
      : 'overflow'
    : 'unknown';

  const parseStatus = pdfParseStatus || 'unknown';
  const parseOk = parseStatus === 'success';

  return (
    <div className={`pdf-status-card card ${className}`}>
      <div className="pdf-status-header">
        <div className="pdf-status-icon">
          {pdfCompiled ? (pdfCompressed ? '📄' : '📄') : '⏳'}
        </div>
        <div className="pdf-status-info">
          <h4 className="pdf-status-title">
            {pdfCompiled ? 'PDF Ready' : 'PDF Not Compiled'}
          </h4>
          <p className="pdf-status-subtitle">
            {pdfCompiled
              ? `Your resume has been compiled and is ready for download.`
              : 'Enable PDF compilation to download your resume as a PDF file.'}
          </p>
        </div>
      </div>

      <div className="pdf-status-metrics">
        <div className="pdf-status-metric">
          <div className={`pdf-status-metric-value ${pdfCompiled ? 'text-success' : 'text-muted'}`}>
            {pdfCompiled ? '✓' : '—'}
          </div>
          <div className="pdf-status-metric-label">PDF compiled</div>
        </div>

        <div className="pdf-status-metric">
          <div className={`pdf-status-metric-value ${parseOk ? 'text-success' : parseStatus === 'unknown' ? 'text-muted' : 'text-warning'}`}>
            {parseOk ? '✓' : parseStatus === 'unknown' ? '—' : '!'}
          </div>
          <div className="pdf-status-metric-label">PDF parsed</div>
        </div>

        <div className="pdf-status-metric">
          <div className={`pdf-status-metric-value ${pageStatus === 'fits' ? 'text-success' : pageStatus === 'overflow' ? 'text-warning' : 'text-muted'}`}>
            {pageCount ?? '—'}
          </div>
          <div className="pdf-status-metric-label">
            Page{pageCount !== 1 ? 's' : ''} (target: {targetPages})
          </div>
        </div>
      </div>

      {pageStatus === 'overflow' && pageCount && (
        <div className="warning-banner warning-warn" style={{ marginTop: 'var(--space-md)' }}>
          <span>⚠️</span>
          <div>
            <strong>Resume exceeds target length</strong>
            <p style={{ margin: 0, marginTop: '2px', fontSize: '0.8rem' }}>
              Your resume is {pageCount} page{pageCount > 1 ? 's' : ''} but the target is {targetPages} page{targetPages > 1 ? 's' : ''}.
              {pdfCompressed ? ' Content was compressed to fit.' : ' Consider shortening some sections.'}
            </p>
          </div>
        </div>
      )}

      {pdfCompressed && compressionActions && compressionActions.length > 0 && (
        <div className="pdf-status-compression" style={{ marginTop: 'var(--space-md)' }}>
          <h5 className="pdf-status-compression-title">Compression applied:</h5>
          <ul className="pdf-status-compression-list">
            {compressionActions.slice(0, 5).map((action, i) => (
              <li key={i}>{action}</li>
            ))}
          </ul>
        </div>
      )}

      {pageStatus === 'fits' && pdfCompiled && (
        <div className="pdf-status-success" style={{ marginTop: 'var(--space-md)' }}>
          <span className="badge badge-success">
            ✓ Fits {targetPages} page{targetPages > 1 ? 's' : ''}
          </span>
        </div>
      )}
    </div>
  );
}
