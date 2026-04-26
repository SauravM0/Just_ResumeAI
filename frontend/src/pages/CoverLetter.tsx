/**
 * Cover Letter page — generate and view a tailored cover letter.
 */

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { generateCoverLetter } from '../lib/api';
import { useAppStore } from '../store/useAppStore';

export default function CoverLetter() {
  const { sessionId, activeProfile, parsedJD, recommendation } = useAppStore();
  const [tone, setTone] = useState('Professional');
  const [additionalContext, setAdditionalContext] = useState('');
  const [coverLetterText, setCoverLetterText] = useState('');

  const generateMutation = useMutation({
    mutationFn: generateCoverLetter,
    onSuccess: (data) => {
      setCoverLetterText(data.cover_letter_text);
    },
  });

  const handleGenerate = () => {
    if (!sessionId || !activeProfile || !parsedJD || !recommendation) return;
    generateMutation.mutate({
      session_id: sessionId,
      profile: activeProfile,
      parsed_jd: parsedJD,
      recommendation,
      tone,
      additional_context: additionalContext,
    });
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(coverLetterText);
  };

  if (!sessionId || !recommendation) {
    return (
      <div className="empty-state">
        <div className="empty-icon">✉️</div>
        <div className="empty-title">Session required</div>
        <div className="empty-description">Please complete the resume review first.</div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <h1 className="page-title">Tailored Cover Letter</h1>
        <p className="page-subtitle">
          Generate a high-impact cover letter tailored to {parsedJD?.company || 'the job'}.
        </p>
      </div>

      <div className="split-pane">
        <div className="split-pane-left">
          <div className="card">
            <h2 className="card-title" style={{ marginBottom: 'var(--space-md)' }}>Settings</h2>
            
            <div className="form-group">
              <label className="form-label">Tone</label>
              <select 
                className="form-select" 
                value={tone} 
                onChange={(e) => setTone(e.target.value)}
              >
                <option>Professional</option>
                <option>Enthusiastic</option>
                <option>Concise</option>
                <option>Bold</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Additional Instructions</label>
              <textarea
                className="form-textarea"
                placeholder="e.g. Mention my specific interest in their recent AI project..."
                value={additionalContext}
                onChange={(e) => setAdditionalContext(e.target.value)}
              />
            </div>

            <button 
              className="btn btn-primary btn-lg" 
              style={{ width: '100%' }}
              onClick={handleGenerate}
              disabled={generateMutation.isPending}
            >
              {generateMutation.isPending ? <span className="spinner" /> : '✨ Generate Cover Letter'}
            </button>
          </div>
        </div>

        <div className="split-pane-right">
          <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-md)' }}>
              <h2 className="card-title">Generated Letter</h2>
              {coverLetterText && (
                <button className="btn btn-ghost btn-sm" onClick={handleCopy}>📋 Copy</button>
              )}
            </div>

            <div 
              className="code-editor" 
              style={{ 
                flex: 1, 
                backgroundColor: 'var(--bg-card-hover)', 
                whiteSpace: 'pre-wrap',
                fontFamily: 'var(--font-sans)',
                fontSize: '0.95rem'
              }}
            >
              {coverLetterText || (
                <div className="loading-state" style={{ height: '100%' }}>
                  <div className="loading-text">Click generate to see the magic.</div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
