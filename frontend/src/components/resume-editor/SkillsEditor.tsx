/**
 * Skills Editor component
 */

import { useState } from 'react';
import type { ResumeSkillGroup } from '../../types/resume';
import { joinedStrings, stringArray } from '../../lib/resumeSafe';

const CLEAN_CATEGORIES = [
  'Programming Languages',
  'Frontend Frameworks',
  'Backend Frameworks',
  'Databases',
  'Cloud & DevOps',
  'Tools',
  'Domain Platforms',
  'AI/ML',
  'Learning Focus',
  'Soft Skills',
  'Review Needed',
];

const INVALID_SKILLS = new Set([
  'strong',
  'good',
  'excellent',
  'familiar',
  'basic',
  'advanced',
  'good team player',
  'communication skills',
  'leadership',
  'problem solving',
]);

function cleanSkill(value: string): string | null {
  const cleaned = value.trim().replace(/\s+/g, ' ');
  const key = cleaned.toLowerCase();
  if (!cleaned || INVALID_SKILLS.has(key)) return null;
  if (cleaned.split(/\s+/).length > 4) return null;
  if (/^[a-z0-9]+(?:-[a-z0-9]+){2,}$/i.test(cleaned)) return null;
  return cleaned;
}

function categoryForSkill(skill: string, fallback: string): string {
  const key = skill.toLowerCase();
  if (['ms word', 'word', 'excel', 'ms excel', 'powerpoint', 'ms powerpoint', 'git', 'jira', 'postman'].includes(key)) {
    return 'Tools';
  }
  if (['react.js', 'react', 'angular', 'vue', 'next.js'].includes(key)) return 'Frontend Frameworks';
  if (['node.js', 'express.js', 'django', 'flask', 'fastapi', 'spring boot', 'asp.net'].includes(key)) return 'Backend Frameworks';
  if (['python', 'javascript', 'typescript', 'java', 'c#', 'c++', 'sql', 'go'].includes(key)) return 'Programming Languages';
  return CLEAN_CATEGORIES.includes(fallback) ? fallback : 'Review Needed';
}

function cleanGroups(groups: ResumeSkillGroup[]): ResumeSkillGroup[] {
  const grouped = new Map<string, string[]>();
  groups.forEach((group) => {
    stringArray(group.skills)
      .map(cleanSkill)
      .filter((skill): skill is string => Boolean(skill))
      .forEach((skill) => {
        const category = categoryForSkill(skill, group.category);
        grouped.set(category, [...(grouped.get(category) ?? []), skill]);
      });
  });
  return CLEAN_CATEGORIES
    .filter((category) => grouped.has(category))
    .map((category) => ({
      category,
      skills: Array.from(new Set(grouped.get(category))),
    }));
}

interface SkillsEditorProps {
  skills: ResumeSkillGroup[];
  onChange: (skills: ResumeSkillGroup[]) => void;
}

export default function SkillsEditor({ skills, onChange }: SkillsEditorProps) {
  const [draftCategory, setDraftCategory] = useState<string | null>(null);
  const [draftSkills, setDraftSkills] = useState('');

  const handleCategoryChange = (index: number, newCategory: string) => {
    const updated = [...skills];
    updated[index] = { ...updated[index], category: newCategory };
    onChange(cleanGroups(updated));
  };

  const handleSkillsChange = (index: number, skillsText: string) => {
    const updated = [...skills];
    const skillsArray = skillsText
      .split(',')
      .map(cleanSkill)
      .filter((skill): skill is string => Boolean(skill));
    updated[index] = { ...updated[index], skills: skillsArray };
    onChange(cleanGroups(updated));
  };

  const handleAddCategory = () => {
    setDraftCategory('Review Needed');
    setDraftSkills('');
  };

  const handleRemoveCategory = (index: number) => {
    onChange(skills.filter((_, i) => i !== index));
  };

  const commitDraftSkills = () => {
    const parsedSkills = draftSkills
      .split(',')
      .map(cleanSkill)
      .filter((skill): skill is string => Boolean(skill));
    if (!draftCategory || parsedSkills.length === 0) return;
    onChange(cleanGroups([...skills, { category: draftCategory, skills: parsedSkills }]));
    setDraftCategory(null);
    setDraftSkills('');
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
              <select
                className="input"
                value={group.category}
                onChange={(e) => handleCategoryChange(index, e.target.value)}
              >
                {CLEAN_CATEGORIES.map((category) => (
                  <option key={category} value={category}>{category}</option>
                ))}
              </select>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => handleRemoveCategory(index)}
              >
                Remove
              </button>
            </div>
            <textarea
              className="textarea"
              value={joinedStrings(group.skills)}
              onChange={(e) => handleSkillsChange(index, e.target.value)}
              placeholder="Python, JavaScript, AWS, Docker..."
              rows={2}
            />
          </div>
        ))}
        {draftCategory && (
          <div className="skill-group">
            <div className="skill-header">
              <select
                className="input"
                value={draftCategory}
                onChange={(e) => setDraftCategory(e.target.value)}
              >
                {CLEAN_CATEGORIES.map((category) => (
                  <option key={category} value={category}>{category}</option>
                ))}
              </select>
              <button className="btn btn-ghost btn-sm" onClick={() => setDraftCategory(null)}>
                Remove
              </button>
            </div>
            <textarea
              className="textarea"
              value={draftSkills}
              onChange={(e) => setDraftSkills(e.target.value)}
              placeholder="Python, JavaScript, AWS, Docker..."
              rows={2}
            />
            <button className="btn btn-secondary btn-sm" onClick={commitDraftSkills}>
              Add
            </button>
          </div>
        )}
      </div>

      <button className="btn btn-secondary" onClick={handleAddCategory} disabled={Boolean(draftCategory)}>
        + Add Skill Category
      </button>
    </div>
  );
}
