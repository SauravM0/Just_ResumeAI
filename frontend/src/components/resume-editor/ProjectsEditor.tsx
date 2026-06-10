/**
 * Projects Editor component
 */

import { useState } from 'react';
import type { ResumeProjectEntry, ResumeBullet } from '../../types/resume';
import { BulletQualityBadge } from '../ui/BulletQualityBadge';
import { objectArray, joinedStrings } from '../../lib/resumeSafe';

interface ProjectsEditorProps {
  projects: ResumeProjectEntry[];
  onChange: (projects: ResumeProjectEntry[]) => void;
  onImproveBullet?: (bulletId: string) => void;
}

function BulletEditor({
  bullet,
  onChange,
  onDelete,
  onImprove,
}: {
  bullet: ResumeBullet;
  onChange: (text: string) => void;
  onDelete: () => void;
  onImprove?: () => void;
}) {
  return (
    <div className="bullet-editor">
      {bullet.star_score !== undefined && (
        <BulletQualityBadge
          starScore={bullet.star_score}
          hasAction={bullet.has_strong_verb ?? true}
          hasContext={bullet.has_context ?? true}
          hasOutcome={bullet.has_outcome ?? false}
          hasBannedPhrase={bullet.has_banned_phrase ?? false}
          onImprove={onImprove}
        />
      )}
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

function ProjectEditor({
  project,
  onChange,
  onImproveBullet,
}: {
  project: ResumeProjectEntry;
  onChange: (project: ResumeProjectEntry) => void;
  onImproveBullet?: (bulletId: string) => void;
}) {
  const handleFieldChange = (field: keyof ResumeProjectEntry, value: string | string[]) => {
    onChange({ ...project, [field]: value });
  };

  const handleBulletChange = (bulletIndex: number, text: string) => {
    const bullets = [...objectArray<ResumeBullet>(project.bullets)];
    bullets[bulletIndex] = { ...bullets[bulletIndex], text, status: 'edited' };
    onChange({ ...project, bullets });
  };

  const handleDeleteBullet = (bulletIndex: number) => {
    const bullets = objectArray<ResumeBullet>(project.bullets).filter((_, i) => i !== bulletIndex);
    onChange({ ...project, bullets });
  };

  const handleAddBullet = () => {
    const newBullet: ResumeBullet = {
      id: `bullet-${Date.now()}`,
      text: '',
      status: 'edited',
      relevance_score: 0,
      matched_keywords: [],
    };
    onChange({ ...project, bullets: [...objectArray<ResumeBullet>(project.bullets), newBullet] });
  };

  return (
    <div className="entry-editor">
      <div className="entry-header">
        <input
          type="text"
          className="input"
          value={project.name}
          onChange={(e) => handleFieldChange('name', e.target.value)}
          placeholder="Project Name"
        />
      </div>
      <div className="form-group">
        <input
          type="text"
          className="input"
          value={joinedStrings(project.technologies)}
          onChange={(e) => handleFieldChange('technologies', e.target.value.split(',').map(t => t.trim()))}
          placeholder="Technologies (comma separated)"
        />
      </div>
      <div className="entry-bullets">
        <label className="form-label">Description</label>
        {objectArray<ResumeBullet>(project.bullets)
          .filter(b => b.status !== 'rejected')
          .map((bullet) => (
            <BulletEditor
              key={bullet.id}
              bullet={bullet}
              onChange={(text) => {
                const realIdx = objectArray<ResumeBullet>(project.bullets).findIndex(b => b.id === bullet.id);
                handleBulletChange(realIdx, text);
              }}
              onDelete={() => {
                const realIdx = objectArray<ResumeBullet>(project.bullets).findIndex(b => b.id === bullet.id);
                handleDeleteBullet(realIdx);
              }}
              onImprove={onImproveBullet ? () => onImproveBullet(bullet.id) : undefined}
            />
          ))}
        <button className="btn btn-ghost btn-sm" onClick={handleAddBullet}>
          + Add bullet
        </button>
      </div>
    </div>
  );
}

export default function ProjectsEditor({ projects, onChange, onImproveBullet }: ProjectsEditorProps) {
  const [expandedId, setExpandedId] = useState<string | null>(
    projects.length > 0 ? projects[0].source_id : null
  );

  const handleToggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="section-editor">
      <div className="section-title">
        <h3>Projects</h3>
        <p className="section-description">
          Edit your relevant projects.
        </p>
      </div>

      <div className="entries-list">
        {projects.map((project) => (
          <div
            key={project.source_id}
            className={`entry-card ${expandedId === project.source_id ? 'expanded' : ''}`}
          >
            <div
              className="entry-card-header"
              onClick={() => handleToggleExpand(project.source_id)}
            >
              <div className="entry-card-title">
                <span className="entry-title">{project.name}</span>
                <span className="entry-company">{joinedStrings(project.technologies)}</span>
              </div>
              <span className="expand-icon">{expandedId === project.source_id ? '−' : '+'}</span>
            </div>
            {expandedId === project.source_id && (
              <div className="entry-card-content">
                <ProjectEditor
                  project={project}
                  onImproveBullet={onImproveBullet}
                  onChange={(updated) => {
                    const newProj = projects.map(p =>
                      p.source_id === project.source_id ? updated : p
                    );
                    onChange(newProj);
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
