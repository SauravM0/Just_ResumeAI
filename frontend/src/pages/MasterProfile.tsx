import { useEffect, useState, useCallback } from 'react';
import {
  activateSourceResume,
  getProfileEmbeddingStatus,
  getMyProfile,
  listSourceResumes,
  saveMyProfile,
  uploadSourceResume,
} from '../lib/profileApi';
import { createBlankProfile, sanitizeProfile } from '../lib/profile';
import { useAppStore } from '../store/useAppStore';
import PageHeader from '../components/ui/PageHeader';
import PrimaryActionBar from '../components/ui/PrimaryActionBar';
import LoadingState from '../components/ui/LoadingState';
import ProfileConfirmationModal from '../components/ui/ProfileConfirmationModal';
import type { ExtractionConfidenceReport, LockedFields, MasterProfile, WorkExperience, Education, Skill, Project, Certification, Award } from '../types/profile';
import type { SourceResumeSummary } from '../lib/profileApi';

type Tab = 'contact' | 'experience' | 'education' | 'skills' | 'projects' | 'credentials';

export default function MasterProfilePage() {
  const [profile, setProfile] = useState<MasterProfile | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('contact');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sourceResumes, setSourceResumes] = useState<SourceResumeSummary[]>([]);
  const [activeSourceResumeId, setActiveSourceResumeId] = useState<string | null>(null);
  const [importPreview, setImportPreview] = useState<MasterProfile | null>(null);
  const [confidenceReport, setConfidenceReport] = useState<ExtractionConfidenceReport | null>(null);
  const [showConfirmationModal, setShowConfirmationModal] = useState(false);
  const [lockedFields, setLockedFields] = useState<LockedFields>({});
  const [sourceWarnings, setSourceWarnings] = useState<string[]>([]);
  const [uploadingSource, setUploadingSource] = useState(false);
  const [embeddingStatus, setEmbeddingStatus] = useState<'idle' | 'analysing' | 'complete' | 'failed'>('idle');
  const { setActiveProfile } = useAppStore();

  useEffect(() => {
    let cancelled = false;
    async function loadProfile() {
      setLoading(true);
      setError(null);
      try {
        const response = await getMyProfile();
        const prof = response.profile_json || createBlankProfile();
        if (cancelled) return;
        setProfile(prof);
        setActiveProfile(prof);
      } catch (loadError) {
        if (cancelled) return;
        setProfile(createBlankProfile());
        setActiveProfile(null);
        setError(loadError instanceof Error ? loadError.message : 'Unable to load profile.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadProfile();
    return () => { cancelled = true; };
  }, [setActiveProfile]);

  useEffect(() => {
    let cancelled = false;
    async function loadSourceResumes() {
      try {
        const response = await listSourceResumes();
        if (cancelled) return;
        setSourceResumes(response.resumes);
        setActiveSourceResumeId(response.active_source_resume_id || null);
      } catch {
        if (!cancelled) setSourceResumes([]);
      }
    }
    void loadSourceResumes();
    return () => { cancelled = true; };
  }, []);

  const handleSave = useCallback(async () => {
    if (!profile) return;
    if (!profile.contact.full_name.trim() || !profile.contact.email.trim()) {
      setError('Full name and email are required before saving.');
      return;
    }
    const savedProfile: MasterProfile = {
      ...sanitizeProfile(profile),
      updated_at: new Date().toISOString(),
    };
    setSaving(true);
    setError(null);
    try {
      const response = await saveMyProfile(savedProfile);
      const persistedProfile = response.profile_json || savedProfile;
      setProfile(persistedProfile);
      setActiveProfile(persistedProfile);
      setEmbeddingStatus('analysing');
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Unable to save profile.');
    } finally {
      setSaving(false);
    }
  }, [profile, setActiveProfile]);

  const updateProfile = useCallback((updates: Partial<MasterProfile>) => {
    setProfile((prev) => prev ? { ...prev, ...updates } : prev);
  }, []);

  const handleSourceUpload = useCallback(async (file?: File) => {
    if (!file) return;
    setUploadingSource(true);
    setError(null);
    setSourceWarnings([]);
    try {
      const response = await uploadSourceResume(file);
      setImportPreview(response.extracted_profile);
      setConfidenceReport(response.confidence || null);
      setLockedFields(response.locked_fields || {});
      setSourceWarnings(response.warnings);
      if (response.confidence?.has_low_confidence_fields) {
        setShowConfirmationModal(true);
      } else {
        // All high confidence — directly populate the form
        const imported = sanitizeProfile(response.extracted_profile);
        if (profile) {
          setProfile({
            ...imported,
            id: profile.id,
            created_at: profile.created_at,
            updated_at: profile.updated_at,
          });
        }
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      }
      const sourceList = await listSourceResumes();
      setSourceResumes(sourceList.resumes);
      setActiveSourceResumeId(sourceList.active_source_resume_id || response.source_resume.id);
    } catch (uploadError) {
      setError(uploadError instanceof Error ? uploadError.message : 'Unable to import source resume.');
    } finally {
      setUploadingSource(false);
    }
  }, [profile]);

  const handleApplyImport = useCallback(() => {
    if (!profile || !importPreview) return;
    const imported = sanitizeProfile(importPreview);
    setProfile({
      ...imported,
      id: profile.id,
      created_at: profile.created_at,
      updated_at: profile.updated_at,
    });
    setSaved(false);
  }, [importPreview, profile]);

  const handleConfirmationComplete = useCallback((correctedProfile: MasterProfile) => {
    setShowConfirmationModal(false);
    const imported = sanitizeProfile(correctedProfile);
    setImportPreview(imported);
    if (!profile) return;
    setProfile({
      ...imported,
      id: profile.id,
      created_at: profile.created_at,
      updated_at: profile.updated_at,
    });
    setSaved(false);
  }, [profile]);

  const handleActivateSource = useCallback(async (sourceResumeId: string) => {
    try {
      const response = await activateSourceResume(sourceResumeId);
      setSourceResumes(response.resumes);
      setActiveSourceResumeId(response.active_source_resume_id || null);
    } catch (activateError) {
      setError(activateError instanceof Error ? activateError.message : 'Unable to activate source resume.');
    }
  }, []);

  useEffect(() => {
    if (embeddingStatus !== 'analysing') return;
    let cancelled = false;
    let attempts = 0;
    const poll = window.setInterval(() => {
      attempts += 1;
      void getProfileEmbeddingStatus()
        .then((status) => {
          if (cancelled) return;
          const normalized = String(status.status || '').toLowerCase();
          if (normalized === 'complete' || (status.count || 0) > 0) {
            setEmbeddingStatus('complete');
            window.clearInterval(poll);
          } else if (normalized === 'failed') {
            setEmbeddingStatus('failed');
            window.clearInterval(poll);
          } else if (attempts >= 10) {
            setEmbeddingStatus('complete');
            window.clearInterval(poll);
          }
        })
        .catch(() => {
          if (attempts >= 4) {
            setEmbeddingStatus('failed');
            window.clearInterval(poll);
          }
        });
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [embeddingStatus]);

  if (loading || !profile) {
    return <LoadingState text="Loading your master profile..." />;
  }

  const profileQuality = calculateProfileQuality(profile);
  const tabs: { key: Tab; label: string; icon: string }[] = [
    { key: 'contact', label: 'Contact', icon: '👤' },
    { key: 'experience', label: 'Experience', icon: '💼' },
    { key: 'education', label: 'Education', icon: '🎓' },
    { key: 'skills', label: 'Skills', icon: '⚡' },
    { key: 'projects', label: 'Projects', icon: '🚀' },
    { key: 'credentials', label: 'Certs & Awards', icon: '🏆' },
  ];

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Master Profile"
        subtitle="Your source of truth — all resume data comes from here."
        badge={<span className="badge badge-info">{profileQuality.score}% complete</span>}
      />

      <ProfileQualityIndicator
        score={profileQuality.score}
        missingSection={profileQuality.missingSection}
        embeddingStatus={embeddingStatus}
      />

      {error && (
        <div className="warning-banner warning-error" style={{ marginBottom: 'var(--space-md)' }}>
          <span>{error}</span>
        </div>
      )}

      {(!profile.contact.full_name.trim() || !profile.contact.email.trim()) && (
        <div className="warning-banner warning-warn" style={{ marginBottom: 'var(--space-md)' }}>
          <span>Full name and email are required before saving.</span>
        </div>
      )}

      <SourceResumePanel
        sourceResumes={sourceResumes}
        activeSourceResumeId={activeSourceResumeId}
        importPreview={importPreview}
        warnings={sourceWarnings}
        uploading={uploadingSource}
        onUpload={handleSourceUpload}
        onApply={handleApplyImport}
        onActivate={handleActivateSource}
      />

      {importPreview && confidenceReport && (
        <ProfileConfirmationModal
          isOpen={showConfirmationModal}
          confidenceReport={confidenceReport}
          profile={importPreview}
          onConfirm={handleConfirmationComplete}
          onSkip={() => setShowConfirmationModal(false)}
        />
      )}

      <div className="tabs profile-tabs" style={{ marginBottom: 'var(--space-lg)' }}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            <span className="profile-tab-mark" aria-hidden="true">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      <div className="animate-fade-in" key={activeTab}>
        {activeTab === 'contact' && <ContactForm profile={profile} onChange={updateProfile} />}
        {activeTab === 'experience' && <ExperienceForm profile={profile} lockedFields={lockedFields} onChange={updateProfile} />}
        {activeTab === 'education' && <EducationForm profile={profile} lockedFields={lockedFields} onChange={updateProfile} />}
        {activeTab === 'skills' && <SkillsForm profile={profile} onChange={updateProfile} />}
        {activeTab === 'projects' && <ProjectsForm profile={profile} onChange={updateProfile} />}
        {activeTab === 'credentials' && <CredentialsForm profile={profile} onChange={updateProfile} />}
      </div>

      <PrimaryActionBar>
        <div style={{ display: 'flex', gap: 'var(--space-sm)', width: '100%', justifyContent: 'flex-end' }}>
          {saved && <span style={{ color: 'var(--text-success)', fontSize: '0.85rem', alignSelf: 'center' }}>✓ Saved</span>}
          <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? <><span className="spinner" /> Saving...</> : 'Save Profile'}
          </button>
        </div>
      </PrimaryActionBar>
    </div>
  );
}

function SourceResumePanel({
  sourceResumes,
  activeSourceResumeId,
  importPreview,
  warnings,
  uploading,
  onUpload,
  onApply,
  onActivate,
}: {
  sourceResumes: SourceResumeSummary[];
  activeSourceResumeId: string | null;
  importPreview: MasterProfile | null;
  warnings: string[];
  uploading: boolean;
  onUpload: (file?: File) => void;
  onApply: () => void;
  onActivate: (sourceResumeId: string) => void;
}) {
  const active = sourceResumes.find((resume) => resume.id === activeSourceResumeId);

  return (
    <section className="card" style={{ marginBottom: 'var(--space-lg)' }}>
      <div className="profile-card-header">
        <div>
          <div className="card-title">Source Resume</div>
          <div className="card-subtitle">{active ? active.display_name : 'No active uploaded resume'}</div>
        </div>
        <label className={`btn btn-secondary btn-sm ${uploading ? 'disabled' : ''}`}>
          {uploading ? 'Extracting...' : 'Upload PDF, DOCX, or TXT'}
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            hidden
            disabled={uploading}
            onChange={(event) => {
              onUpload(event.target.files?.[0]);
              event.currentTarget.value = '';
            }}
          />
        </label>
      </div>

      {sourceResumes.length > 0 && (
        <div style={{ display: 'grid', gap: 'var(--space-sm)', marginTop: 'var(--space-md)' }}>
          {sourceResumes.map((resume) => (
            <div key={resume.id} className="profile-inline-row">
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600 }}>{resume.display_name}</div>
                <div className="card-subtitle">{resume.file_type.toUpperCase()} uploaded source</div>
              </div>
              {resume.id === activeSourceResumeId ? (
                <span className="badge badge-info">Active</span>
              ) : (
                <button className="btn btn-ghost btn-sm" onClick={() => onActivate(resume.id)}>Set Active</button>
              )}
            </div>
          ))}
        </div>
      )}

      {importPreview && (
        <div style={{ borderTop: '1px solid var(--border-primary)', marginTop: 'var(--space-md)', paddingTop: 'var(--space-md)' }}>
          <div className="profile-card-header">
            <div>
              <div className="card-title">Extracted Profile Preview</div>
              <div className="card-subtitle">
                {importPreview.contact.full_name || 'Unnamed candidate'} | {importPreview.work_experience.length} roles | {importPreview.skills.length} skills
              </div>
            </div>
            <button className="btn btn-primary btn-sm" onClick={onApply}>Use In Profile Editor</button>
          </div>
          {warnings.map((warning) => (
            <div key={warning} className="warning-banner warning-warn" style={{ marginTop: 'var(--space-sm)' }}>
              <span>{warning}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

// ─── Contact Form ───────────────────────────────────────────────────────────

function ProfileQualityIndicator({
  score,
  missingSection,
  embeddingStatus,
}: {
  score: number;
  missingSection: string;
  embeddingStatus: 'idle' | 'analysing' | 'complete' | 'failed';
}) {
  return (
    <section className="profile-quality-card">
      <div
        className="profile-quality-ring"
        style={{ background: `conic-gradient(var(--status-success) ${score * 3.6}deg, var(--bg-glass-strong) 0deg)` }}
        aria-label={`Profile completeness ${score}%`}
      >
        <span>{score}%</span>
      </div>
      <div className="profile-quality-copy">
        <strong>Your profile is {score}% complete</strong>
        <p>Add {missingSection} to improve your ATS match rate.</p>
      </div>
      {embeddingStatus === 'analysing' && <span className="badge badge-info"><span className="spinner" /> Analysing your profile...</span>}
      {embeddingStatus === 'complete' && <span className="badge badge-success">Profile analysis complete</span>}
      {embeddingStatus === 'failed' && <span className="badge badge-warning">Profile analysis pending</span>}
    </section>
  );
}

function calculateProfileQuality(profile: MasterProfile): { score: number; missingSection: string } {
  const sections = [
    { label: 'contact info', weight: 20, done: Boolean(profile.contact.email?.trim() && (profile.contact.phone?.trim() || profile.contact.linkedin_url?.trim())) },
    { label: 'work experience', weight: 25, done: profile.work_experience.some((exp) => exp.company.trim() && exp.bullets.filter(Boolean).length >= 2) },
    { label: 'projects with technologies', weight: 20, done: profile.projects.filter((project) => project.name.trim() && project.technologies.length > 0).length >= 2 },
    { label: 'at least 5 skills', weight: 15, done: profile.skills.filter((skill) => skill.name.trim()).length >= 5 },
    { label: 'education with GPA', weight: 10, done: profile.education.some((edu) => edu.institution.trim() && edu.gpa?.trim()) },
    { label: 'an achievement or certification', weight: 10, done: profile.awards.some((award) => award.title.trim()) || profile.certifications.some((cert) => cert.name.trim()) },
  ];
  const score = sections.reduce((total, section) => total + (section.done ? section.weight : 0), 0);
  return { score, missingSection: sections.find((section) => !section.done)?.label || 'fresh evidence as you grow' };
}

function isLockedField(lockedFields: LockedFields, path: string): boolean {
  return Boolean(lockedFields[path] || lockedFields[path.replace(/\.(\d+)\./g, '[$1].')]);
}

function ContactForm({ profile, onChange }: { profile: MasterProfile; onChange: (u: Partial<MasterProfile>) => void }) {
  const c = profile.contact;
  const update = (field: string, value: string) => {
    onChange({ contact: { ...c, [field]: value } });
  };

  return (
    <div className="card">
      <div className="card-title" style={{ marginBottom: 'var(--space-lg)' }}>Contact Information</div>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Full Name *</label>
          <input className="form-input" value={c.full_name} onChange={(e) => update('full_name', e.target.value)} placeholder="John Doe" />
        </div>
        <div className="form-group">
          <label className="form-label">Email *</label>
          <input className="form-input" type="email" value={c.email} onChange={(e) => update('email', e.target.value)} placeholder="john@example.com" />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Phone</label>
          <input className="form-input" value={c.phone || ''} onChange={(e) => update('phone', e.target.value)} placeholder="+1 (555) 123-4567" />
        </div>
        <div className="form-group">
          <label className="form-label">Location</label>
          <input className="form-input" value={c.location || ''} onChange={(e) => update('location', e.target.value)} placeholder="San Francisco, CA" />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">LinkedIn URL</label>
          <input className="form-input" value={c.linkedin_url || ''} onChange={(e) => update('linkedin_url', e.target.value)} placeholder="https://linkedin.com/in/johndoe" />
        </div>
        <div className="form-group">
          <label className="form-label">GitHub URL</label>
          <input className="form-input" value={c.github_url || ''} onChange={(e) => update('github_url', e.target.value)} placeholder="https://github.com/johndoe" />
        </div>
      </div>
      <div className="form-group">
        <label className="form-label">Professional Summary</label>
        <textarea className="form-textarea" value={profile.summary || ''} onChange={(e) => onChange({ summary: e.target.value })} placeholder="Brief professional summary..." rows={4} />
        <span className="form-hint">Optional. AI can generate a tailored summary from your experience.</span>
      </div>
    </div>
  );
}

// ─── Experience Form ────────────────────────────────────────────────────────

function ExperienceForm({
  profile,
  lockedFields,
  onChange,
}: {
  profile: MasterProfile;
  lockedFields: LockedFields;
  onChange: (u: Partial<MasterProfile>) => void;
}) {
  const experiences = profile.work_experience;

  const addExp = () => {
    onChange({
      work_experience: [
        ...experiences,
        {
          id: crypto.randomUUID(),
          company: '',
          title: '',
          location: '',
          start_date: '',
          end_date: '',
          is_current: false,
          description: '',
          bullets: [''],
          tags: [],
        },
      ],
    });
  };

  const updateExp = (index: number, updates: Partial<WorkExperience>) => {
    const updated = [...experiences];
    updated[index] = { ...updated[index], ...updates };
    onChange({ work_experience: updated });
  };

  const removeExp = (index: number) => {
    onChange({ work_experience: experiences.filter((_, i) => i !== index) });
  };

  const addBullet = (expIndex: number) => {
    const exp = experiences[expIndex];
    updateExp(expIndex, { bullets: [...exp.bullets, ''] });
  };

  const updateBullet = (expIndex: number, bulletIndex: number, text: string) => {
    const exp = experiences[expIndex];
    const bullets = [...exp.bullets];
    bullets[bulletIndex] = text;
    updateExp(expIndex, { bullets });
  };

  const removeBullet = (expIndex: number, bulletIndex: number) => {
    const exp = experiences[expIndex];
    updateExp(expIndex, { bullets: exp.bullets.filter((_, i) => i !== bulletIndex) });
  };

  return (
    <div>
      {experiences.map((exp, i) => (
        <div key={exp.id} className="card" style={{ marginBottom: 'var(--space-md)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-md)' }}>
            <div className="card-title">Experience #{i + 1}</div>
            <button className="btn btn-danger btn-sm" onClick={() => removeExp(i)}>Remove</button>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Job Title *</label>
              <input className="form-input" value={exp.title} onChange={(e) => updateExp(i, { title: e.target.value })} placeholder="Software Engineer" />
            </div>
            <div className="form-group">
              <label className="form-label">
                Company *
                {isLockedField(lockedFields, `work_experience.${i}.company`) && (
                  <span className="locked-edit-hint" title="This will update the locked value - make sure this is accurate">Verified</span>
                )}
              </label>
              <input className="form-input" value={exp.company} onChange={(e) => updateExp(i, { company: e.target.value })} placeholder="Google" />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Start Date</label>
              <input className="form-input" type="month" value={exp.start_date} onChange={(e) => updateExp(i, { start_date: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label">End Date</label>
              <input className="form-input" type="month" value={exp.end_date || ''} onChange={(e) => updateExp(i, { end_date: e.target.value })} disabled={exp.is_current} />
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '4px', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                <input type="checkbox" checked={exp.is_current} onChange={(e) => updateExp(i, { is_current: e.target.checked, end_date: e.target.checked ? undefined : exp.end_date })} />
                Currently working here
              </label>
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">Location</label>
            <input className="form-input" value={exp.location || ''} onChange={(e) => updateExp(i, { location: e.target.value })} placeholder="Mountain View, CA" />
          </div>
          <div className="form-group">
            <label className="form-label">Bullet Points</label>
            {exp.bullets.map((bullet, bi) => (
              <div key={bi} className="profile-inline-row">
                <input className="form-input" value={bullet} onChange={(e) => updateBullet(i, bi, e.target.value)} placeholder="Describe an achievement..." />
                <button className="btn btn-ghost btn-sm" onClick={() => removeBullet(i, bi)} aria-label="Remove bullet">Remove</button>
              </div>
            ))}
            <button className="btn btn-ghost btn-sm" onClick={() => addBullet(i)}>+ Add Bullet</button>
          </div>
        </div>
      ))}
      <button className="btn btn-secondary" onClick={addExp}>+ Add Experience</button>
    </div>
  );
}

// ─── Education Form ─────────────────────────────────────────────────────────

function EducationForm({
  profile,
  lockedFields,
  onChange,
}: {
  profile: MasterProfile;
  lockedFields: LockedFields;
  onChange: (u: Partial<MasterProfile>) => void;
}) {
  const eduList = profile.education;

  const addEdu = () => {
    onChange({
      education: [
        ...eduList,
        {
          id: crypto.randomUUID(),
          institution: '',
          degree: '',
          degree_type: 'bachelor' as const,
          field_of_study: '',
          start_date: '',
          end_date: '',
          gpa: '',
          honors: '',
          relevant_coursework: [],
        },
      ],
    });
  };

  const updateEdu = (index: number, updates: Partial<Education>) => {
    const updated = [...eduList];
    updated[index] = { ...updated[index], ...updates };
    onChange({ education: updated });
  };

  const removeEdu = (index: number) => {
    onChange({ education: eduList.filter((_, i) => i !== index) });
  };

  return (
    <div>
      {eduList.map((edu, i) => (
        <div key={edu.id} className="card" style={{ marginBottom: 'var(--space-md)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-md)' }}>
            <div className="card-title">Education #{i + 1}</div>
            <button className="btn btn-danger btn-sm" onClick={() => removeEdu(i)}>Remove</button>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">
                Institution *
                {isLockedField(lockedFields, `education.${i}.institution`) && (
                  <span className="locked-edit-hint" title="This will update the locked value - make sure this is accurate">Verified</span>
                )}
              </label>
              <input className="form-input" value={edu.institution} onChange={(e) => updateEdu(i, { institution: e.target.value })} placeholder="Stanford University" />
            </div>
            <div className="form-group">
              <label className="form-label">Degree *</label>
              <input className="form-input" value={edu.degree} onChange={(e) => updateEdu(i, { degree: e.target.value })} placeholder="Bachelor of Science" />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Field of Study</label>
              <input className="form-input" value={edu.field_of_study || ''} onChange={(e) => updateEdu(i, { field_of_study: e.target.value })} placeholder="Computer Science" />
            </div>
            <div className="form-group">
              <label className="form-label">GPA</label>
              <input className="form-input" value={edu.gpa || ''} onChange={(e) => updateEdu(i, { gpa: e.target.value })} placeholder="3.8/4.0" />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Start Date</label>
              <input className="form-input" type="month" value={edu.start_date || ''} onChange={(e) => updateEdu(i, { start_date: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label">End Date</label>
              <input className="form-input" type="month" value={edu.end_date || ''} onChange={(e) => updateEdu(i, { end_date: e.target.value })} />
            </div>
          </div>
        </div>
      ))}
      <button className="btn btn-secondary" onClick={addEdu}>+ Add Education</button>
    </div>
  );
}

// ─── Skills Form ────────────────────────────────────────────────────────────

function SkillsForm({ profile, onChange }: { profile: MasterProfile; onChange: (u: Partial<MasterProfile>) => void }) {
  const skills = profile.skills;

  const addSkill = () => {
    onChange({ skills: [...skills, { name: '', category: '', level: undefined }] });
  };

  const updateSkill = (index: number, updates: Partial<Skill>) => {
    const updated = [...skills];
    updated[index] = { ...updated[index], ...updates };
    onChange({ skills: updated });
  };

  const removeSkill = (index: number) => {
    onChange({ skills: skills.filter((_, i) => i !== index) });
  };

  const categoryOptions = [
    'Programming Languages',
    'Frontend Frameworks',
    'Backend Frameworks',
    'Databases',
    'Cloud & DevOps',
    'Tools',
    'Domain Platforms',
    'AI & ML',
    'Soft Skills',
    'Learning Focus',
  ];

  // Group by category for display
  const categories = [...new Set(skills.map((s) => s.category || 'Uncategorized'))];

  return (
    <div>
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-lg)' }}>
          <div>
            <div className="card-title">Skills & Technologies</div>
            <div className="card-subtitle">{skills.length} skills added</div>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={addSkill}>+ Add Skill</button>
        </div>

        {skills.map((skill, i) => (
          <div key={i} className="profile-skill-row">
            <input
              aria-label={`Skill ${i + 1} name`}
              className="form-input"
              value={skill.name}
              onChange={(e) => updateSkill(i, { name: e.target.value })}
              placeholder="Skill name"
            />
            <select
              aria-label={`Skill ${i + 1} category`}
              className="form-select"
              value={skill.category || ''}
              onChange={(e) => updateSkill(i, { category: e.target.value })}
            >
              <option value="">Choose category</option>
              {categoryOptions.map((category) => <option key={category} value={category}>{category}</option>)}
            </select>
            <select
              aria-label={`Skill ${i + 1} level`}
              className="form-select"
              value={skill.level || ''}
              onChange={(e) => updateSkill(i, { level: (e.target.value || undefined) as Skill['level'] })}
            >
              <option value="">Level</option>
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
              <option value="expert">Expert</option>
            </select>
            <button className="btn btn-ghost btn-sm" onClick={() => removeSkill(i)} aria-label={`Remove skill ${i + 1}`}>Remove</button>
          </div>
        ))}

        {skills.length === 0 && (
          <div className="empty-state" style={{ padding: 'var(--space-xl)' }}>
            <div className="empty-icon">⚡</div>
            <div className="empty-title">No skills yet</div>
            <div className="empty-description">Add your technical skills, tools, and technologies.</div>
          </div>
        )}
      </div>

      {/* Quick view by category */}
      {categories.length > 0 && skills.length > 0 && (
        <div className="card" style={{ marginTop: 'var(--space-md)' }}>
          <div className="card-title" style={{ marginBottom: 'var(--space-md)' }}>Preview by Category</div>
          {categories.map((cat) => (
            <div key={cat} style={{ marginBottom: 'var(--space-sm)' }}>
              <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{cat}: </span>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                {skills.filter((s) => (s.category || 'Uncategorized') === cat).map((s) => s.name).filter(Boolean).join(', ')}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Projects Form ──────────────────────────────────────────────────────────

function ProjectsForm({ profile, onChange }: { profile: MasterProfile; onChange: (u: Partial<MasterProfile>) => void }) {
  const projects = profile.projects;

  const addProject = () => {
    onChange({
      projects: [
        ...projects,
        {
          id: crypto.randomUUID(),
          name: '',
          description: '',
          url: '',
          technologies: [],
          bullets: [''],
          start_date: '',
          end_date: '',
        },
      ],
    });
  };

  const updateProject = (index: number, updates: Partial<Project>) => {
    const updated = [...projects];
    updated[index] = { ...updated[index], ...updates };
    onChange({ projects: updated });
  };

  const removeProject = (index: number) => {
    onChange({ projects: projects.filter((_, i) => i !== index) });
  };

  return (
    <div>
      {projects.map((proj, i) => (
        <div key={proj.id} className="card" style={{ marginBottom: 'var(--space-md)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-md)' }}>
            <div className="card-title">Project #{i + 1}</div>
            <button className="btn btn-danger btn-sm" onClick={() => removeProject(i)}>Remove</button>
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Project Name *</label>
              <input className="form-input" value={proj.name} onChange={(e) => updateProject(i, { name: e.target.value })} placeholder="E-commerce Platform" />
            </div>
            <div className="form-group">
              <label className="form-label">URL</label>
              <input className="form-input" value={proj.url || ''} onChange={(e) => updateProject(i, { url: e.target.value })} placeholder="https://github.com/..." />
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">Description</label>
            <textarea className="form-textarea" value={proj.description || ''} onChange={(e) => updateProject(i, { description: e.target.value })} placeholder="What does this project do?" rows={2} />
          </div>
          <div className="form-group">
            <label className="form-label">Technologies (comma-separated)</label>
            <input className="form-input" value={proj.technologies.join(', ')} onChange={(e) => updateProject(i, { technologies: e.target.value.split(',').map((t) => t.trim()).filter(Boolean) })} placeholder="React, Node.js, PostgreSQL" />
          </div>
          <div className="form-group">
            <label className="form-label">Key Points</label>
            {proj.bullets.map((bullet, bi) => (
              <div key={bi} className="profile-inline-row">
                <input className="form-input" value={bullet} onChange={(e) => {
                  const bullets = [...proj.bullets];
                  bullets[bi] = e.target.value;
                  updateProject(i, { bullets });
                }} placeholder="Describe a feature or achievement..." />
                <button className="btn btn-ghost btn-sm" onClick={() => updateProject(i, { bullets: proj.bullets.filter((_, j) => j !== bi) })} aria-label="Remove project point">Remove</button>
              </div>
            ))}
            <button className="btn btn-ghost btn-sm" onClick={() => updateProject(i, { bullets: [...proj.bullets, ''] })}>+ Add Point</button>
          </div>
        </div>
      ))}
      <button className="btn btn-secondary" onClick={addProject}>+ Add Project</button>
    </div>
  );
}

function CredentialsForm({ profile, onChange }: { profile: MasterProfile; onChange: (u: Partial<MasterProfile>) => void }) {
  const certifications = profile.certifications;
  const awards = profile.awards;

  const addCertification = () => {
    onChange({
      certifications: [
        ...certifications,
        { id: crypto.randomUUID(), name: '', issuing_org: '', issue_date: '', expiry_date: '', credential_id: '', url: '' },
      ],
    });
  };

  const updateCertification = (index: number, updates: Partial<Certification>) => {
    const updated = [...certifications];
    updated[index] = { ...updated[index], ...updates };
    onChange({ certifications: updated });
  };

  const removeCertification = (index: number) => {
    onChange({ certifications: certifications.filter((_, i) => i !== index) });
  };

  const addAward = () => {
    onChange({
      awards: [
        ...awards,
        { id: crypto.randomUUID(), title: '', issuer: '', date: '', description: '' },
      ],
    });
  };

  const updateAward = (index: number, updates: Partial<Award>) => {
    const updated = [...awards];
    updated[index] = { ...updated[index], ...updates };
    onChange({ awards: updated });
  };

  const removeAward = (index: number) => {
    onChange({ awards: awards.filter((_, i) => i !== index) });
  };

  return (
    <div>
      <div className="card" style={{ marginBottom: 'var(--space-md)' }}>
        <div className="profile-card-header">
          <div>
            <div className="card-title">Certifications</div>
            <div className="card-subtitle">Licenses, cloud badges, platform certificates, and course certificates.</div>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={addCertification}>+ Add Certification</button>
        </div>

        {certifications.map((cert, i) => (
          <div key={cert.id} className="card" style={{ marginBottom: 'var(--space-sm)', padding: 'var(--space-md)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-md)' }}>
              <div className="card-title">Certification #{i + 1}</div>
              <button className="btn btn-danger btn-sm" onClick={() => removeCertification(i)}>Remove</button>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Certification Name *</label>
                <input className="form-input" value={cert.name} onChange={(e) => updateCertification(i, { name: e.target.value })} placeholder="AWS Certified Cloud Practitioner" />
              </div>
              <div className="form-group">
                <label className="form-label">Issuer</label>
                <input className="form-input" value={cert.issuing_org || ''} onChange={(e) => updateCertification(i, { issuing_org: e.target.value })} placeholder="Amazon Web Services" />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Issue Date</label>
                <input className="form-input" type="month" value={cert.issue_date || ''} onChange={(e) => updateCertification(i, { issue_date: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">Credential ID</label>
                <input className="form-input" value={cert.credential_id || ''} onChange={(e) => updateCertification(i, { credential_id: e.target.value })} placeholder="Optional credential ID" />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Credential URL</label>
              <input className="form-input" value={cert.url || ''} onChange={(e) => updateCertification(i, { url: e.target.value })} placeholder="https://..." />
            </div>
          </div>
        ))}

        {certifications.length === 0 && (
          <div className="empty-state" style={{ padding: 'var(--space-lg)' }}>
            <div className="empty-title">No certifications yet</div>
          </div>
        )}
      </div>

      <div className="card">
        <div className="profile-card-header">
          <div>
            <div className="card-title">Achievements & Awards</div>
            <div className="card-subtitle">Hackathons, recognitions, scholarships, honors, and competition results.</div>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={addAward}>+ Add Achievement</button>
        </div>

        {awards.map((award, i) => (
          <div key={award.id} className="card" style={{ marginBottom: 'var(--space-sm)', padding: 'var(--space-md)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-md)' }}>
              <div className="card-title">Achievement #{i + 1}</div>
              <button className="btn btn-danger btn-sm" onClick={() => removeAward(i)}>Remove</button>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">Title *</label>
                <input className="form-input" value={award.title} onChange={(e) => updateAward(i, { title: e.target.value })} placeholder="3rd Prize Hackathon" />
              </div>
              <div className="form-group">
                <label className="form-label">Issuer / Organization</label>
                <input className="form-input" value={award.issuer || ''} onChange={(e) => updateAward(i, { issuer: e.target.value })} placeholder="College Innovation Cell" />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Date</label>
              <input className="form-input" type="month" value={award.date || ''} onChange={(e) => updateAward(i, { date: e.target.value })} />
            </div>
            <div className="form-group">
              <label className="form-label">Description</label>
              <textarea className="form-textarea" value={award.description || ''} onChange={(e) => updateAward(i, { description: e.target.value })} placeholder="Short evidence, result, or metric..." rows={2} />
            </div>
          </div>
        ))}

        {awards.length === 0 && (
          <div className="empty-state" style={{ padding: 'var(--space-lg)' }}>
            <div className="empty-title">No achievements yet</div>
          </div>
        )}
      </div>
    </div>
  );
}
