/**
 * LaTeX Editor page — view/edit LaTeX source + PDF preview/export.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { renderPdf } from '../lib/api';
import { useAppStore } from '../store/useAppStore';

export default function LatexEditor() {
  const navigate = useNavigate();
  const { sessionId, latexSource, setLatexSource } = useAppStore();
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [compileErrors, setCompileErrors] = useState<string[]>([]);

  const compileMutation = useMutation({
    mutationFn: renderPdf,
    onSuccess: (data) => {
      if (data.compile_success) {
        // Build full URL from relative path
        const baseUrl = import.meta.env.VITE_API_BASE?.replace('/api/v1', '') || 'http://localhost:8000';
        setPdfUrl(`${baseUrl}${data.pdf_url}`);
        setCompileErrors([]);
      } else {
        setPdfUrl(null);
        setCompileErrors(data.compile_errors);
      }
    },
    onError: (error) => {
      setPdfUrl(null);
      setCompileErrors([
        error instanceof Error ? error.message : 'PDF compilation failed.',
      ]);
    },
  });

  const handleCompile = () => {
    if (!sessionId || !latexSource) return;
    compileMutation.mutate({
      session_id: sessionId,
    });
  };

  const handleDownload = () => {
    if (pdfUrl) {
      window.open(pdfUrl, '_blank');
    }
  };

  const handleCopyLatex = () => {
    if (latexSource) {
      navigator.clipboard.writeText(latexSource);
    }
  };

  const handleDownloadLatex = () => {
    if (!latexSource) return;
    const blob = new Blob([latexSource], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'resume.tex';
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!sessionId || !latexSource) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📑</div>
        <div className="empty-title">No LaTeX source generated</div>
        <div className="empty-description">Complete the resume review first to generate LaTeX.</div>
        <button className="btn btn-primary" onClick={() => navigate('/review')}>Go to Review</button>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 className="page-title">LaTeX Editor & PDF Preview</h1>
          <p className="page-subtitle">
            Review the generated LaTeX source. Compile to PDF when ready.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
          <button className="btn btn-ghost" onClick={handleCopyLatex}>📋 Copy LaTeX</button>
          <button className="btn btn-secondary" onClick={handleDownloadLatex}>💾 Download .tex</button>
          <button className="btn btn-secondary" onClick={handleCompile} disabled={compileMutation.isPending}>
            {compileMutation.isPending ? <span className="spinner" /> : '⚡'} Compile PDF
          </button>
          {pdfUrl && (
            <button className="btn btn-primary" onClick={handleDownload}>📥 Download PDF</button>
          )}
        </div>
      </div>

      {/* Pipeline */}
      <div className="pipeline-steps" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="pipeline-step step-done"><span>✓</span><span>Profile</span></div>
        <div className="pipeline-connector" />
        <div className="pipeline-step step-done"><span>✓</span><span>JD Analysis</span></div>
        <div className="pipeline-connector" />
        <div className="pipeline-step step-done"><span>✓</span><span>Review</span></div>
        <div className="pipeline-connector" />
        <div className="pipeline-step step-active"><span>📑</span><span>LaTeX / PDF</span></div>
      </div>

      {/* Compile Errors */}
      {compileErrors.length > 0 && (
        <div style={{ marginBottom: 'var(--space-lg)' }}>
          {compileErrors.map((err, i) => (
            <div key={i} className="warning-banner warning-error" style={{ marginBottom: 'var(--space-xs)' }}>
              <span>❌</span><span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>{err}</span>
            </div>
          ))}
        </div>
      )}

      {/* Split Pane: Editor + Preview */}
      <div className="split-pane">
        <div className="split-pane-left">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-sm)' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              LaTeX Source
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>
              {latexSource.length.toLocaleString()} characters
            </span>
          </div>
          <textarea
            className="code-editor"
            value={latexSource}
            onChange={(e) => setLatexSource(e.target.value)}
            spellCheck={false}
          />
          <p style={{ marginTop: 'var(--space-sm)', color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
            PDF compilation uses the last server-rendered LaTeX stored for this session. Local edits in this textbox are not compiled in this phase.
          </p>
        </div>

        <div className="split-pane-right">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-sm)' }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              PDF Preview
            </span>
            {compileMutation.isPending && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="spinner" />
                <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>Compiling...</span>
              </div>
            )}
          </div>
          <div className="pdf-preview">
            {pdfUrl ? (
              <iframe src={pdfUrl} title="PDF Preview" />
            ) : (
              <div className="empty-state" style={{ padding: 'var(--space-xl)' }}>
                <div className="empty-icon" style={{ fontSize: '2rem' }}>📄</div>
                <div className="empty-title" style={{ color: '#666' }}>No PDF yet</div>
                <div className="empty-description" style={{ color: '#999' }}>Click "Compile PDF" to generate the preview.</div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Overleaf Tip */}
      <div className="card" style={{ marginTop: 'var(--space-lg)' }}>
        <div className="card-title" style={{ marginBottom: 'var(--space-sm)' }}>💡 Overleaf Integration</div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
          You can also copy the LaTeX source and paste it into{' '}
          <a href="https://www.overleaf.com" target="_blank" rel="noopener noreferrer">Overleaf</a>
          {' '}for advanced editing and compilation. The template is compatible with standard pdflatex.
        </p>
      </div>
    </div>
  );
}
