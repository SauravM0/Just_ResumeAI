/**
 * Section Order Editor component
 */

interface SectionOrderEditorProps {
  sectionOrder: string[];
  onChange: (sectionOrder: string[]) => void;
}

const DEFAULT_SECTION_ORDER = [
  'summary',
  'experience',
  'projects',
  'skills',
  'education',
  'certifications',
  'achievements',
];

const SECTION_LABELS: Record<string, string> = {
  summary: 'Professional Summary',
  experience: 'Work Experience',
  projects: 'Projects',
  skills: 'Skills',
  education: 'Education',
  certifications: 'Certifications',
  achievements: 'Achievements',
  awards: 'Awards',
};

export default function SectionOrderEditor({ sectionOrder, onChange }: SectionOrderEditorProps) {
  const orderedSections = sectionOrder.length > 0 ? sectionOrder : DEFAULT_SECTION_ORDER;

  const handleMoveUp = (index: number) => {
    if (index === 0) return;
    const newOrder = [...orderedSections];
    [newOrder[index - 1], newOrder[index]] = [newOrder[index], newOrder[index - 1]];
    onChange(newOrder);
  };

  const handleMoveDown = (index: number) => {
    if (index === orderedSections.length - 1) return;
    const newOrder = [...orderedSections];
    [newOrder[index], newOrder[index + 1]] = [newOrder[index + 1], newOrder[index]];
    onChange(newOrder);
  };

  const handleReset = () => {
    onChange(DEFAULT_SECTION_ORDER);
  };

  return (
    <div className="section-editor">
      <div className="section-title">
        <h3>Section Order</h3>
        <p className="section-description">
          Reorder the sections to customize your resume layout.
        </p>
      </div>

      <div className="section-order-list">
        {orderedSections.map((section, index) => (
          <div key={section} className="section-order-item">
            <span className="section-order-label">
              {SECTION_LABELS[section] || section}
            </span>
            <div className="section-order-actions">
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => handleMoveUp(index)}
                disabled={index === 0}
              >
                ↑
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => handleMoveDown(index)}
                disabled={index === orderedSections.length - 1}
              >
                ↓
              </button>
            </div>
          </div>
        ))}
      </div>

      <button className="btn btn-ghost" onClick={handleReset}>
        Reset to Default
      </button>
    </div>
  );
}