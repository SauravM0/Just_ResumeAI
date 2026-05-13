/**
 * Fast resume output console.
 *
 * Users can copy, lightly edit, optimize, export, and move to the next JD
 * without approving individual bullets.
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import ATSCompactScoreCard from '../components/ATSCompactScoreCard';
import { approveGeneratePdf, exportResumeDocx, generateCoverLetter, regenerateResume, validateResume } from '../lib/api';
import { getDefaultProfile, saveRecentResumeSnapshot } from '../lib/db';
import { sanitizeProfile } from '../lib/profile';
import {
  recommendationSkillsToText,
  recommendationSummaryToText,
  recommendationToMarkdown,
  recommendationToPlainText,
} from '../lib/resumeText';
import { useAppStore } from '../store/useAppStore';
import type {
  ApproveGeneratePdfRequest,
  ApproveGeneratePdfResponse,
  ResumeBullet,
  ResumeExperienceEntry,
  ResumeProjectEntry,
  ResumeRecommendation,
  ResumeRecommendResponse,
} from '../types/resume';
import type { MasterProfile } from '../types/profile';
import type { ReactNode } from 'react';

function hasSavedProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

function toBackendUrl(path: string): string {
  const baseUrl = import.meta.env.VITE_API_BASE?.replace('/api/v1', '') || 'http://localhost:8000';
  return `${baseUrl}${path}`;
}

function updateEntryBullet<T extends ResumeExperienceEntry | ResumeProjectEntry>(
  entry: T,
  bulletIndex: number,
  text: string,
): T {
  const bullets = [...entry.bullets];
  bullets[bulletIndex] = {
    ...bullets[bulletIndex],
    text,
    status: 'edited',
  };
  return { ...entry, bullets };
}

function includedBulletsWithIndex(bullets: ResumeBullet[]): Array<{ bullet: ResumeBullet; index: number }> {
  return bullets
    .map((bullet, index) => ({ bullet, index }))
    .filter(({ bullet }) => bullet.status !== 'rejected');
}

function dedupeKeywords(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  values.forEach((value) => {
    const cleaned = value.trim();
    const key = cleaned.toLowerCase();
    if (!cleaned || seen.has(key)) return;
    seen.add(key);
    result.push(cleaned);
  });

  return result;
}

function keywordInstruction(keywords: string[]): string {
  return [
    `Naturally include these high-priority JD keywords: ${keywords.join(', ')}.`,
    'Prefer the target title, summary, technical skills, and top experience bullets.',
    'Keep the resume one page, avoid keyword stuffing, and do not copy JD phrasing awkwardly.',
  ].join(' ');
}

export default function ResumeReview() {
  const navigate = useNavigate();
  const {
    sessionId,
    parsedJD,
    recommendation,
    setRecommendation,
    atsScore,
    setAtsScore,
    alignmentReport,
    latexSource,
    setLatexSource,
    pipelinePdf,
    setPipelinePdf,
    setStep,
    activeProfile,
    setActiveProfile,
    setAlignmentReport,
    resetJobSession,
  } = useAppStore();

  const [focusKeywords, setFocusKeywords] = useState('');
  const [resolvedProfile, setResolvedProfile] = useState<MasterProfile | null>(activeProfile);
  const [isCheckingProfile, setIsCheckingProfile] = useState(false);
  const [blockingError, setBlockingError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [compileErrors, setCompileErrors] = useState<string[]>([]);
  const [compileWarnings, setCompileWarnings] = useState<string[]>([]);
  const [pdflatexExcerpt, setPdflatexExcerpt] = useState<string | null>(null);
  const [compileLineNumber, setCompileLineNumber] = useState<number | null>(null);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [coverLetterStatus, setCoverLetterStatus] = useState<string | null>(null);
  const [coverLetterText, setCoverLetterText] = useState('');

  useEffect(() => {
    let cancelled = false;

    async function resolveProfile() {
      if (!sessionId) {
        setResolvedProfile(null);
        setBlockingError('Missing session. Please analyze the JD again.');
        return;
      }

      if (!parsedJD) {
        setResolvedProfile(null);
        setBlockingError('Missing parsed JD. Please analyze the JD again.');
        return;
      }

      if (activeProfile) {
        setResolvedProfile(activeProfile);
        return;
      }

      setIsCheckingProfile(true);
      setBlockingError(null);

      try {
        const savedProfile = await getDefaultProfile();
        if (cancelled) return;

        if (!hasSavedProfile(savedProfile)) {
          setResolvedProfile(null);
          setActiveProfile(null);
          setBlockingError('No saved master profile found. Please save your profile before analyzing a job description.');
          return;
        }

        const normalizedProfile = sanitizeProfile(savedProfile);
        setResolvedProfile(normalizedProfile);
        setActiveProfile(normalizedProfile);
      } finally {
        if (!cancelled) setIsCheckingProfile(false);
      }
    }

    void resolveProfile();

    return () => {
      cancelled = true;
    };
  }, [activeProfile, parsedJD, sessionId, setActiveProfile]);

  const pdfUrl = pipelinePdf?.compile_success && pipelinePdf.pdf_url
    ? toBackendUrl(pipelinePdf.pdf_url)
    : null;

  const saveCurrentResume = async (overrides?: {
    pipelinePdf?: typeof pipelinePdf;
    coverLetterText?: string;
  }) => {
    if (!sessionId || !recommendation) return;
    await saveRecentResumeSnapshot({
      sessionId,
      parsedJD,
      recommendation,
      atsScore,
      pipelinePdf: overrides?.pipelinePdf ?? pipelinePdf,
      coverLetterText: overrides?.coverLetterText ?? coverLetterText,
    });
  };

  const approvePdfMutation = useMutation<ApproveGeneratePdfResponse, Error, ApproveGeneratePdfRequest>({
    mutationFn: approveGeneratePdf,
    onSuccess: (data) => {
      setLatexSource(data.latex_source || '');
      if (data.compile_success) {
        const nextPdf = {
          requested: true,
          compile_success: true,
          pdf_url: data.pdf_url,
          compile_errors: [],
          compile_warnings: data.compile_warnings || [],
          generated_tex_path: data.generated_tex_path,
          pdflatex_excerpt: data.pdflatex_excerpt,
          line_number: data.line_number,
        };
        setRenderError(null);
        setCompileErrors([]);
        setCompileWarnings([]);
        setPdflatexExcerpt(null);
        setCompileLineNumber(null);
        setPipelinePdf(nextPdf);
        void saveCurrentResume({ pipelinePdf: nextPdf });
        return;
      }

      const errors = data.compile_errors || ['PDF compilation failed.'];
      const warnings = data.compile_warnings || [];
      setPipelinePdf({
        requested: true,
        compile_success: false,
        pdf_url: undefined,
        compile_errors: errors,
        compile_warnings: warnings,
        generated_tex_path: data.generated_tex_path,
        pdflatex_excerpt: data.pdflatex_excerpt,
        line_number: data.line_number,
      });
      setRenderError('PDF generation failed, but your resume content is safe. Try Optimize Again or open Advanced LaTeX Editor.');
      setCompileErrors(errors);
      setCompileWarnings(warnings);
      setPdflatexExcerpt(data.pdflatex_excerpt ?? null);
      setCompileLineNumber(data.line_number ?? null);
    },
    onError: (error) => {
      setRenderError('PDF generation failed, but your resume content is safe. Try Optimize Again or open Advanced LaTeX Editor.');
      setCompileErrors([error.message || 'PDF generation failed. Please try again.']);
      setCompileWarnings([]);
      setPdflatexExcerpt(null);
      setCompileLineNumber(null);
    },
  });

  const validateMutation = useMutation({
    mutationFn: validateResume,
    onSuccess: (data) => setAtsScore(data.ats_score),
  });

  const regenerateMutation = useMutation({
    mutationFn: regenerateResume,
    onSuccess: (data: ResumeRecommendResponse) => {
      setRecommendation(data.recommendation);
      setAtsScore(null);
      setPipelinePdf(null);
      setRenderError(null);
      setCoverLetterText('');
      if (data.alignment_report) setAlignmentReport(data.alignment_report);
      if (sessionId) {
        validateMutation.mutate({
          session_id: sessionId,
          recommendation: data.recommendation,
        });
      }
      setFocusKeywords('');
    },
  });

  const coverLetterMutation = useMutation({
    mutationFn: generateCoverLetter,
    onSuccess: (data) => {
      setCoverLetterText(data.cover_letter_text);
      setCoverLetterStatus('Cover letter ready');
      void saveCurrentResume({ coverLetterText: data.cover_letter_text });
      window.setTimeout(() => setCoverLetterStatus(null), 2000);
    },
    onError: (error) => {
      setCoverLetterStatus(error instanceof Error ? error.message : 'Cover letter generation failed.');
    },
  });

  const docxMutation = useMutation({
    mutationFn: exportResumeDocx,
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'resume.docx';
      link.click();
      URL.revokeObjectURL(url);
      setCopyStatus('DOCX ready');
      window.setTimeout(() => setCopyStatus(null), 2000);
    },
    onError: (error) => {
      setRenderError(error instanceof Error ? error.message : 'DOCX export failed.');
    },
  });

  const commitRecommendation = (next: ResumeRecommendation) => {
    setRecommendation(next);
    setPipelinePdf(null);
    setRenderError(null);
    setCompileErrors([]);
    setCompileWarnings([]);
    setPdflatexExcerpt(null);
    setCompileLineNumber(null);
    setCoverLetterText('');
  };

  const handleSummaryChange = (summary: string) => {
    if (!recommendation) return;
    commitRecommendation({ ...recommendation, summary });
  };

  const handleExperienceBulletChange = (entryIndex: number, bulletIndex: number, text: string) => {
    if (!recommendation) return;
    const experience = [...recommendation.experience];
    experience[entryIndex] = updateEntryBullet(experience[entryIndex], bulletIndex, text);
    commitRecommendation({ ...recommendation, experience });
  };

  const handleProjectBulletChange = (entryIndex: number, bulletIndex: number, text: string) => {
    if (!recommendation) return;
    const projects = [...recommendation.projects];
    projects[entryIndex] = updateEntryBullet(projects[entryIndex], bulletIndex, text);
    commitRecommendation({ ...recommendation, projects });
  };

  const copyToClipboard = async (value: string, label: string) => {
    if (!value.trim()) return;
    await navigator.clipboard.writeText(value);
    setCopyStatus(`${label} copied`);
    window.setTimeout(() => setCopyStatus(null), 2000);
  };

  const handleCopyResume = () => {
    if (!recommendation) return;
    void copyToClipboard(recommendationToPlainText(recommendation), 'Resume');
  };

  const handleCopyMarkdown = () => {
    if (!recommendation) return;
    void copyToClipboard(recommendationToMarkdown(recommendation), 'Markdown resume');
  };

  const handleCopySummary = () => {
    if (!recommendation) return;
    void copyToClipboard(recommendationSummaryToText(recommendation), 'Summary');
  };

  const handleCopySkills = () => {
    if (!recommendation) return;
    void copyToClipboard(recommendationSkillsToText(recommendation), 'Skills');
  };

  const handleGeneratePdf = () => {
    if (!sessionId || !recommendation) return;
    setRenderError(null);
    setCompileErrors([]);
    setCompileWarnings([]);
    setPdflatexExcerpt(null);
    setCompileLineNumber(null);
    approvePdfMutation.mutate({ session_id: sessionId, recommendation });
  };

  const handleExportDocx = () => {
    if (!sessionId || !recommendation) return;
    setRenderError(null);
    docxMutation.mutate({ session_id: sessionId, recommendation });
  };

  const handleDownloadPdf = () => {
    if (pdfUrl) window.open(pdfUrl, '_blank');
  };

  const handleOptimizeAgain = () => {
    if (!sessionId || !resolvedProfile || !focusKeywords.trim()) return;
    regenerateMutation.mutate({
      session_id: sessionId,
      profile: resolvedProfile,
      emphasis: focusKeywords.trim(),
      additional_alignment_text: keywordInstruction([focusKeywords.trim()]),
      locked_bullet_ids: [],
      rejected_item_ids: [],
    });
  };

  const handleAddMissingKeywords = (keywords: string[]) => {
    if (!sessionId || !resolvedProfile || keywords.length === 0) return;
    const focusText = keywords.join(', ');
    regenerateMutation.mutate({
      session_id: sessionId,
      profile: resolvedProfile,
      emphasis: focusText,
      additional_alignment_text: keywordInstruction(keywords),
      locked_bullet_ids: [],
      rejected_item_ids: [],
    });
  };

  const handleGenerateCoverLetter = () => {
    if (!sessionId || !resolvedProfile || !parsedJD || !recommendation) return;
    setCoverLetterStatus(null);
    coverLetterMutation.mutate({
      session_id: sessionId,
      profile: resolvedProfile,
      parsed_jd: parsedJD,
      recommendation,
      job_title: recommendation.target_title,
      tone: 'Professional',
    });
  };

  const handleCopyCoverLetter = () => {
    if (!coverLetterText) return;
    void copyToClipboard(coverLetterText, 'Cover letter');
  };

  const handleNextJD = () => {
    void saveCurrentResume({ coverLetterText });
    resetJobSession();
    setStep('jd-input');
    navigate('/jd');
  };

  const handleOpenLatexEditor = () => {
    setStep('latex-editor');
    navigate('/editor');
  };

  if (blockingError) {
    return (
      <div className="empty-state">
        <div className="empty-icon">!</div>
        <div className="empty-title">Cannot open resume output</div>
        <div className="empty-description">{blockingError}</div>
        <div style={{ display: 'flex', gap: 'var(--space-md)', marginTop: 'var(--space-md)' }}>
          <button className="btn btn-secondary" onClick={() => navigate('/profile')}>Go to Profile</button>
          <button className="btn btn-primary" onClick={handleNextJD}>Go to JD Input</button>
        </div>
      </div>
    );
  }

  if (isCheckingProfile) {
    return (
      <div className="loading-state">
        <div className="spinner spinner-lg" />
        <div className="loading-text">Loading your saved master profile...</div>
      </div>
    );
  }

  if (!recommendation) {
    return (
      <div className="empty-state">
        <div className="empty-icon">Resume</div>
        <div className="empty-title">No resume available</div>
        <div className="empty-description">
          Paste a job description to generate a fast ATS resume output.
        </div>
        <button className="btn btn-primary" onClick={handleNextJD}>Go to JD Input</button>
      </div>
    );
  }

  const contact = recommendation.contact;
  const experiences = recommendation.experience.filter((entry) => entry.included);
  const projects = recommendation.projects.filter((entry) => entry.included);
  const certifications = recommendation.certifications.filter((entry) => entry.included);
  const achievements = [...(recommendation.achievements ?? []), ...(recommendation.awards ?? [])].filter((entry) => entry.included);
  const placement = alignmentReport?.keyword_placement;
  const missingImportantKeywords = dedupeKeywords([
    ...(placement?.missing_high_priority_keywords ?? []),
    ...(alignmentReport?.keywords_missing ?? []).slice(0, 6),
  ]).slice(0, 8);
  const weaklyPlacedKeywords = dedupeKeywords(placement?.weakly_placed_keywords ?? []).slice(0, 6);

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <h1 className="page-title">ATS Resume Ready</h1>
        <p className="page-subtitle">Review, copy, optimize, and export your one-page resume.</p>
      </div>

      <div
        style={{
          position: 'sticky',
          top: 'var(--space-md)',
          zIndex: 5,
          marginBottom: 'var(--space-lg)',
          padding: 'var(--space-md)',
          borderRadius: 'var(--radius-lg)',
          background: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          backdropFilter: 'blur(12px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 'var(--space-md)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-md)', flex: '1 1 520px' }}>
          <ATSCompactScoreCard
            atsScore={atsScore}
            alignmentReport={alignmentReport}
            compact
          />
          {copyStatus && <span style={{ color: 'var(--status-success)', fontSize: '0.85rem' }}>{copyStatus}</span>}
          {coverLetterStatus && <span style={{ color: coverLetterMutation.isError ? 'var(--status-danger)' : 'var(--status-success)', fontSize: '0.85rem' }}>{coverLetterStatus}</span>}
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
          <button className="btn btn-secondary" onClick={handleCopyResume}>Copy Resume</button>
          <button className="btn btn-secondary" onClick={handleCopyMarkdown}>Copy Markdown</button>
          <button className="btn btn-ghost" onClick={handleCopySummary}>Copy Summary</button>
          <button className="btn btn-ghost" onClick={handleCopySkills}>Copy Skills</button>
          <button className="btn btn-primary" onClick={handleExportDocx} disabled={docxMutation.isPending}>
            {docxMutation.isPending ? <span className="spinner" /> : null}
            {docxMutation.isPending ? 'Exporting...' : 'Download DOCX'}
          </button>
          {pdfUrl ? (
            <button className="btn btn-primary" onClick={handleDownloadPdf}>Download PDF</button>
          ) : (
            <button className="btn btn-secondary" onClick={handleGeneratePdf} disabled={approvePdfMutation.isPending}>
              {approvePdfMutation.isPending ? <span className="spinner" /> : null}
              {approvePdfMutation.isPending ? 'Generating...' : 'Generate PDF'}
            </button>
          )}
          <button className="btn btn-secondary" onClick={handleGenerateCoverLetter} disabled={coverLetterMutation.isPending || !resolvedProfile}>
            {coverLetterMutation.isPending ? <span className="spinner" /> : null}
            {coverLetterMutation.isPending ? 'Writing...' : coverLetterText ? 'Regenerate Cover Letter' : 'Generate Cover Letter'}
          </button>
          <button className="btn btn-secondary" onClick={handleCopyCoverLetter} disabled={!coverLetterText}>
            Copy Cover Letter
          </button>
          <button className="btn btn-ghost" onClick={handleOptimizeAgain} disabled={regenerateMutation.isPending || !focusKeywords.trim()}>
            {regenerateMutation.isPending ? <span className="spinner" /> : null}
            Optimize Again
          </button>
          <button className="btn btn-ghost" onClick={handleNextJD}>Next JD</button>
        </div>
      </div>

  {renderError && (
    <div className="warning-banner warning-error" style={{ marginBottom: 'var(--space-lg)' }}>
      <span>PDF</span>
      <div style={{ flex: 1 }}>
        <div>{renderError}</div>
        <div style={{ marginTop: 'var(--space-sm)', display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
          <button className="btn btn-ghost btn-sm" onClick={handleOptimizeAgain} disabled={regenerateMutation.isPending || !focusKeywords.trim()}>
            Optimize Again
          </button>
          <button className="btn btn-ghost btn-sm" onClick={handleOpenLatexEditor}>Open Advanced LaTeX Editor</button>
        </div>
        {(compileErrors.length > 0 || compileWarnings.length > 0 || pdflatexExcerpt) && (
          <details style={{ marginTop: 'var(--space-sm)' }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
              Advanced details
            </summary>
            <div style={{ marginTop: 'var(--space-xs)', fontSize: '0.8rem', fontFamily: 'monospace', whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto', background: 'var(--bg-glass)', padding: 'var(--space-sm)', borderRadius: 'var(--radius-md)' }}>
              {compileErrors.map((err, i) => (
                <div key={i} style={{ color: 'var(--status-danger)' }}>{err}</div>
              ))}
              {compileWarnings.map((w, i) => (
                <div key={i} style={{ color: 'var(--text-tertiary)' }}>{w}</div>
              ))}
              {compileLineNumber != null && (
                <div style={{ color: 'var(--text-secondary)' }}>Line: {compileLineNumber}</div>
              )}
              {pdflatexExcerpt && (
                <div style={{ marginTop: 'var(--space-xs)', color: 'var(--text-tertiary)' }}>{pdflatexExcerpt}</div>
              )}
            </div>
          </details>
        )}
      </div>
    </div>
  )}

      {regenerateMutation.isError && (
        <div className="warning-banner warning-error" style={{ marginBottom: 'var(--space-lg)' }}>
          <span>Optimize</span>
          <span>{regenerateMutation.error instanceof Error ? regenerateMutation.error.message : 'Could not improve resume.'}</span>
        </div>
      )}

      <div className="fast-console-layout">
        <div className="card" style={{ background: 'rgba(255, 255, 255, 0.03)' }}>
          <div style={{ maxWidth: 820, margin: '0 auto', color: 'var(--text-primary)' }}>
            {contact && (
              <section style={{ textAlign: 'center', marginBottom: 'var(--space-lg)' }}>
                <h2 style={{ margin: 0, fontSize: '1.7rem' }}>{contact.full_name}</h2>
                <div style={{ marginTop: 'var(--space-xs)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                  {[contact.email, contact.phone, contact.location, contact.linkedin_url, contact.github_url, contact.portfolio_url]
                    .filter(Boolean)
                    .join(' | ')}
                </div>
              </section>
            )}

            <section style={{ marginBottom: 'var(--space-lg)' }}>
              <h3 style={{ margin: 0, fontSize: '1.15rem' }}>{recommendation.target_title}</h3>
              <textarea
                className="form-textarea"
                value={recommendation.summary || ''}
                onChange={(event) => handleSummaryChange(event.target.value)}
                placeholder="Add a concise ATS summary..."
                style={{ marginTop: 'var(--space-sm)', minHeight: 90, background: 'var(--bg-glass)' }}
              />
            </section>

            {recommendation.skills.length > 0 && (
              <ResumeSection title="Technical Skills">
                {recommendation.skills.map((group) => (
                  <div key={group.category} style={{ marginBottom: '6px', fontSize: '0.9rem' }}>
                    <strong>{group.category}:</strong> {group.skills.join(', ')}
                  </div>
                ))}
              </ResumeSection>
            )}

            {experiences.length > 0 && (
              <ResumeSection title="Experience">
                {experiences.map((entry, entryIndex) => (
                  <div key={entry.source_id} style={{ marginBottom: 'var(--space-md)' }}>
                    <EntryHeader
                      title={entry.title}
                      subtitle={entry.company}
                      meta={`${entry.start_date} - ${entry.end_date || 'Present'}`}
                    />
                    <EditableBulletList
                      bullets={includedBulletsWithIndex(entry.bullets)}
                      onChange={(bulletIndex, text) => handleExperienceBulletChange(entryIndex, bulletIndex, text)}
                    />
                  </div>
                ))}
              </ResumeSection>
            )}

            {projects.length > 0 && (
              <ResumeSection title="Projects">
                {projects.map((entry, entryIndex) => (
                  <div key={entry.source_id} style={{ marginBottom: 'var(--space-md)' }}>
                    <EntryHeader
                      title={entry.name}
                      subtitle={entry.technologies.join(', ')}
                    />
                    <EditableBulletList
                      bullets={includedBulletsWithIndex(entry.bullets)}
                      onChange={(bulletIndex, text) => handleProjectBulletChange(entryIndex, bulletIndex, text)}
                    />
                  </div>
                ))}
              </ResumeSection>
            )}

            {recommendation.education.length > 0 && (
              <ResumeSection title="Education">
                {recommendation.education.map((entry) => (
                  <div key={entry.source_id} style={{ marginBottom: '6px', fontSize: '0.9rem' }}>
                    <strong>{entry.institution}</strong>
                    <span style={{ color: 'var(--text-secondary)' }}>
                      {' '}| {[entry.degree, entry.field_of_study, entry.gpa].filter(Boolean).join(', ')}
                    </span>
                  </div>
                ))}
              </ResumeSection>
            )}

            {certifications.length > 0 && (
              <ResumeSection title="Certifications">
                {certifications.map((entry) => (
                  <div key={entry.source_id} style={{ marginBottom: '6px', fontSize: '0.9rem' }}>
                    <strong>{entry.name}</strong>
                    <span style={{ color: 'var(--text-secondary)' }}>
                      {' '}| {[entry.issuing_org, entry.date].filter(Boolean).join(' | ')}
                    </span>
                  </div>
                ))}
              </ResumeSection>
            )}

            {achievements.length > 0 && (
              <ResumeSection title="Achievements">
                {achievements.map((entry) => (
                  <div key={entry.source_id} style={{ marginBottom: '6px', fontSize: '0.9rem' }}>
                    <strong>{entry.title}</strong>
                    <span style={{ color: 'var(--text-secondary)' }}>
                      {' '}| {[entry.issuer, entry.date, entry.description].filter(Boolean).join(' | ')}
                    </span>
                  </div>
                ))}
              </ResumeSection>
            )}

            {(recommendation.custom_sections ?? []).filter((entry) => entry.included && entry.items.length > 0).map((entry) => (
              <ResumeSection key={entry.title} title={entry.title}>
                {entry.items.map((item) => (
                  <div key={item} style={{ marginBottom: '6px', fontSize: '0.9rem' }}>- {item}</div>
                ))}
              </ResumeSection>
            ))}
          </div>
        </div>

        <aside className="fast-console-side">
          <div className="card">
            <div className="card-title" style={{ marginBottom: 'var(--space-md)' }}>Optimization</div>
            {(missingImportantKeywords.length > 0 || weaklyPlacedKeywords.length > 0) && (
              <div style={{ marginBottom: 'var(--space-md)', display: 'grid', gap: 'var(--space-sm)' }}>
                {missingImportantKeywords.length > 0 && (
                  <div>
                    <div className="form-label">Missing important keywords</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      {missingImportantKeywords.map((keyword) => (
                        <span key={keyword} className="keyword-tag keyword-missing">{keyword}</span>
                      ))}
                    </div>
                  </div>
                )}
                {weaklyPlacedKeywords.length > 0 && (
                  <div>
                    <div className="form-label">Weak keyword placement</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                      {weaklyPlacedKeywords.map((keyword) => (
                        <span key={keyword} className="keyword-tag">{keyword}</span>
                      ))}
                    </div>
                  </div>
                )}
                <button
                  className="btn btn-secondary"
                  style={{ width: '100%' }}
                  onClick={() => handleAddMissingKeywords(dedupeKeywords([...missingImportantKeywords, ...weaklyPlacedKeywords]))}
                  disabled={regenerateMutation.isPending || !resolvedProfile}
                >
                  {regenerateMutation.isPending ? <span className="spinner" /> : null}
                  Add missing keywords naturally
                </button>
              </div>
            )}
            <div className="form-group" style={{ marginBottom: 'var(--space-sm)' }}>
              <label className="form-label">Optimize Again</label>
              <input
                className="form-input"
                value={focusKeywords}
                onChange={(event) => setFocusKeywords(event.target.value)}
                placeholder="Add focus keywords, e.g. Java, Jenkins, OBDX..."
                disabled={regenerateMutation.isPending}
              />
            </div>
            <button className="btn btn-primary" style={{ width: '100%' }} onClick={handleOptimizeAgain} disabled={regenerateMutation.isPending || !focusKeywords.trim()}>
              {regenerateMutation.isPending ? <span className="spinner" /> : null}
              {regenerateMutation.isPending ? 'Improving...' : 'Improve Resume'}
            </button>
            <button className="btn btn-secondary" style={{ width: '100%', marginTop: 'var(--space-sm)' }} onClick={() => recommendation && validateMutation.mutate({ session_id: sessionId || '', recommendation })} disabled={validateMutation.isPending || !sessionId}>
              {validateMutation.isPending ? <span className="spinner" /> : null}
              Refresh Score
            </button>
          </div>

          {latexSource && (
            <details className="card">
              <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Advanced</summary>
              <button className="btn btn-ghost btn-sm" style={{ marginTop: 'var(--space-md)' }} onClick={handleOpenLatexEditor}>
                Open LaTeX editor
              </button>
            </details>
          )}
        </aside>
      </div>
    </div>
  );
}

function ResumeSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginBottom: 'var(--space-lg)' }}>
      <h3
        style={{
          margin: '0 0 var(--space-sm)',
          paddingBottom: '6px',
          borderBottom: '1px solid var(--border-medium)',
          fontSize: '0.9rem',
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
        }}
      >
        {title}
      </h3>
      {children}
    </section>
  );
}

function EntryHeader({ title, subtitle, meta }: { title: string; subtitle?: string; meta?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-md)', marginBottom: '6px' }}>
      <div>
        <div style={{ fontWeight: 700 }}>{title}</div>
        {subtitle && <div style={{ color: 'var(--text-secondary)', fontSize: '0.86rem' }}>{subtitle}</div>}
      </div>
      {meta && <div style={{ color: 'var(--text-tertiary)', fontSize: '0.82rem', whiteSpace: 'nowrap' }}>{meta}</div>}
    </div>
  );
}

function EditableBulletList({
  bullets,
  onChange,
}: {
  bullets: Array<{ bullet: ResumeBullet; index: number }>;
  onChange: (bulletIndex: number, text: string) => void;
}) {
  return (
    <div style={{ display: 'grid', gap: '6px' }}>
      {bullets.map(({ bullet, index }) => (
        <div key={bullet.id} style={{ display: 'grid', gridTemplateColumns: '18px minmax(0, 1fr)', gap: '6px', alignItems: 'start' }}>
          <span style={{ color: 'var(--text-secondary)', lineHeight: '34px' }}>-</span>
          <textarea
            className="form-textarea"
            value={bullet.text}
            onChange={(event) => onChange(index, event.target.value)}
            style={{ minHeight: 44, padding: '8px 10px', resize: 'vertical', background: 'var(--bg-glass)' }}
          />
        </div>
      ))}
    </div>
  );
}
