/**
 * Education Editor component
 */

import type { ResumeEducationEntry } from '../../types/resume';

interface EducationEditorProps {
  education: ResumeEducationEntry[];
  onChange: (education: ResumeEducationEntry[]) => void;
}

function EducationEntryEditor({
  entry,
  onChange,
}: {
  entry: ResumeEducationEntry;
  onChange: (entry: ResumeEducationEntry) => void;
}) {
  const handleFieldChange = (field: keyof ResumeEducationEntry, value: string) => {
    onChange({ ...entry, [field]: value });
  };

  return (
    <div className="education-entry">
      <div className="form-group">
        <input
          type="text"
          className="input"
          value={entry.institution}
          onChange={(e) => handleFieldChange('institution', e.target.value)}
          placeholder="Institution"
        />
      </div>
      <div className="form-row">
        <div className="form-group">
          <input
            type="text"
            className="input"
            value={entry.degree}
            onChange={(e) => handleFieldChange('degree', e.target.value)}
            placeholder="Degree"
          />
        </div>
        <div className="form-group">
          <input
            type="text"
            className="input"
            value={entry.field_of_study || ''}
            onChange={(e) => handleFieldChange('field_of_study', e.target.value)}
            placeholder="Field of Study"
          />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <input
            type="text"
            className="input"
            value={entry.start_date || ''}
            onChange={(e) => handleFieldChange('start_date', e.target.value)}
            placeholder="Start Year"
          />
        </div>
        <div className="form-group">
          <input
            type="text"
            className="input"
            value={entry.end_date || ''}
            onChange={(e) => handleFieldChange('end_date', e.target.value)}
            placeholder="End Year"
          />
        </div>
      </div>
      <div className="form-group">
        <input
          type="text"
          className="input"
          value={entry.gpa || ''}
          onChange={(e) => handleFieldChange('gpa', e.target.value)}
          placeholder="GPA (optional)"
        />
      </div>
    </div>
  );
}

export default function EducationEditor({ education, onChange }: EducationEditorProps) {
  return (
    <div className="section-editor">
      <div className="section-title">
        <h3>Education</h3>
        <p className="section-description">
          Edit your educational background.
        </p>
      </div>

      <div className="entries-list">
        {education.map((entry) => (
          <div key={entry.source_id} className="entry-card expanded">
            <div className="entry-card-content">
              <EducationEntryEditor
                entry={entry}
                onChange={(updated) => {
                  const newEdu = education.map(e =>
                    e.source_id === entry.source_id ? updated : e
                  );
                  onChange(newEdu);
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}