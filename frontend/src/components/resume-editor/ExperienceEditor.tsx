/**
 * Experience Editor component
 */

import { useState } from 'react';
import type { ResumeExperienceEntry, ResumeBullet } from '../../types/resume';

interface ExperienceEditorProps {
  experience: ResumeExperienceEntry[];
  onChange: (experience: ResumeExperienceEntry[]) => void;
}

function BulletEditor({
  bullet,
  onChange,
  onDelete,
}: {
  bullet: ResumeBullet;
  onChange: (text: string) => void;
  onDelete: () => void;
}) {
  return (
    <div className="bullet-editor">
      <span className="bullet-marker">•</span>
      <textarea
        className="textarea textarea-sm"
        value={bullet.text}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
      />
      <button className="btn btn-ghost btn-icon-sm" onClick={onDelete}>
        ×
      </button>
    </div>
  );
}

function EntryEditor({
  entry,
  onChange,
}: {
  entry: ResumeExperienceEntry;
  onChange: (entry: ResumeExperienceEntry) => void;
}) {
  const handleFieldChange = (field: keyof ResumeExperienceEntry, value: string) => {
    onChange({ ...entry, [field]: value });
  };

  const handleBulletChange = (bulletIndex: number, text: string) => {
    const bullets = [...entry.bullets];
    bullets[bulletIndex] = { ...bullets[bulletIndex], text, status: 'edited' };
    onChange({ ...entry, bullets });
  };

  const handleDeleteBullet = (bulletIndex: number) => {
    const bullets = entry.bullets.filter((_, i) => i !== bulletIndex);
    onChange({ ...entry, bullets });
  };

  const handleAddBullet = () => {
    const newBullet: ResumeBullet = {
      id: `bullet-${Date.now()}`,
      text: '',
      status: 'edited',
      relevance_score: 0,
      matched_keywords: [],
    };
    onChange({ ...entry, bullets: [...entry.bullets, newBullet] });
  };

  return (
    <div className="entry-editor">
      <div className="entry-header">
        <input
          type="text"
          className="input"
          value={entry.title}
          onChange={(e) => handleFieldChange('title', e.target.value)}
          placeholder="Job Title"
        />
      </div>
      <div className="entry-subheader">
        <input
          type="text"
          className="input input-sm"
          value={entry.company}
          onChange={(e) => handleFieldChange('company', e.target.value)}
          placeholder="Company"
        />
        <div className="entry-dates">
          <input
            type="text"
            className="input input-sm"
            value={entry.start_date}
            onChange={(e) => handleFieldChange('start_date', e.target.value)}
            placeholder="Start"
          />
          <span>-</span>
          <input
            type="text"
            className="input input-sm"
            value={entry.end_date || ''}
            onChange={(e) => handleFieldChange('end_date', e.target.value)}
            placeholder="End"
          />
        </div>
      </div>
      <div className="entry-bullets">
        <label className="form-label">Achievements</label>
        {entry.bullets
          .filter(b => b.status !== 'rejected')
          .map((bullet, _idx) => (
            <BulletEditor
              key={bullet.id}
              bullet={bullet}
              onChange={(text) => {
                const realIdx = entry.bullets.findIndex(b => b.id === bullet.id);
                handleBulletChange(realIdx, text);
              }}
              onDelete={() => {
                const realIdx = entry.bullets.findIndex(b => b.id === bullet.id);
                handleDeleteBullet(realIdx);
              }}
            />
          ))}
        <button className="btn btn-ghost btn-sm" onClick={handleAddBullet}>
          + Add bullet
        </button>
      </div>
    </div>
  );
}

export default function ExperienceEditor({ experience, onChange }: ExperienceEditorProps) {
  const [expandedId, setExpandedId] = useState<string | null>(
    experience.length > 0 ? experience[0].source_id : null
  );

  const handleToggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="section-editor">
      <div className="section-title">
        <h3>Work Experience</h3>
        <p className="section-description">
          Edit your work experience entries and achievements.
        </p>
      </div>

      <div className="entries-list">
        {experience.map((entry) => (
          <div
            key={entry.source_id}
            className={`entry-card ${expandedId === entry.source_id ? 'expanded' : ''}`}
          >
            <div
              className="entry-card-header"
              onClick={() => handleToggleExpand(entry.source_id)}
            >
              <div className="entry-card-title">
                <span className="entry-title">{entry.title}</span>
                <span className="entry-company">{entry.company}</span>
              </div>
              <span className="expand-icon">{expandedId === entry.source_id ? '−' : '+'}</span>
            </div>
            {expandedId === entry.source_id && (
              <div className="entry-card-content">
                <EntryEditor
                  entry={entry}
                  onChange={(updated) => {
                    const newExp = experience.map(e =>
                      e.source_id === entry.source_id ? updated : e
                    );
                    onChange(newExp);
                  }}
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}