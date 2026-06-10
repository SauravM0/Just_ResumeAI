import type { RecruiterReview } from '../../types/resume';

interface RecruiterScoreCardProps {
  review: RecruiterReview;
}

export function RecruiterScoreCard({ review }: RecruiterScoreCardProps) {
  const score = review.overall_impression;
  const color = score >= 8 ? '#1D9E75' : score >= 6 ? '#E8920E' : '#E24B4A';
  const label = score >= 8 ? 'Strong candidate' : score >= 6 ? 'Competitive candidate' : 'Needs strengthening';

  return (
    <div
      className="card recruiter-score-card"
      style={{
        padding: 'var(--space-lg)',
        background: 'var(--bg-card)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-lg)', flexWrap: 'wrap' }}>
        <div style={{ textAlign: 'center', minWidth: 100 }}>
          <div style={{ fontWeight: 800, fontSize: '2rem', color, lineHeight: 1 }}>
            {score.toFixed(1)}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: 2 }}>/10</div>
        </div>

        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontWeight: 700, fontSize: '1.05rem', marginBottom: 2 }}>
            Recruiter Impact Score
          </div>
          <div style={{ color, fontWeight: 600, fontSize: '0.85rem', marginBottom: 6 }}>
            {label}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            {review.summary_assessment}
          </div>
        </div>
      </div>

      {review.hr_flags.length > 0 && (
        <div style={{ marginTop: 'var(--space-md)', padding: 'var(--space-sm) var(--space-md)', background: 'var(--bg-secondary, #f8fafc)', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontWeight: 600, fontSize: '0.82rem', marginBottom: 4 }}>Recruiter concerns:</div>
          {review.hr_flags.slice(0, 3).map((flag, i) => (
            <div key={i} style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginBottom: 2 }}>
              – {flag}
            </div>
          ))}
        </div>
      )}

      {review.recommended_for_shortlist && (
        <div style={{ marginTop: 'var(--space-md)', color: '#1D9E75', fontWeight: 600, fontSize: '0.85rem' }}>
          ✓ This resume would likely be shortlisted
        </div>
      )}

      {!review.recommended_for_shortlist && review.weak_bullet_ids.length > 0 && (
        <div style={{ marginTop: 'var(--space-md)', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
          {review.weak_bullet_ids.length} bullet{review.weak_bullet_ids.length !== 1 ? 's' : ''} need strengthening for better recruiter impact
        </div>
      )}
    </div>
  );
}
