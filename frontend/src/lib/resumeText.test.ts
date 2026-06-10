import { describe, expect, it } from 'vitest'

import {
  recommendationSkillsToText,
  recommendationToMarkdown,
  recommendationToPlainText,
} from './resumeText'
import type { ResumeRecommendation } from '../types/resume'

function recommendation(overrides: Partial<ResumeRecommendation> = {}): ResumeRecommendation {
  return {
    generation_id: 'gen-test',
    version_id: 'v1',
    target_title: 'Backend Software Engineer',
    summary: 'Backend engineer with Python and FastAPI project experience.',
    contact: {
      full_name: 'Rahul Sharma',
      email: 'rahul@example.com',
      phone: '+91-9876543210',
      location: 'Bengaluru',
    },
    skills: [
      {
        category: 'Backend',
        skills: ['Python', 'FastAPI', 'PostgreSQL'],
      },
    ],
    experience: [
      {
        source_id: 'exp-1',
        company: 'Infosys',
        title: 'Software Engineer',
        start_date: '2021-07',
        end_date: null,
        included: true,
        bullets: [
          {
            id: 'bullet-1',
            text: 'Built FastAPI services reducing response time by 30%.',
            status: 'accepted',
          },
          {
            id: 'bullet-2',
            text: 'Rejected bullet should not appear.',
            status: 'rejected',
          },
        ],
      },
    ],
    projects: [],
    education: [
      {
        source_id: 'edu-1',
        institution: 'VIT University',
        degree: 'B.Tech',
        included: true,
      },
    ],
    certifications: [],
    achievements: [],
    awards: [],
    custom_sections: [],
    section_order: [],
    warnings: [],
    locked_fields: {},
    ...overrides,
  }
}

describe('resumeText', () => {
  it('renders skills as categorized plain text', () => {
    expect(recommendationSkillsToText(recommendation())).toBe(
      'Backend: Python, FastAPI, PostgreSQL',
    )
  })

  it('omits rejected bullets from plain text and markdown output', () => {
    const rec = recommendation()

    const plainText = recommendationToPlainText(rec)
    const markdown = recommendationToMarkdown(rec)

    expect(plainText).toContain('RAHUL SHARMA')
    expect(plainText).toContain('Built FastAPI services reducing response time by 30%.')
    expect(markdown).toContain('# Rahul Sharma')
    expect(markdown).toContain('### Experience')
    expect(plainText).not.toContain('Rejected bullet should not appear.')
    expect(markdown).not.toContain('Rejected bullet should not appear.')
  })

  it('blocks JD boilerplate contamination in plain text export', () => {
    const plainText = recommendationToPlainText(
      recommendation({
        summary: 'We are seeking a backend engineer with Python skills.',
      }),
    )

    expect(plainText).toBe('')
  })
})
