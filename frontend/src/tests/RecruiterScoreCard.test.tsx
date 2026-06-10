import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RecruiterScoreCard } from '../components/ui/RecruiterScoreCard'
import type { RecruiterReview } from '../types/resume'

function review(overrides: Partial<RecruiterReview> = {}): RecruiterReview {
  return {
    overall_impression: 8.6,
    summary_assessment: 'Strong evidence of relevant impact.',
    weak_bullet_ids: [],
    recommended_for_shortlist: true,
    hr_flags: [],
    ...overrides,
  }
}

describe('RecruiterScoreCard', () => {
  it('renders strong candidate summary and shortlist signal', () => {
    render(<RecruiterScoreCard review={review()} />)

    expect(screen.getByText('8.6')).toHaveStyle('color: #1D9E75')
    expect(screen.getByText('Recruiter Impact Score')).toBeInTheDocument()
    expect(screen.getByText('Strong candidate')).toHaveStyle('color: #1D9E75')
    expect(screen.getByText('Strong evidence of relevant impact.')).toBeInTheDocument()
    expect(screen.getByText(/shortlisted/i)).toBeInTheDocument()
  })

  it('renders competitive candidate for mid scores', () => {
    render(<RecruiterScoreCard review={review({ overall_impression: 6.4 })} />)

    expect(screen.getByText('6.4')).toHaveStyle('color: #E8920E')
    expect(screen.getByText('Competitive candidate')).toBeInTheDocument()
  })

  it('renders concerns and weak bullet count for lower non-shortlisted scores', () => {
    render(
      <RecruiterScoreCard
        review={review({
          overall_impression: 5.2,
          recommended_for_shortlist: false,
          weak_bullet_ids: ['b1', 'b2'],
          hr_flags: ['No measurable outcomes', 'Missing required tool'],
        })}
      />,
    )

    expect(screen.getByText('Needs strengthening')).toHaveStyle('color: #E24B4A')
    expect(screen.getByText('Recruiter concerns:')).toBeInTheDocument()
    expect(screen.getByText(/No measurable outcomes/)).toBeInTheDocument()
    expect(screen.getByText(/2 bullets need strengthening/)).toBeInTheDocument()
  })
})
