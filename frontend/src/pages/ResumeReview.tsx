/**
 * Resume Review page — the human-in-the-loop review interface.
 *
 * User can:
 * - Accept/reject experiences, projects, certifications
 * - Edit, lock, or reject individual bullets
 * - Regenerate with different emphasis
 * - See ATS score, keyword coverage, readability score
 * - See warnings for weak JD / weak profile
 */

import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { approveGeneratePdf, recommendResume, regenerateResume, validateResume } from '../lib/api';
import AlignmentMetricsPanel from '../components/AlignmentMetricsPanel';
import { getDefaultProfile } from '../lib/db';
import { sanitizeProfile } from '../lib/profile';
import { useAppStore } from '../store/useAppStore';
import type {
  ResumeExperienceEntry,
  ResumeProjectEntry,
  ResumeBullet,
  BulletStatus,
  ApproveGeneratePdfRequest,
  ApproveGeneratePdfResponse,
  ResumeRecommendResponse,
} from '../types/resume';
import type { MasterProfile } from '../types/profile';

function hasSavedProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

type ReviewSection = 'experience' | 'projects';

function updateEntryBullet<T extends ResumeExperienceEntry | ResumeProjectEntry>(
  entry: T,
  bulletIndex: number,
  updater: (bullet: ResumeBullet) => ResumeBullet,
): T {
  const bullets = [...entry.bullets];
  bullets[bulletIndex] = updater(bullets[bulletIndex]);
  return { ...entry, bullets };
}

export default function ResumeReview() {
const navigate = useNavigate();
  const {
    sessionId, parsedJD, recommendation, setRecommendation,
    atsScore, setAtsScore, latexSource, setLatexSource, setPipelinePdf, setStep,
    setActiveProfile, pipelinePdf, setAlignmentReport, alignmentReport,
  } = useAppStore();

  const [emphasis, setEmphasis] = useState('');
  const [additionalContext, setAdditionalContext] = useState('');
  const [activeTab, setActiveTab] = useState<'experience' | 'projects' | 'skills' | 'scores'>('experience');
  const [resolvedProfile, setResolvedProfile] = useState<MasterProfile | null>(null);
  const [isCheckingProfile, setIsCheckingProfile] = useState(false);
  const [blockingError, setBlockingError] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  // Resolve the saved profile from IndexedDB before allowing recommendation.
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
        if (!cancelled) {
          setIsCheckingProfile(false);
        }
      }
    }

    void resolveProfile();

    return () => {
      cancelled = true;
    };
  }, [sessionId, parsedJD, setActiveProfile]);

  // ── Generate recommendation on mount if needed ─────────────────────────
  const recommendMutation = useMutation({
    mutationFn: recommendResume,
    onSuccess: (data) => setRecommendation(data.recommendation),
  });

  const regenerateMutation = useMutation({
    mutationFn: regenerateResume,
    onSuccess: (data: ResumeRecommendResponse) => {
      setRecommendation(data.recommendation);
      if (data.alignment_report) {
        setAlignmentReport(data.alignment_report);
      }
    },
  });

  const validateMutation = useMutation({
    mutationFn: validateResume,
    onSuccess: (data) => setAtsScore(data.ats_score),
  });

  const approvePdfMutation = useMutation<ApproveGeneratePdfResponse, Error, ApproveGeneratePdfRequest>({
    mutationFn: approveGeneratePdf,
    onSuccess: (data) => {
      if (data.compile_success) {
        setRenderError(null);
        setLatexSource(data.latex_source);
        setPipelinePdf({
          requested: true,
          compile_success: true,
          pdf_url: data.pdf_url,
          compile_errors: [],
          compile_warnings: data.compile_warnings || [],
          generated_tex_path: data.generated_tex_path,
          pdflatex_excerpt: data.pdflatex_excerpt,
          line_number: data.line_number,
        });
        setStep('latex-editor');
        navigate('/editor');
        return;
      }

      setLatexSource(data.latex_source || '');
      setPipelinePdf({
        requested: true,
        compile_success: false,
        pdf_url: undefined,
        compile_errors: data.compile_errors || ['PDF compilation failed.'],
        compile_warnings: data.compile_warnings || [],
        generated_tex_path: data.generated_tex_path,
        pdflatex_excerpt: data.pdflatex_excerpt,
        line_number: data.line_number,
      });
      setRenderError((data.compile_errors || ['PDF compilation failed.']).join('; '));
    },
    onError: (error) => {
      setRenderError(error.message || 'PDF generation failed. Please try again.');
    },
  });

  // ── Handlers ───────────────────────────────────────────────────────────
  const getRejectedIds = useCallback((): string[] => {
    if (!recommendation) return [];
    const rejected: string[] = [];
    recommendation.experience.forEach((e) => { if (!e.included) rejected.push(e.source_id); });
    recommendation.projects.forEach((p) => { if (!p.included) rejected.push(p.source_id); });
    return rejected;
  }, [recommendation]);

  const getLockedBulletIds = useCallback((): string[] => {
    if (!recommendation) return [];
    const locked: string[] = [];
    recommendation.experience.forEach((e) => e.bullets.forEach((b) => { if (b.status === 'locked') locked.push(b.id); }));
    recommendation.projects.forEach((p) => p.bullets.forEach((b) => { if (b.status === 'locked') locked.push(b.id); }));
    return locked;
  }, [recommendation]);

  const handleRegenerate = () => {
    if (!sessionId || !parsedJD || !resolvedProfile) return;
    regenerateMutation.mutate({
      session_id: sessionId,
      profile: resolvedProfile,
      emphasis: emphasis || undefined,
      additional_alignment_text: additionalContext || undefined,
      locked_bullet_ids: getLockedBulletIds(),
      rejected_item_ids: getRejectedIds(),
    });
  };

const handleValidate = () => {
    if (!sessionId || !recommendation || !parsedJD) return;
    validateMutation.mutate({
      session_id: sessionId,
      recommendation,
    });
  };

  const handleOpenLatexEditor = () => {
    setStep('latex-editor');
    navigate('/editor');
  };

  const updateBulletStatus = (expIndex: number, bulletIndex: number, status: BulletStatus, section: ReviewSection) => {
    if (!recommendation) return;
    if (section === 'experience') {
      const experience = [...recommendation.experience];
      experience[expIndex] = updateEntryBullet(experience[expIndex], bulletIndex, (bullet) => ({ ...bullet, status }));
      setRecommendation({ ...recommendation, experience });
      return;
    }

    const projects = [...recommendation.projects];
    projects[expIndex] = updateEntryBullet(projects[expIndex], bulletIndex, (bullet) => ({ ...bullet, status }));
    setRecommendation({ ...recommendation, projects });
  };

  const updateBulletText = (expIndex: number, bulletIndex: number, text: string, section: ReviewSection) => {
    if (!recommendation) return;
    if (section === 'experience') {
      const experience = [...recommendation.experience];
      experience[expIndex] = updateEntryBullet(experience[expIndex], bulletIndex, (bullet) => ({ ...bullet, text, status: 'edited' }));
      setRecommendation({ ...recommendation, experience });
      return;
    }

    const projects = [...recommendation.projects];
    projects[expIndex] = updateEntryBullet(projects[expIndex], bulletIndex, (bullet) => ({ ...bullet, text, status: 'edited' }));
    setRecommendation({ ...recommendation, projects });
  };

  const toggleIncluded = (index: number, section: ReviewSection) => {
    if (!recommendation) return;
    if (section === 'experience') {
      const experience = [...recommendation.experience];
      experience[index] = { ...experience[index], included: !experience[index].included };
      setRecommendation({ ...recommendation, experience });
      return;
    }

    const projects = [...recommendation.projects];
    projects[index] = { ...projects[index], included: !projects[index].included };
    setRecommendation({ ...recommendation, projects });
  };

  // ── Loading state ──────────────────────────────────────────────────────
  if (blockingError) {
    return (
      <div className="empty-state">
        <div className="empty-icon">❌</div>
        <div className="empty-title">Cannot Start Review</div>
        <div className="empty-description">{blockingError}</div>
        <div style={{ display: 'flex', gap: 'var(--space-md)', marginTop: 'var(--space-md)' }}>
          <button className="btn btn-secondary" onClick={() => navigate('/profile')}>Go to Profile</button>
          <button className="btn btn-primary" onClick={() => navigate('/jd')}>Go to JD Input</button>
        </div>
      </div>
    );
  }

  // Show error if recommendation failed
  if (recommendMutation.isError) {
    return (
      <div className="empty-state">
        <div className="empty-icon">❌</div>
        <div className="empty-title">Resume Generation Failed</div>
        <div className="empty-description" style={{ color: 'var(--text-danger)' }}>
          {(recommendMutation.error as Error).message || 'Something went wrong during AI analysis.'}
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-md)', marginTop: 'var(--space-md)' }}>
          <button className="btn btn-secondary" onClick={() => navigate('/profile')}>Check Profile</button>
          <button className="btn btn-primary" onClick={() => {
            if (sessionId && parsedJD && resolvedProfile) {
              recommendMutation.mutate({
                session_id: sessionId,
                profile: resolvedProfile,
                emphasis: emphasis || undefined,
                rejected_item_ids: [],
              });
            }
          }}>🔄 Retry</button>
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

  if (recommendMutation.isPending) {
    return (
      <div className="loading-state">
        <div className="spinner spinner-lg" />
        <div className="loading-text">AI is analyzing your profile against the job description...</div>
        <div style={{ color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>This may take 15-30 seconds</div>
      </div>
    );
  }

  if (!recommendation) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📄</div>
        <div className="empty-title">No recommendation available</div>
        <div className="empty-description">
          Resume recommendations are kept only for the active browser session. Please analyze the job description again to regenerate the review content.
        </div>
        <button className="btn btn-primary" onClick={() => navigate('/jd')}>Go to JD Input</button>
      </div>
    );
  }

const rec = recommendation;

  const handleApprovePdf = () => {
    if (!sessionId || !recommendation) return;
    setRenderError(null);
    approvePdfMutation.mutate({
      session_id: sessionId,
      recommendation,
    });
  };

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 className="page-title">Review Resume</h1>
          <p className="page-subtitle">
            Review AI recommendations. Accept, edit, lock, or reject items before generating PDF.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
          <button className="btn btn-primary" onClick={handleApprovePdf} disabled={approvePdfMutation.isPending}>
            {approvePdfMutation.isPending ? (
              <>
                <span className="spinner" />
                Generating PDF...
              </>
            ) : (
              '✓ Approve & Generate PDF'
            )}
          </button>
        </div>
      </div>

      <AlignmentMetricsPanel alignmentReport={alignmentReport} atsScore={atsScore} />

      {/* ATS Score Card - Prominent display */}
      {atsScore && (
        <div className="card" style={{ marginBottom: 'var(--space-lg)', background: 'linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-tertiary) 100%)', border: '1px solid var(--border-color)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-md)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-lg)' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '2.5rem', fontWeight: 700, color: atsScore.overall_score >= 75 ? 'var(--status-success)' : atsScore.overall_score >= 50 ? 'var(--status-warning)' : 'var(--status-danger)' }}>
                  {Math.round(atsScore.overall_score)}
                </div>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Overall ATS Score</div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-xs)' }}>
                <div style={{ display: 'flex', gap: 'var(--space-md)', fontSize: '0.9rem' }}>
                  <span><strong>{Math.round(atsScore.keyword_score.coverage_percent)}%</strong> Keywords</span>
                  <span><strong>{Math.round(atsScore.skill_score.required_coverage_percent)}%</strong> Required Skills</span>
                  <span><strong>{Math.round(atsScore.responsibility_score)}%</strong> Responsibilities</span>
                </div>
                <div style={{ display: 'flex', gap: 'var(--space-md)', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  <span><strong>{Math.round(atsScore.format_score)}</strong> Format</span>
                  <span><strong>{Math.round(atsScore.section_score.score)}</strong> Sections</span>
                  <span><strong>{Math.round(atsScore.title_alignment_score)}</strong> Title Match</span>
                </div>
              </div>
            </div>
            <button className="btn btn-secondary" onClick={handleValidate} disabled={validateMutation.isPending}>
              {validateMutation.isPending ? <span className="spinner" /> : '🔄 Recalculate Score'}
            </button>
          </div>
          {atsScore.missing_keywords.length > 0 && (
            <div style={{ marginTop: 'var(--space-md)', paddingTop: 'var(--space-md)', borderTop: '1px solid var(--border-color)' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 'var(--space-xs)' }}>Missing Keywords:</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {atsScore.missing_keywords.slice(0, 10).map((kw) => (
                  <span key={kw} className="keyword-tag keyword-missing">{kw}</span>
                ))}
              </div>
            </div>
          )}
          {atsScore.recommendations.length > 0 && (
            <div style={{ marginTop: 'var(--space-md)', paddingTop: 'var(--space-md)', borderTop: '1px solid var(--border-color)' }}>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 'var(--space-xs)' }}>Recommendations:</div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                {atsScore.recommendations.slice(0, 3).join(' • ')}
              </div>
            </div>
          )}
        </div>
      )}

      {/* PDF Generation Success Message */}
      {pipelinePdf?.requested && pipelinePdf.compile_success && (
        <div className="warning-banner" style={{ marginBottom: 'var(--space-md)', background: 'var(--status-success)', color: 'white' }}>
          <span>✓</span>
          <span>PDF generated successfully! You can download it or edit the LaTeX source.</span>
        </div>
      )}

{/* PDF Failure - Show on review page */}
      {(renderError || (pipelinePdf?.requested && !pipelinePdf.compile_success)) && (
        <div className="card" style={{ marginBottom: 'var(--space-xl)', borderColor: 'var(--status-danger)', background: 'var(--bg-tertiary)' }}>
          <div className="card-title" style={{ marginBottom: 'var(--space-sm)', color: 'var(--status-danger)' }}>
            ⚠️ PDF Generation Failed
          </div>
          <p style={{ marginTop: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            {renderError || pipelinePdf?.compile_errors.join('; ') || 'PDF compilation failed. Your resume is ready for review below - try regenerating or open the LaTeX editor to fix the issue.'}
          </p>
          {pipelinePdf?.line_number && (
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              Approximate LaTeX line: <strong>{pipelinePdf.line_number}</strong>
            </p>
          )}
          <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap', marginTop: 'var(--space-md)' }}>
            <button className="btn btn-secondary" onClick={handleRegenerate} disabled={regenerateMutation.isPending}>
              {regenerateMutation.isPending ? <span className="spinner" /> : '🔄 Regenerate'}
            </button>
            {latexSource && (
              <button className="btn btn-primary" onClick={handleOpenLatexEditor}>
                Open LaTeX Editor
              </button>
            )}
          </div>
        </div>
)}

      {/* Regeneration Controls */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)', background: 'var(--bg-secondary)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-md)' }}>
          <div className="card-title" style={{ marginBottom: 0 }}>🔄 Regenerate Resume</div>
          <button className="btn btn-primary" onClick={handleRegenerate} disabled={regenerateMutation.isPending}>
            {regenerateMutation.isPending ? (
              <>
                <span className="spinner" />
                Regenerating...
              </>
            ) : (
              'Regenerate for higher ATS score'
            )}
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 'var(--space-md)' }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Focus keywords / Emphasis</label>
            <input
              className="form-input"
              value={emphasis}
              onChange={(e) => setEmphasis(e.target.value)}
              placeholder="e.g. leadership, backend, OBDX, microservices"
              disabled={regenerateMutation.isPending}
            />
            <div className="form-hint">Optional: highlight specific skills or areas</div>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label">Additional context</label>
            <textarea
              className="form-textarea"
              value={additionalContext}
              onChange={(e) => setAdditionalContext(e.target.value)}
              placeholder="Add specific JD keywords, tools, or responsibilities to emphasize..."
              style={{ minHeight: 70 }}
              disabled={regenerateMutation.isPending}
            />
          </div>
        </div>
      </div>

      {/* Resume Title & Summary */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div className="card-title">📌 {rec.target_title}</div>
        {rec.summary && (
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: 'var(--space-sm)', lineHeight: 1.6 }}>
            {rec.summary}
          </p>
        )}
      </div>

      {/* Tabs */}
      <div className="tabs">
        {[
          { key: 'experience' as const, label: `Experience (${rec.experience.length})` },
          { key: 'projects' as const, label: `Projects (${rec.projects.length})` },
          { key: 'skills' as const, label: `Skills (${rec.skills.length} groups)` },
          { key: 'scores' as const, label: 'Keywords' },
        ].map((t) => (
          <button key={t.key} className={`tab ${activeTab === t.key ? 'active' : ''}`} onClick={() => setActiveTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Experience Tab */}
      {activeTab === 'experience' && rec.experience.map((exp, ei) => (
        <div key={exp.source_id} className="experience-card" style={{ opacity: exp.included ? 1 : 0.4 }}>
          <div className="experience-header">
            <div>
              <div className="experience-title">{exp.title}</div>
              <div className="experience-company">{exp.company}{exp.location ? ` • ${exp.location}` : ''}</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <div className="experience-dates">{exp.start_date} — {exp.end_date || 'Present'}</div>
              <div className="relevance-bar">
                <div className="relevance-fill" style={{
                  width: `${exp.relevance_score * 100}%`,
                  background: exp.relevance_score > 0.7 ? 'var(--status-success)' : exp.relevance_score > 0.4 ? 'var(--status-warning)' : 'var(--status-danger)',
                }} />
              </div>
              <button
                className={`btn btn-sm ${exp.included ? 'btn-danger' : 'btn-success'}`}
                onClick={() => toggleIncluded(ei, 'experience')}
              >
                {exp.included ? 'Exclude' : 'Include'}
              </button>
            </div>
          </div>

          {exp.included && exp.bullets.map((bullet, bi) => (
            <BulletReviewItem
              key={bullet.id}
              bullet={bullet}
              onStatusChange={(status) => updateBulletStatus(ei, bi, status, 'experience')}
              onTextChange={(text) => updateBulletText(ei, bi, text, 'experience')}
            />
          ))}
        </div>
      ))}

      {/* Projects Tab */}
      {activeTab === 'projects' && rec.projects.map((proj, pi) => (
        <div key={proj.source_id} className="experience-card" style={{ opacity: proj.included ? 1 : 0.4 }}>
          <div className="experience-header">
            <div>
              <div className="experience-title">{proj.name}</div>
              <div className="experience-company">{proj.technologies.join(', ')}</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-sm)' }}>
              <button
                className={`btn btn-sm ${proj.included ? 'btn-danger' : 'btn-success'}`}
                onClick={() => toggleIncluded(pi, 'projects')}
              >
                {proj.included ? 'Exclude' : 'Include'}
              </button>
            </div>
          </div>

          {proj.included && proj.bullets.map((bullet, bi) => (
            <BulletReviewItem
              key={bullet.id}
              bullet={bullet}
              onStatusChange={(status) => updateBulletStatus(pi, bi, status, 'projects')}
              onTextChange={(text) => updateBulletText(pi, bi, text, 'projects')}
            />
          ))}
        </div>
      ))}

      {/* Skills Tab */}
      {activeTab === 'skills' && (
        <div className="card">
          {rec.skills.map((sg, i) => (
            <div key={i} style={{ marginBottom: 'var(--space-md)' }}>
              <div style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: 'var(--space-xs)' }}>{sg.category}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {sg.skills.map((skill) => (
                  <span key={skill} className="badge badge-info">{skill}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Keywords Tab */}
      {activeTab === 'scores' && parsedJD && (
        <div className="card">
          <div className="card-title" style={{ marginBottom: 'var(--space-lg)' }}>JD Keywords</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {parsedJD.keywords.map((kw) => {
              // Check if keyword exists in recommendation text
              const recText = JSON.stringify(rec).toLowerCase();
              const found = recText.includes(kw.keyword.toLowerCase());
              return (
                <span key={kw.keyword} className={`keyword-tag ${found ? 'keyword-found' : 'keyword-missing'}`}>
                  {kw.keyword}
                  {kw.importance === 'critical' && ' ★'}
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Bullet Review Component ────────────────────────────────────────────────

function BulletReviewItem({
  bullet,
  onStatusChange,
  onTextChange,
}: {
  bullet: ResumeBullet;
  onStatusChange: (status: BulletStatus) => void;
  onTextChange: (text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(bullet.text);

  const statusClass = {
    pending: '',
    accepted: 'bullet-accepted',
    edited: 'bullet-accepted',
    locked: 'bullet-locked',
    rejected: 'bullet-rejected',
  }[bullet.status];

  const statusBadge = {
    pending: <span className="badge badge-neutral">Pending</span>,
    accepted: <span className="badge badge-success">Accepted</span>,
    edited: <span className="badge badge-success">Edited</span>,
    locked: <span className="badge badge-info">🔒 Locked</span>,
    rejected: <span className="badge badge-danger">Rejected</span>,
  }[bullet.status];

  const handleSaveEdit = () => {
    onTextChange(editText);
    setEditing(false);
  };

  return (
    <div className={`bullet-item ${statusClass}`} style={{ marginBottom: 'var(--space-sm)' }}>
      <div style={{ flex: 1 }}>
        {editing ? (
          <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
            <textarea
              className="form-textarea"
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              style={{ minHeight: '60px', fontSize: '0.85rem' }}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <button className="btn btn-success btn-sm" onClick={handleSaveEdit}>Save</button>
              <button className="btn btn-ghost btn-sm" onClick={() => { setEditing(false); setEditText(bullet.text); }}>Cancel</button>
            </div>
          </div>
        ) : (
          <>
            <div className="bullet-text">• {bullet.text}</div>
            {bullet.matched_keywords.length > 0 && (
              <div className="bullet-keywords">
                {bullet.matched_keywords.map((kw) => (
                  <span key={kw} className="keyword-tag keyword-found">{kw}</span>
                ))}
              </div>
            )}
          </>
        )}
      </div>
      <div className="bullet-actions" style={{ alignItems: 'center' }}>
        {statusBadge}
        {!editing && bullet.status !== 'rejected' && (
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => onStatusChange('accepted')} title="Accept">✓</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)} title="Edit">✏️</button>
            <button className="btn btn-ghost btn-sm" onClick={() => onStatusChange('locked')} title="Lock">🔒</button>
            <button className="btn btn-ghost btn-sm" onClick={() => onStatusChange('rejected')} title="Reject">✕</button>
          </>
        )}
        {bullet.status === 'rejected' && (
          <button className="btn btn-ghost btn-sm" onClick={() => onStatusChange('pending')} title="Restore">↩</button>
        )}
      </div>
</div>
  );
}
