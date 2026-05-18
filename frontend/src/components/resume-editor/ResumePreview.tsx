/**
 * Resume Preview component - shows formatted preview of the resume
 */

import type { ResumeRecommendation } from '../../types/resume';

interface ResumePreviewProps {
  recommendation: ResumeRecommendation;
}

export default function ResumePreview({ recommendation }: ResumePreviewProps) {
  const orderedSections = recommendation.section_order?.length > 0
    ? recommendation.section_order
    : ['summary', 'skills', 'experience', 'projects', 'education'];

  const hasSection = (section: string): boolean => {
    switch (section) {
      case 'summary':
        return Boolean(recommendation.summary);
      case 'skills':
        return recommendation.skills.length > 0;
      case 'experience':
        return recommendation.experience.filter(e => e.included).length > 0;
      case 'projects':
        return recommendation.projects.filter(p => p.included).length > 0;
      case 'education':
        return recommendation.education.filter(e => e.included).length > 0;
      case 'certifications':
        return recommendation.certifications?.filter(c => c.included).length > 0;
      case 'achievements':
        return [...(recommendation.achievements || []), ...(recommendation.awards || [])].filter(a => a.included).length > 0;
      default:
        return false;
    }
  };

  const formatDate = (date: string | undefined): string => {
    if (!date) return '';
    return date;
  };

  return (
    <div className="resume-preview">
      <div className="preview-paper">
        {recommendation.contact && (
          <header className="preview-header">
            <h1 className="preview-name">{recommendation.contact.full_name}</h1>
            <div className="preview-contact">
              {[recommendation.contact.email, recommendation.contact.phone, recommendation.contact.location]
                .filter(Boolean)
                .join(' | ')}
            </div>
            <div className="preview-links">
              {[recommendation.contact.linkedin_url, recommendation.contact.github_url, recommendation.contact.portfolio_url]
                .filter(Boolean)
                .join(' | ')}
            </div>
          </header>
        )}

        {recommendation.target_title && (
          <div className="preview-title">{recommendation.target_title}</div>
        )}

        {orderedSections.map(section => {
          if (!hasSection(section)) return null;

          switch (section) {
            case 'summary':
              return (
                <section key={section} className="preview-section">
                  <h2 className="preview-section-title">Summary</h2>
                  <p className="preview-text">{recommendation.summary}</p>
                </section>
              );
            case 'skills':
              return (
                <section key={section} className="preview-section">
                  <h2 className="preview-section-title">Skills</h2>
                  {recommendation.skills.map((group, idx) => (
                    <div key={idx} className="preview-skills-group">
                      <strong>{group.category}:</strong> {group.skills.join(', ')}
                    </div>
                  ))}
                </section>
              );
            case 'experience':
              return (
                <section key={section} className="preview-section">
                  <h2 className="preview-section-title">Experience</h2>
                  {recommendation.experience.filter(e => e.included).map(exp => (
                    <div key={exp.source_id} className="preview-entry">
                      <div className="preview-entry-header">
                        <span className="preview-entry-title">{exp.title}</span>
                        <span className="preview-entry-dates">
                          {formatDate(exp.start_date)} - {exp.end_date || 'Present'}
                        </span>
                      </div>
                      <div className="preview-entry-subtitle">{exp.company}</div>
                      <ul className="preview-bullets">
                        {exp.bullets.filter(b => b.status !== 'rejected').map(bullet => (
                          <li key={bullet.id}>{bullet.text}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </section>
              );
            case 'projects':
              return (
                <section key={section} className="preview-section">
                  <h2 className="preview-section-title">Projects</h2>
                  {recommendation.projects.filter(p => p.included).map(proj => (
                    <div key={proj.source_id} className="preview-entry">
                      <div className="preview-entry-header">
                        <span className="preview-entry-title">{proj.name}</span>
                        <span className="preview-entry-tech">{proj.technologies.join(', ')}</span>
                      </div>
                      <ul className="preview-bullets">
                        {proj.bullets.filter(b => b.status !== 'rejected').map(bullet => (
                          <li key={bullet.id}>{bullet.text}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </section>
              );
            case 'education':
              return (
                <section key={section} className="preview-section">
                  <h2 className="preview-section-title">Education</h2>
                  {recommendation.education.filter(e => e.included).map(edu => (
                    <div key={edu.source_id} className="preview-entry">
                      <div className="preview-entry-header">
                        <span className="preview-entry-title">{edu.institution}</span>
                        <span className="preview-entry-dates">
                          {formatDate(edu.start_date)} - {formatDate(edu.end_date)}
                        </span>
                      </div>
                      <div className="preview-entry-subtitle">
                        {[edu.degree, edu.field_of_study, edu.gpa ? `GPA: ${edu.gpa}` : null].filter(Boolean).join(', ')}
                      </div>
                    </div>
                  ))}
                </section>
              );
            default:
              return null;
          }
        })}
      </div>
    </div>
  );
}