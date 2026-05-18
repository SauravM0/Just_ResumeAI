/**
 * Skills Editor component
 */

import type { ResumeSkillGroup } from '../../types/resume';

interface SkillsEditorProps {
  skills: ResumeSkillGroup[];
  onChange: (skills: ResumeSkillGroup[]) => void;
}

export default function SkillsEditor({ skills, onChange }: SkillsEditorProps) {
  const handleCategoryChange = (index: number, newCategory: string) => {
    const updated = [...skills];
    updated[index] = { ...updated[index], category: newCategory };
    onChange(updated);
  };

  const handleSkillsChange = (index: number, skillsText: string) => {
    const updated = [...skills];
    const skillsArray = skillsText
      .split(',')
      .map(s => s.trim())
      .filter(s => s.length > 0);
    updated[index] = { ...updated[index], skills: skillsArray };
    onChange(updated);
  };

  const handleAddCategory = () => {
    onChange([...skills, { category: 'New Category', skills: [] }]);
  };

  const handleRemoveCategory = (index: number) => {
    onChange(skills.filter((_, i) => i !== index));
  };

  return (
    <div className="section-editor">
      <div className="section-title">
        <h3>Technical Skills</h3>
        <p className="section-description">
          Organize your skills by category. Use commas to separate skills.
        </p>
      </div>

      <div className="skills-list">
        {skills.map((group, index) => (
          <div key={index} className="skill-group">
            <div className="skill-header">
              <input
                type="text"
                className="input"
                value={group.category}
                onChange={(e) => handleCategoryChange(index, e.target.value)}
                placeholder="Category name"
              />
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => handleRemoveCategory(index)}
              >
                Remove
              </button>
            </div>
            <textarea
              className="textarea"
              value={group.skills.join(', ')}
              onChange={(e) => handleSkillsChange(index, e.target.value)}
              placeholder="Python, JavaScript, AWS, Docker..."
              rows={2}
            />
          </div>
        ))}
      </div>

      <button className="btn btn-secondary" onClick={handleAddCategory}>
        + Add Skill Category
      </button>
    </div>
  );
}