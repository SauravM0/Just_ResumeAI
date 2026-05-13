/**
 * Master Profile page — CRUD interface for the user's single profile.
 * Data persisted to IndexedDB. Never sent to backend except per-request.
 */

import { useEffect, useState, useCallback } from 'react';
import { getDefaultProfile, saveProfile, createBlankProfile } from '../lib/db';
import { sanitizeProfile } from '../lib/profile';
import { useAppStore } from '../store/useAppStore';
import type { MasterProfile, WorkExperience, Education, Skill, Project, Certification, Award } from '../types/profile';

type Tab = 'contact' | 'experience' | 'education' | 'skills' | 'projects' | 'credentials';

export default function MasterProfilePage() {
  const [profile, setProfile] = useState<MasterProfile | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('contact');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const { setActiveProfile } = useAppStore();

  useEffect(() => {
    getDefaultProfile().then((p) => {
      const prof = p || createBlankProfile();
      setProfile(prof);
      setActiveProfile(prof);
    });
  }, [setActiveProfile]);

  const handleSave = useCallback(async () => {
    if (!profile) return;
    const savedProfile: MasterProfile = {
      ...sanitizeProfile(profile),
      updated_at: new Date().toISOString(),
    };
    setSaving(true);
    try {
      await saveProfile(savedProfile);
      setProfile(savedProfile);
      setActiveProfile(savedProfile);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally {
      setSaving(false);
    }
  }, [profile, setActiveProfile]);

  const updateProfile = useCallback((updates: Partial<MasterProfile>) => {
    setProfile((prev) => prev ? { ...prev, ...updates } : prev);
  }, []);

  if (!profile) {
    return (
      <div className="loading-state">
        <div className="spinner spinner-lg" />
      </div>
    );
  }

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
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 className="page-title">Master Profile</h1>
          <p className="page-subtitle">Your single source of truth. All resume data comes from here.</p>
        </div>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? <span className="spinner" /> : saved ? '✓ Saved' : '💾 Save Profile'}
        </button>
      </div>

      {/* Tabs */}
      <div className="tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`tab ${activeTab === tab.key ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="animate-fade-in" key={activeTab}>
        {activeTab === 'contact' && <ContactForm profile={profile} onChange={updateProfile} />}
        {activeTab === 'experience' && <ExperienceForm profile={profile} onChange={updateProfile} />}
        {activeTab === 'education' && <EducationForm profile={profile} onChange={updateProfile} />}
        {activeTab === 'skills' && <SkillsForm profile={profile} onChange={updateProfile} />}
        {activeTab === 'projects' && <ProjectsForm profile={profile} onChange={updateProfile} />}
        {activeTab === 'credentials' && <CredentialsForm profile={profile} onChange={updateProfile} />}
      </div>
    </div>
  );
}

// ─── Contact Form ───────────────────────────────────────────────────────────

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

function ExperienceForm({ profile, onChange }: { profile: MasterProfile; onChange: (u: Partial<MasterProfile>) => void }) {
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
              <label className="form-label">Company *</label>
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
              <div key={bi} style={{ display: 'flex', gap: 'var(--space-sm)', marginBottom: 'var(--space-xs)' }}>
                <input className="form-input" value={bullet} onChange={(e) => updateBullet(i, bi, e.target.value)} placeholder="Describe an achievement..." />
                <button className="btn btn-ghost btn-sm" onClick={() => removeBullet(i, bi)}>✕</button>
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

function EducationForm({ profile, onChange }: { profile: MasterProfile; onChange: (u: Partial<MasterProfile>) => void }) {
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
              <label className="form-label">Institution *</label>
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
          <div key={i} style={{ display: 'flex', gap: 'var(--space-sm)', marginBottom: 'var(--space-sm)', alignItems: 'center' }}>
            <input className="form-input" value={skill.name} onChange={(e) => updateSkill(i, { name: e.target.value })} placeholder="Skill name" style={{ flex: 2 }} />
            <input className="form-input" value={skill.category || ''} onChange={(e) => updateSkill(i, { category: e.target.value })} placeholder="Category (e.g. Languages)" style={{ flex: 2 }} />
            <select className="form-select" value={skill.level || ''} onChange={(e) => updateSkill(i, { level: (e.target.value || undefined) as Skill['level'] })} style={{ flex: 1 }}>
              <option value="">Level</option>
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
              <option value="expert">Expert</option>
            </select>
            <button className="btn btn-ghost btn-sm" onClick={() => removeSkill(i)}>✕</button>
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
              <div key={bi} style={{ display: 'flex', gap: 'var(--space-sm)', marginBottom: 'var(--space-xs)' }}>
                <input className="form-input" value={bullet} onChange={(e) => {
                  const bullets = [...proj.bullets];
                  bullets[bi] = e.target.value;
                  updateProject(i, { bullets });
                }} placeholder="Describe a feature or achievement..." />
                <button className="btn btn-ghost btn-sm" onClick={() => updateProject(i, { bullets: proj.bullets.filter((_, j) => j !== bi) })}>✕</button>
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
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-lg)' }}>
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
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-lg)' }}>
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
