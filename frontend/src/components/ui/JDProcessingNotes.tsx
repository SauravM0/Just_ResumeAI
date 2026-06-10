interface Props {
  warnings?: string[] | null;
  className?: string;
}

export default function JDProcessingNotes({ warnings, className = '' }: Props) {
  const items = [...new Set((warnings ?? []).filter(Boolean))];
  if (items.length === 0) return null;

  return (
    <section className={`jd-processing-notes card ${className}`} aria-live="polite">
      <div className="section-label">JD processing notes</div>
      <h2>Job description cleaned for resume generation</h2>
      <div className="jd-processing-list">
        {items.slice(0, 4).map((warning) => (
          <p key={warning}>{warning}</p>
        ))}
      </div>
    </section>
  );
}
