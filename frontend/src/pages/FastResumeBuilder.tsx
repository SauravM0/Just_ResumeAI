import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import PageHeader from '../components/ui/PageHeader';
import { exportDocx, exportPdf, generateFastResume } from '../lib/api';
import { getMyProfile } from '../lib/profileApi';
import { getSettings } from '../lib/settingsApi';
import { sanitizeProfile } from '../lib/profile';
import { objectArray, stringArray } from '../lib/resumeSafe';
import { useAppStore } from '../store/useAppStore';
import type { ExportFileResponse, FastResumeGenerateResponse, ResumeRecommendation } from '../types/resume';
import type { MasterProfile } from '../types/profile';

function hasUsableProfile(profile: MasterProfile | null): profile is MasterProfile {
  return Boolean(profile?.contact.full_name?.trim());
}

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

export default function FastResumeBuilder() {
  const navigate = useNavigate();
  const [profile, setProfile] = useState<MasterProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(true);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [rawJD, setRawJD] = useState('');
  const [targetPages, setTargetPages] = useState<1 | 2>(1);
  const [atsOptimizationMode, setAtsOptimizationMode] = useState<'realistic' | 'aggressive'>('aggressive');
  const [result, setResult] = useState<FastResumeGenerateResponse | null>(null);
  const [exportStatus, setExportStatus] = useState<string | null>(null);

  const {
    setGenerationId,
    setRecommendation,
    setAtsScore,
    setActiveProfile,
    setStep,
  } = useAppStore();

  useEffect(() => {
    let cancelled = false;
    setProfileLoading(true);
    setProfileError(null);

    getMyProfile()
      .then((response) => {
        if (cancelled) return;
        const normalized = response.profile_json ? sanitizeProfile(response.profile_json) : null;
        setProfile(normalized);
        setActiveProfile(normalized);
        if (!hasUsableProfile(normalized)) {
          setProfileError('Add your name and core experience to your master profile before generating.');
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setProfileError(error instanceof Error ? error.message : 'Unable to load your master profile.');
        }
      })
      .finally(() => {
        if (!cancelled) setProfileLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [setActiveProfile]);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((settings) => {
        if (!cancelled && settings.aggressive_ats_default) {
          setAtsOptimizationMode('aggressive');
        }
      })
      .catch(() => {
        // Fast generation can continue with realistic mode if settings are unavailable.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const generateMutation = useMutation({
    mutationFn: async () => {
      if (!hasUsableProfile(profile)) {
        throw new Error('A saved master profile is required before generating.');
      }
      return generateFastResume({
        profile,
        raw_jd_text: rawJD,
        target_pages: targetPages,
        save_to_database: true,
        ats_optimization_mode: atsOptimizationMode,
      });
    },
    onSuccess: (data) => {
      setResult(data);
      setGenerationId(data.generation_id);
      setRecommendation(data.resume_json);
      setAtsScore(fastResultToScore(data));
      setStep('resume-review');
      setExportStatus(null);
    },
  });

  const pdfExportMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: exportPdf,
    onSuccess: (data) => {
      downloadExport(data);
      setExportStatus('PDF downloaded');
      window.setTimeout(() => setExportStatus(null), 2000);
    },
    onError: (error) => {
      setExportStatus(error.message || 'PDF export failed.');
    },
  });

  const docxExportMutation = useMutation<ExportFileResponse, Error, string>({
    mutationFn: exportDocx,
    onSuccess: (data) => {
      downloadExport(data);
      setExportStatus('DOCX downloaded');
      window.setTimeout(() => setExportStatus(null), 2000);
    },
    onError: (error) => {
      setExportStatus(error.message || 'DOCX export failed.');
    },
  });

  const jdValid = rawJD.trim().length >= 50;
  const canGenerate = jdValid && hasUsableProfile(profile) && !generateMutation.isPending;
  const matchedKeywords = result?.matched_keywords ?? [];
  const missingKeywords = result?.missing_keywords ?? [];
  const resume = result?.resume_json ?? null;
  const generationId = result?.generation_id;

  const emptyState = useMemo(() => {
    if (profileLoading) return 'Loading your master profile...';
    if (profileError) return profileError;
    if (!rawJD.trim()) return 'Paste a job description to generate a tailored resume.';
    if (!jdValid) return `${50 - rawJD.trim().length} more characters needed.`;
    return null;
  }, [profileLoading, profileError, rawJD, jdValid]);

  return (
    <div className="animate-fade-in" style={{ display: 'grid', gap: 'var(--space-lg)' }}>
      <PageHeader
        title="Fast Resume Builder"
        subtitle="Paste a JD, generate a tailored resume, and export from one screen."
        actions={
          <button className="btn btn-secondary" onClick={() => navigate('/create-resume/advanced')}>
            Advanced Mode
          </button>
        }
      />

      <section className="card" style={{ display: 'grid', gap: 'var(--space-md)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
          <div>
            <div className="card-title">Job Description</div>
            <p className="card-subtitle">Your active master profile loads automatically.</p>
          </div>
          <ProfileStatus loading={profileLoading} profile={profile} error={profileError} onEdit={() => navigate('/profile')} />
        </div>

        <textarea
          className="form-textarea"
          value={rawJD}
          onChange={(event) => setRawJD(event.target.value)}
          placeholder="Paste the full job description here..."
          style={{ minHeight: 240, fontFamily: 'var(--font-sans)' }}
          disabled={generateMutation.isPending}
          aria-label="Job description"
        />

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 'var(--space-xs)', alignItems: 'center' }}>
            <span className="form-label" style={{ margin: 0 }}>Length</span>
            <button
              className={`btn btn-sm ${targetPages === 1 ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setTargetPages(1)}
              type="button"
            >
              1 page
            </button>
            <button
              className={`btn btn-sm ${targetPages === 2 ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setTargetPages(2)}
              type="button"
            >
              2 pages
            </button>
          </div>
          <span className="form-hint">{rawJD.length.toLocaleString()} / 15,000 characters</span>
        </div>

        {emptyState && !generateMutation.isError && (
          <div className={`warning-banner ${profileError ? 'warning-error' : 'warning-info'}`}>
            <span>{profileError ? '!' : 'i'}</span>
            <div>
              <strong>{profileError ? 'Profile needed' : 'Ready when you are'}</strong>
              <p style={{ margin: 0, marginTop: 4, fontSize: '0.85rem' }}>{emptyState}</p>
            </div>
          </div>
        )}

        {generateMutation.isError && (
          <div className="warning-banner warning-error">
            <span>!</span>
            <div>
              <strong>Generation failed</strong>
              <p style={{ margin: 0, marginTop: 4, fontSize: '0.85rem' }}>
                {generateMutation.error instanceof Error ? generateMutation.error.message : 'Unable to generate resume.'}
              </p>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
          {generateMutation.isError && (
            <button className="btn btn-secondary" onClick={() => generateMutation.mutate()} disabled={!canGenerate}>
              Retry
            </button>
          )}
          <button className="btn btn-primary btn-lg" onClick={() => generateMutation.mutate()} disabled={!canGenerate}>
            {generateMutation.isPending ? <span className="spinner" /> : null}
            {generateMutation.isPending ? 'Generating...' : 'Generate Resume'}
          </button>
        </div>
      </section>

      {generateMutation.isPending && (
        <section className="card">
          <div className="generation-status">
            <span className="spinner" />
            <div>
              <strong>Generating your fast resume...</strong>
              <p>Extracting JD keywords, composing resume JSON, and estimating ATS score.</p>
            </div>
          </div>
        </section>
      )}

      {result && resume && (
        <section style={{ display: 'grid', gap: 'var(--space-lg)' }}>
          <div className="card" style={{ display: 'grid', gap: 'var(--space-md)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-md)', flexWrap: 'wrap' }}>
              <div>
                <div className="card-title">Generated Resume</div>
                <p className="card-subtitle">Estimated ATS score and keyword match are shown below.</p>
              </div>
              <div className="score-card" style={{ minWidth: 120 }}>
                <div className={`score-value ${result.ats_score >= 85 ? 'score-high' : result.ats_score >= 70 ? 'score-mid' : 'score-low'}`}>
                  {Math.round(result.ats_score)}
                </div>
                <div className="score-label">Estimated ATS Match Score</div>
              </div>
            </div>

            <KeywordSection title="Matched Keywords" keywords={matchedKeywords} variant="found" />
            <KeywordSection title="Missing Keywords" keywords={missingKeywords} variant="missing" />

            <div className="warning-banner warning-info">
              <span>i</span>
              <div>
                <strong>Estimated score</strong>
                <p style={{ margin: 0, marginTop: 4, fontSize: '0.85rem' }}>
                  {result.score_disclaimer || 'This score is an estimate for comparison and is not guaranteed.'}
                </p>
              </div>
            </div>

            <ScoreExplanation
              explanation={result.score_explanation}
              suggestions={result.improvement_suggestions}
              breakdown={result.score_breakdown}
            />

            <div style={{ display: 'flex', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
              <button className="btn btn-secondary" onClick={() => generationId && navigate(`/review/${generationId}`)} disabled={!generationId}>
                Edit
              </button>
              <button
                className="btn btn-primary"
                onClick={() => generationId && docxExportMutation.mutate(generationId)}
                disabled={!generationId || docxExportMutation.isPending}
              >
                {docxExportMutation.isPending ? <span className="spinner" /> : null}
                Download DOCX
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => generationId && pdfExportMutation.mutate(generationId)}
                disabled={!generationId || pdfExportMutation.isPending}
              >
                {pdfExportMutation.isPending ? <span className="spinner" /> : null}
                Download PDF
              </button>
              {exportStatus && <span style={{ alignSelf: 'center', color: /fail|error|unable/i.test(exportStatus) ? 'var(--status-danger)' : 'var(--status-success)' }}>{exportStatus}</span>}
            </div>
          </div>

          <ResumePreviewLite resume={resume} />
        </section>
      )}
    </div>
  );
}

function ProfileStatus({
  loading,
  profile,
  error,
  onEdit,
}: {
  loading: boolean;
  profile: MasterProfile | null;
  error: string | null;
  onEdit: () => void;
}) {
  if (loading) return <span className="badge badge-info">Loading profile</span>;
  if (error || !hasUsableProfile(profile)) {
    return <button className="btn btn-secondary btn-sm" onClick={onEdit}>Update Profile</button>;
  }
  return <span className="badge badge-success">{profile.contact.full_name}</span>;
}

function KeywordSection({ title, keywords, variant }: { title: string; keywords: string[]; variant: 'found' | 'missing' }) {
  return (
    <div>
      <div className="form-label">{title}</div>
      {keywords.length ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {keywords.slice(0, 24).map((keyword) => (
            <span key={keyword} className={`keyword-tag keyword-${variant}`}>{keyword}</span>
          ))}
        </div>
      ) : (
        <p className="form-hint" style={{ margin: 0 }}>None</p>
      )}
    </div>
  );
}

type PreviewLiteBullet = { id?: string; text?: string };
type PreviewLiteExperience = {
  source_id?: string;
  company?: string;
  title?: string;
  start_date?: string;
  end_date?: string;
  is_current?: boolean;
  bullets?: unknown;
};
type PreviewLiteProject = {
  source_id?: string;
  name?: string;
  description?: string;
  bullets?: unknown;
};
type PreviewLiteEducation = {
  institution?: string;
  degree?: string;
  field_of_study?: string;
};

function ResumePreviewLite({ resume }: { resume: ResumeRecommendation }) {
  return (
    <section className="card" style={{ display: 'grid', gap: 'var(--space-md)' }}>
      <div>
        <h2 style={{ margin: 0, fontSize: '1.35rem' }}>{resume.contact?.full_name || 'Resume'}</h2>
        <p style={{ margin: '4px 0 0', color: 'var(--text-secondary)' }}>{resume.target_title}</p>
      </div>

      {resume.summary && (
        <PreviewSection title="Summary">
          <p style={{ margin: 0, lineHeight: 1.6 }}>{resume.summary}</p>
        </PreviewSection>
      )}

      {objectArray<{ category?: string; skills?: unknown }>(resume.skills).length > 0 && (
        <PreviewSection title="Skills">
          <div style={{ display: 'grid', gap: 8 }}>
            {objectArray<{ category?: string; skills?: unknown }>(resume.skills).map((group, index) => (
              <div key={`${group.category}-${index}`}>
                <strong>{group.category}: </strong>
                <span>{stringArray(group.skills).join(', ')}</span>
              </div>
            ))}
          </div>
        </PreviewSection>
      )}

      {objectArray<PreviewLiteExperience>(resume.experience).length > 0 && (
        <PreviewSection title="Experience">
          <div style={{ display: 'grid', gap: 'var(--space-md)' }}>
            {objectArray<PreviewLiteExperience>(resume.experience).map((entry, index) => (
              <div key={`${entry.company}-${entry.title}-${index}`}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--space-sm)', flexWrap: 'wrap' }}>
                <strong>{entry.title} - {entry.company}</strong>
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{entry.start_date} - {entry.is_current ? 'Present' : entry.end_date}</span>
                </div>
                <ul style={{ margin: '8px 0 0', paddingLeft: '1.2rem' }}>
                  {objectArray<PreviewLiteBullet>(entry.bullets).slice(0, 5).map((bullet, bulletIndex) => (
                    <li key={bullet.id || `${entry.source_id}-${bulletIndex}`}>{bullet.text}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </PreviewSection>
      )}

      {objectArray<PreviewLiteProject>(resume.projects).length > 0 && (
        <PreviewSection title="Projects">
          <div style={{ display: 'grid', gap: 'var(--space-md)' }}>
            {objectArray<PreviewLiteProject>(resume.projects).map((project, index) => (
              <div key={`${project.name}-${index}`}>
                <strong>{project.name}</strong>
                {project.description && <p style={{ margin: '4px 0', color: 'var(--text-secondary)' }}>{project.description}</p>}
                <ul style={{ margin: '8px 0 0', paddingLeft: '1.2rem' }}>
                  {objectArray<PreviewLiteBullet>(project.bullets).slice(0, 4).map((bullet, bulletIndex) => (
                    <li key={bullet.id || `${project.source_id}-${bulletIndex}`}>{bullet.text}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </PreviewSection>
      )}

      {objectArray<PreviewLiteEducation>(resume.education).length > 0 && (
        <PreviewSection title="Education">
          {objectArray<PreviewLiteEducation>(resume.education).map((entry, index) => (
            <p key={`${entry.institution}-${index}`} style={{ margin: 0 }}>
              <strong>{entry.degree}</strong>{entry.field_of_study ? `, ${entry.field_of_study}` : ''} - {entry.institution}
            </p>
          ))}
        </PreviewSection>
      )}
    </section>
  );
}

function ScoreExplanation({
  explanation,
  suggestions,
  breakdown,
}: {
  explanation: string[];
  suggestions: string[];
  breakdown: Record<string, number>;
}) {
  const rows = Object.entries(breakdown);
  if (!explanation.length && !suggestions.length && !rows.length) return null;
  return (
    <div style={{ display: 'grid', gap: 'var(--space-sm)' }}>
      {rows.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
          {rows.map(([key, value]) => (
            <div key={key} style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 10, background: 'var(--bg-glass)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{formatScoreLabel(key)}</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700 }}>{Math.round(value)}%</div>
            </div>
          ))}
        </div>
      )}
      {explanation.length > 0 && (
        <div>
          <div className="form-label">Score Explanation</div>
          <ul style={{ margin: 0, paddingLeft: '1.2rem' }}>
            {explanation.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      )}
      {suggestions.length > 0 && (
        <div>
          <div className="form-label">Improvement Suggestions</div>
          <ul style={{ margin: 0, paddingLeft: '1.2rem' }}>
            {suggestions.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function formatScoreLabel(value: string): string {
  const labels: Record<string, string> = {
    exact_jd_keywords: 'Exact JD Keywords',
    required_skills: 'Required Skills',
    title_seniority_alignment: 'Title Alignment',
    standard_sections: 'ATS Sections',
    parseability: 'Parseability',
  };
  return labels[value] ?? value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function PreviewSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 style={{ fontSize: '0.9rem', textTransform: 'uppercase', letterSpacing: 0, margin: '0 0 8px', color: 'var(--text-secondary)' }}>{title}</h3>
      {children}
    </section>
  );
}

function fastResultToScore(data: FastResumeGenerateResponse) {
  const total = data.extracted_keywords.length;
  const matched = data.matched_keywords.length;
  const coverage = total ? Math.round((matched / total) * 100) : 0;
  return {
    overall_score: data.ats_score,
    keyword_score: {
      total_keywords: total,
      matched_keywords: matched,
      coverage_percent: coverage,
      critical_missing: data.missing_keywords,
      details: data.extracted_keywords.map((keyword) => ({
        keyword,
        found: data.matched_keywords.includes(keyword),
        location: data.matched_keywords.includes(keyword) ? 'resume_json' : 'missing',
      })),
    },
    skill_score: {
      required_total: total,
      required_matched: matched,
      required_coverage_percent: coverage,
      preferred_total: 0,
      preferred_matched: 0,
      preferred_coverage_percent: 0,
    },
    readability_score: { score: 80, avg_bullet_length: 0, issues: [] },
    format_score: 80,
    section_score: {
      score: 80,
      missing_sections: [],
      has_contact: true,
      has_summary: true,
      has_experience: true,
      has_skills: true,
      has_education: true,
    },
    responsibility_score: 70,
    title_alignment_score: 70,
    missing_keywords: data.missing_keywords,
    matched_supported_keywords: data.matched_keywords,
    unsupported_jd_keywords: data.missing_keywords,
    warnings: [],
    recommendations: data.improvement_suggestions ?? [],
    score_breakdown: data.score_breakdown ?? {},
  };
}
