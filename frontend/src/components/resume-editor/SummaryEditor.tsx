/**
 * Summary Editor component
 */

interface SummaryEditorProps {
  summary: string;
  targetTitle: string;
  onChange: (summary: string, targetTitle: string) => void;
}

export default function SummaryEditor({ summary, targetTitle, onChange }: SummaryEditorProps) {
  return (
    <div className="section-editor">
      <div className="section-title">
        <h3>Professional Summary</h3>
        <p className="section-description">
          Write a concise summary that highlights your relevant experience and skills.
        </p>
      </div>

      <div className="form-group">
        <label className="form-label">Target Job Title</label>
        <input
          type="text"
          className="input"
          value={targetTitle}
          onChange={(e) => onChange(summary, e.target.value)}
          placeholder="e.g., Senior Software Engineer"
        />
      </div>

      <div className="form-group">
        <label className="form-label">Summary</label>
        <textarea
          className="textarea"
          value={summary}
          onChange={(e) => onChange(e.target.value, targetTitle)}
          placeholder="Write a brief professional summary..."
          rows={6}
        />
        <div className="form-hint">
          Keep it concise (2-4 sentences). Focus on your experience and key skills.
        </div>
      </div>
    </div>
  );
}