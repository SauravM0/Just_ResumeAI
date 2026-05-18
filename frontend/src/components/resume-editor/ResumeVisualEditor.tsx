import { useState, useEffect, useCallback, useRef } from 'react';
import type { ResumeRecommendation } from '../../types/resume';
import { updateHistory } from '../../lib/historyApi';
import SummaryEditor from './SummaryEditor';
import SkillsEditor from './SkillsEditor';
import ExperienceEditor from './ExperienceEditor';
import ProjectsEditor from './ProjectsEditor';
import EducationEditor from './EducationEditor';
import SectionOrderEditor from './SectionOrderEditor';
import ResumePreview from './ResumePreview';

interface ResumeVisualEditorProps {
  recommendation: ResumeRecommendation;
  generationId: string;
  onSave: (updated: ResumeRecommendation) => void;
}

type TabId = 'summary' | 'skills' | 'experience' | 'projects' | 'education' | 'order';

interface Tab {
  id: TabId;
  label: string;
}

const TABS: Tab[] = [
  { id: 'summary', label: 'Summary' },
  { id: 'skills', label: 'Skills' },
  { id: 'experience', label: 'Experience' },
  { id: 'projects', label: 'Projects' },
  { id: 'education', label: 'Education' },
  { id: 'order', label: 'Section Order' },
];

type SaveStatus = 'idle' | 'saving' | 'saved' | 'failed';

export default function ResumeVisualEditor({ recommendation, generationId, onSave }: ResumeVisualEditorProps) {
  const [editedResume, setEditedResume] = useState<ResumeRecommendation>(recommendation);
  const [activeTab, setActiveTab] = useState<TabId>('summary');
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [hasChanges, setHasChanges] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isMounted = useRef(true);

  useEffect(() => {
    setEditedResume(recommendation);
    setHasChanges(false);
    setSaveStatus('idle');
  }, [recommendation]);

  useEffect(() => {
    return () => { isMounted.current = false; };
  }, []);

  const doSave = useCallback(async (data: ResumeRecommendation) => {
    setSaveStatus('saving');
    try {
      await updateHistory(generationId, {
        resume_json: data,
        status: 'completed',
      });
      if (isMounted.current) {
        setHasChanges(false);
        setSaveStatus('saved');
        onSave(data);
        setTimeout(() => {
          if (isMounted.current) setSaveStatus('idle');
        }, 2000);
      }
    } catch {
      if (isMounted.current) {
        setSaveStatus('failed');
      }
    }
  }, [generationId, onSave]);

  const scheduleAutosave = useCallback((data: ResumeRecommendation) => {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => {
      doSave(data);
    }, 2000);
  }, [doSave]);

  const handleChange = useCallback((updated: ResumeRecommendation) => {
    setEditedResume(updated);
    setHasChanges(true);
    setSaveStatus('idle');
    scheduleAutosave(updated);
  }, [scheduleAutosave]);

  const handleSaveNow = async () => {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    await doSave(editedResume);
  };

  const handleReset = () => {
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current);
    setEditedResume(recommendation);
    setHasChanges(false);
    setSaveStatus('idle');
  };

  const renderTabContent = () => {
    switch (activeTab) {
      case 'summary':
        return (
          <SummaryEditor
            summary={editedResume.summary || ''}
            targetTitle={editedResume.target_title}
            onChange={(summary, targetTitle) =>
              handleChange({ ...editedResume, summary, target_title: targetTitle })
            }
          />
        );
      case 'skills':
        return (
          <SkillsEditor
            skills={editedResume.skills}
            onChange={(skills) => handleChange({ ...editedResume, skills })}
          />
        );
      case 'experience':
        return (
          <ExperienceEditor
            experience={editedResume.experience.filter(e => e.included)}
            onChange={(experience) => {
              const allExp = [...editedResume.experience];
              experience.forEach((exp) => {
                const originalIdx = allExp.findIndex(e => e.source_id === exp.source_id);
                if (originalIdx >= 0) allExp[originalIdx] = exp;
              });
              handleChange({ ...editedResume, experience: allExp });
            }}
          />
        );
      case 'projects':
        return (
          <ProjectsEditor
            projects={editedResume.projects.filter(p => p.included)}
            onChange={(projects) => {
              const allProj = [...editedResume.projects];
              projects.forEach((proj) => {
                const originalIdx = allProj.findIndex(p => p.source_id === proj.source_id);
                if (originalIdx >= 0) allProj[originalIdx] = proj;
              });
              handleChange({ ...editedResume, projects: allProj });
            }}
          />
        );
      case 'education':
        return (
          <EducationEditor
            education={editedResume.education.filter(e => e.included)}
            onChange={(education) => {
              const allEdu = [...editedResume.education];
              education.forEach((edu) => {
                const originalIdx = allEdu.findIndex(e => e.source_id === edu.source_id);
                if (originalIdx >= 0) allEdu[originalIdx] = edu;
              });
              handleChange({ ...editedResume, education: allEdu });
            }}
          />
        );
      case 'order':
        return (
          <SectionOrderEditor
            sectionOrder={editedResume.section_order || []}
            onChange={(section_order) => handleChange({ ...editedResume, section_order })}
          />
        );
      default:
        return null;
    }
  };

  const getSaveStatusLabel = () => {
    switch (saveStatus) {
      case 'saving': return 'Saving...';
      case 'saved': return 'Saved';
      case 'failed': return 'Save failed';
      default: return null;
    }
  };

  const getSaveStatusClass = () => {
    switch (saveStatus) {
      case 'saving': return 'save-status saving';
      case 'saved': return 'save-status success';
      case 'failed': return 'save-status error';
      default: return 'save-status';
    }
  };

  return (
    <div className="visual-editor">
      <div className="editor-header">
        <div className="editor-tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              className={`editor-tab ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="editor-actions">
          {saveStatus !== 'idle' && (
            <span className={getSaveStatusClass()}>
              {saveStatus === 'saving' && <span className="spinner" style={{ width: 14, height: 14, marginRight: 4 }} />}
              {getSaveStatusLabel()}
            </span>
          )}
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setShowPreview(!showPreview)}
          >
            {showPreview ? 'Hide Preview' : 'Preview'}
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleReset}
            disabled={!hasChanges}
          >
            Reset
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleSaveNow}
            disabled={!hasChanges || saveStatus === 'saving'}
          >
            {saveStatus === 'saving' ? 'Saving...' : hasChanges ? 'Save' : 'Saved'}
          </button>
        </div>
      </div>

      <div className={`editor-content ${showPreview ? 'with-preview' : ''}`}>
        <div className="editor-panel">
          <div className="editor-scroll">
            {renderTabContent()}
          </div>
        </div>
        {showPreview && (
          <div className="preview-panel">
            <ResumePreview recommendation={editedResume} />
          </div>
        )}
      </div>
    </div>
  );
}
