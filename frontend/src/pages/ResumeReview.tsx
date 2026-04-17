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
import { recommendResume, regenerateResume, validateResume, renderLatex } from '../lib/api';
import { getDefaultProfile } from '../lib/db';
import { sanitizeProfile } from '../lib/profile';
import { useAppStore } from '../store/useAppStore';
import type {
  ResumeExperienceEntry,
  ResumeProjectEntry,
  ResumeBullet,
  BulletStatus,
  ATSScore,
} from '../types/resume';
import type { MasterProfile } from '../types/profile';

function hasSavedProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

export default function ResumeReview() {
  const navigate = useNavigate();
  const {
    sessionId, parsedJD, recommendation, setRecommendation,
    atsScore, setAtsScore, setLatexSource, setStep,
    setActiveProfile, warnings,
  } = useAppStore();

  const [emphasis, setEmphasis] = useState('');
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
    onSuccess: (data) => setRecommendation(data.recommendation),
  });

  const validateMutation = useMutation({
    mutationFn: validateResume,
    onSuccess: (data) => setAtsScore(data.ats_score),
  });

  const latexMutation = useMutation({
    mutationFn: renderLatex,
    onSuccess: (data) => {
      setRenderError(null);
      setLatexSource(data.latex_source);
      setStep('latex-editor');
      navigate('/editor');
    },
    onError: (error) => {
      setRenderError((error as Error).message || 'LaTeX rendering failed. Please try again.');
    },
  });

  useEffect(() => {
    if (
      !recommendation &&
      !recommendMutation.isPending &&
      !blockingError &&
      sessionId &&
      parsedJD &&
      resolvedProfile
    ) {
      recommendMutation.mutate({
        session_id: sessionId,
        profile: resolvedProfile,
        emphasis: emphasis || undefined,
        rejected_item_ids: [],
      });
    }
  }, [sessionId, parsedJD, resolvedProfile, blockingError]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const handleRenderLatex = () => {
    if (!sessionId || !recommendation) return;
    setRenderError(null);
    latexMutation.mutate({
      session_id: sessionId,
      recommendation,
    });
  };

  const updateBulletStatus = (expIndex: number, bulletIndex: number, status: BulletStatus, section: 'experience' | 'projects') => {
    if (!recommendation) return;
    const rec = { ...recommendation };
    const items = section === 'experience' ? [...rec.experience] : [...rec.projects];
    const item = { ...items[expIndex] };
    const bullets = [...item.bullets];
    bullets[bulletIndex] = { ...bullets[bulletIndex], status };
    item.bullets = bullets;
    items[expIndex] = item as any;
    if (section === 'experience') rec.experience = items as ResumeExperienceEntry[];
    else rec.projects = items as ResumeProjectEntry[];
    setRecommendation(rec);
  };

  const updateBulletText = (expIndex: number, bulletIndex: number, text: string, section: 'experience' | 'projects') => {
    if (!recommendation) return;
    const rec = { ...recommendation };
    const items = section === 'experience' ? [...rec.experience] : [...rec.projects];
    const item = { ...items[expIndex] };
    const bullets = [...item.bullets];
    bullets[bulletIndex] = { ...bullets[bulletIndex], text, status: 'edited' as BulletStatus };
    item.bullets = bullets;
    items[expIndex] = item as any;
    if (section === 'experience') rec.experience = items as ResumeExperienceEntry[];
    else rec.projects = items as ResumeProjectEntry[];
    setRecommendation(rec);
  };

  const toggleIncluded = (index: number, section: 'experience' | 'projects') => {
    if (!recommendation) return;
    const rec = { ...recommendation };
    if (section === 'experience') {
      const items = [...rec.experience];
      items[index] = { ...items[index], included: !items[index].included };
      rec.experience = items;
    } else {
      const items = [...rec.projects];
      items[index] = { ...items[index], included: !items[index].included };
      rec.projects = items;
    }
    setRecommendation(rec);
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
        <div className="empty-description">Please analyze the job description again to generate a resume recommendation.</div>
        <button className="btn btn-primary" onClick={() => navigate('/jd')}>Go to JD Input</button>
      </div>
    );
  }

  const rec = recommendation;

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 className="page-title">Review Resume</h1>
          <p className="page-subtitle">
            Review AI recommendations. Accept, edit, lock, or reject items before rendering.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-sm)' }}>
          <button className="btn btn-secondary" onClick={handleValidate} disabled={validateMutation.isPending}>
            {validateMutation.isPending ? <span className="spinner" /> : '📊'} Score
          </button>
          <button className="btn btn-primary" onClick={handleRenderLatex} disabled={latexMutation.isPending}>
            {latexMutation.isPending ? <span className="spinner" /> : '📑'} Render LaTeX
          </button>
        </div>
      </div>

      {/* Warnings */}
      {(rec.warnings.length > 0 || warnings.length > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-sm)', marginBottom: 'var(--space-xl)' }}>
          {[...warnings, ...rec.warnings].map((w, i) => (
            <div key={i} className="warning-banner warning-warn">
              <span>⚠️</span><span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {renderError && (
        <div className="warning-banner warning-error" style={{ marginBottom: 'var(--space-xl)' }}>
          <span>❌</span>
          <div>
            <strong>LaTeX Render Failed</strong>
            <p style={{ margin: 0, marginTop: '4px', fontSize: '0.8rem' }}>{renderError}</p>
          </div>
        </div>
      )}

      {/* Score Cards (if validated) */}
      {atsScore && <ScoreCards score={atsScore} />}

      {/* Regeneration Controls */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)', display: 'flex', gap: 'var(--space-md)', alignItems: 'center', flexWrap: 'wrap' }}>
        <div className="form-group" style={{ flex: 1, minWidth: '200px', marginBottom: 0 }}>
          <label className="form-label">Emphasis (optional)</label>
          <input className="form-input" value={emphasis} onChange={(e) => setEmphasis(e.target.value)} placeholder="e.g. leadership, backend, ML engineering" />
        </div>
        <button className="btn btn-secondary" onClick={handleRegenerate} disabled={regenerateMutation.isPending}>
          {regenerateMutation.isPending ? <span className="spinner" /> : '🔄'} Regenerate
        </button>
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

// ─── Score Cards Component ──────────────────────────────────────────────────

function ScoreCards({ score }: { score: ATSScore }) {
  const getScoreClass = (val: number) => val >= 75 ? 'score-high' : val >= 50 ? 'score-mid' : 'score-low';

  return (
    <div style={{ marginBottom: 'var(--space-xl)' }}>
      <div className="score-grid">
        <div className="score-card">
          <div className={`score-value ${getScoreClass(score.overall_score)}`}>{Math.round(score.overall_score)}</div>
          <div className="score-label">ATS Score</div>
        </div>
        <div className="score-card">
          <div className={`score-value ${getScoreClass(score.keyword_score.coverage_percent)}`}>
            {Math.round(score.keyword_score.coverage_percent)}%
          </div>
          <div className="score-label">Keyword Coverage</div>
        </div>
        <div className="score-card">
          <div className={`score-value ${getScoreClass(score.readability_score.score)}`}>
            {Math.round(score.readability_score.score)}
          </div>
          <div className="score-label">Readability</div>
        </div>
        <div className="score-card">
          <div className="score-value score-high">{Math.round(score.format_score)}</div>
          <div className="score-label">Format</div>
        </div>
      </div>

      {score.recommendations.length > 0 && (
        <div className="card" style={{ marginTop: 'var(--space-md)' }}>
          <div className="card-title" style={{ marginBottom: 'var(--space-sm)' }}>💡 Recommendations</div>
          {score.recommendations.map((r, i) => (
            <div key={i} className="warning-banner warning-info" style={{ marginBottom: 'var(--space-xs)' }}>
              <span>→</span><span>{r}</span>
            </div>
          ))}
        </div>
      )}

      {score.keyword_score.critical_missing.length > 0 && (
        <div className="card" style={{ marginTop: 'var(--space-md)' }}>
          <div className="card-title" style={{ marginBottom: 'var(--space-sm)' }}>🚨 Missing Critical Keywords</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {score.keyword_score.critical_missing.map((kw) => (
              <span key={kw} className="keyword-tag keyword-missing">{kw}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
