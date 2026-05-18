import { describe, it, expect, vi, beforeEach } from 'vitest'

let mockSession: any = { user: { id: 'test-user', user_metadata: { full_name: 'Test User' } } }

vi.mock('../store/useAuthStore', () => ({
  useAuthStore: (selector: any) => {
    const state = {
      session: mockSession,
      user: mockSession?.user ?? null,
      loading: false,
      error: null,
      initialized: true,
      initialize: vi.fn(),
      signInWithGoogle: vi.fn(),
      signOut: vi.fn(),
      clearError: vi.fn(),
    }
    return selector ? selector(state) : state
  },
}))

const mockResetGeneration = vi.fn()
let mockGenerationId: string | null = null

vi.mock('../store/useAppStore', () => ({
  useAppStore: (selector: any) => {
    const state = {
      resetGeneration: mockResetGeneration,
      generationId: mockGenerationId,
      currentStep: 'dashboard',
      setStep: vi.fn(),
      setGenerationId: vi.fn(),
      parsedJD: null,
      setParsedJD: vi.fn(),
      recommendation: null,
      setRecommendation: vi.fn(),
      atsScore: null,
      setAtsScore: vi.fn(),
      alignmentReport: null,
      setAlignmentReport: vi.fn(),
      latexSource: null,
      setLatexSource: vi.fn(),
      pipelinePdf: null,
      setPipelinePdf: vi.fn(),
      activeProfile: null,
      setActiveProfile: vi.fn(),
      resetJobGeneration: vi.fn(),
    }
    return selector ? selector(state) : state
  },
}))

vi.mock('../lib/profileApi', () => ({
  getMyProfile: vi.fn(),
}))

vi.mock('../lib/historyApi', () => ({
  getHistory: vi.fn(),
}))

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { getMyProfile } from '../lib/profileApi'
import { getHistory } from '../lib/historyApi'
import type { Mock } from 'vitest'
import Dashboard from '../pages/Dashboard'

const sampleProfile = {
  id: 'prof-1',
  user_id: 'test-user',
  profile_json: {
    id: 'prof-1',
    version: 1,
    contact: { full_name: 'Test User', email: 'test@example.com' },
    summary: 'A summary',
    work_experience: [],
    education: [],
    skills: [],
    projects: [],
    certifications: [],
    publications: [],
    volunteer: [],
    awards: [],
    custom_sections: {},
  },
  profile_completion_score: 80,
  status: 'active',
}

const sampleHistory = [
  {
    generation_id: 'gen-1',
    job_title: 'Software Engineer',
    company: 'Acme Corp',
    created_at: '2026-01-15T00:00:00Z',
    updated_at: '2026-01-15T00:00:00Z',
    status: 'completed',
    ats_score_summary: { overall_score: 85, keyword_coverage: 78 },
    has_pdf: true,
    has_cover_letter: false,
    file_expiry_info: {
      has_files: true,
      pdf_available: true,
      docx_available: false,
      expires_at: '2026-06-15T00:00:00Z',
      is_expired: false,
      regenerate_available: true,
      files: [{ file_type: 'pdf', expires_at: '2026-06-15T00:00:00Z', is_expired: false }],
      earliest_expiry: '2026-06-15T00:00:00Z',
    },
  },
]

describe('Dashboard Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSession = { user: { id: 'test-user', user_metadata: { full_name: 'Test User' } } }
    mockGenerationId = null
  })

  it('renders dashboard skeleton while loading', () => {
    (getMyProfile as Mock).mockReturnValue(new Promise(() => {}))
    ;(getHistory as Mock).mockReturnValue(new Promise(() => {}))
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    )
    expect(document.querySelector('.skeleton')).toBeInTheDocument()
  })

  it('renders dashboard stats row after loading', async () => {
    (getMyProfile as Mock).mockResolvedValue(sampleProfile)
    ;(getHistory as Mock).mockResolvedValue(sampleHistory)
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    )
    expect(await screen.findByText('Welcome back, Test')).toBeInTheDocument()
    expect(screen.getByText('1/4 sections')).toBeInTheDocument()
    expect(screen.getAllByText('85')).toHaveLength(2)
  })

  it('renders empty state when no history', async () => {
    (getMyProfile as Mock).mockResolvedValue(sampleProfile)
    ;(getHistory as Mock).mockResolvedValue([])
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    )
    expect(await screen.findByText('No resumes yet')).toBeInTheDocument()
  })

  it('renders error state when both API calls fail', async () => {
    (getMyProfile as Mock).mockRejectedValue(new Error('Network error'))
    ;(getHistory as Mock).mockRejectedValue(new Error('Network error'))
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    )
    expect(await screen.findByText('Failed to load your dashboard data. Check your connection and try again.')).toBeInTheDocument()
  })
})
