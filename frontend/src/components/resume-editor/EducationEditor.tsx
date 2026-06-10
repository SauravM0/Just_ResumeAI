/**
 * Education Editor component
 */

import type { ResumeEducationEntry } from '../../types/resume';
import LockedField from '../ui/LockedField';

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
      <LockedField
        value={entry.institution}
        label="Institution"
        reason="Institution name is verified from your profile and cannot be changed"
      />
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
      <LockedField
        value={entry.gpa || ''}
        label="GPA"
        reason="GPA is verified from your academic record and cannot be changed"
      />
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