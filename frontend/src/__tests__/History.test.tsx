import { describe, it, expect, vi, beforeEach } from 'vitest'

let mockSession: any = { user: { id: 'test-user' } }

vi.mock('../store/useAuthStore', () => ({
  useAuthStore: (selector: any) => {
    const state = {
      session: mockSession,
      loading: false,
      initialized: true,
    }
    return selector ? selector(state) : state
  },
}))

vi.mock('../lib/historyApi', () => ({
  getHistory: vi.fn(),
}))

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { getHistory } from '../lib/historyApi'
import type { Mock } from 'vitest'
import History from '../pages/History'

const sampleItems = [
  {
    generation_id: 'gen-1',
    job_title: 'Software Engineer',
    company: 'Acme Corp',
    created_at: '2026-01-15T00:00:00Z',
    updated_at: '2026-01-15T00:00:00Z',
    status: 'completed',
    ats_score_summary: { overall_score: 85, keyword_coverage: 78 },
    has_pdf: true,
    has_cover_letter: true,
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
  {
    generation_id: 'gen-2',
    job_title: 'Product Manager',
    company: 'Beta Inc',
    created_at: '2026-02-20T00:00:00Z',
    updated_at: '2026-02-20T00:00:00Z',
    status: 'failed',
    ats_score_summary: { overall_score: null, keyword_coverage: null },
    has_pdf: false,
    has_cover_letter: false,
    file_expiry_info: {
      has_files: false,
      pdf_available: false,
      docx_available: false,
      expires_at: null,
      is_expired: false,
      regenerate_available: false,
      files: [],
      earliest_expiry: null,
    },
  },
]

describe('History Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSession = { user: { id: 'test-user' } }
  })

  it('renders loading state', () => {
    ;(getHistory as Mock).mockReturnValue(new Promise(() => {}))
    render(
      <MemoryRouter>
        <History />
      </MemoryRouter>
    )
    expect(screen.getByText('Loading your resume history...')).toBeInTheDocument()
  })

  it('renders history list items', async () => {
    ;(getHistory as Mock).mockResolvedValue(sampleItems)
    render(
      <MemoryRouter>
        <History />
      </MemoryRouter>
    )
    expect(await screen.findByText('Software Engineer')).toBeInTheDocument()
    expect(screen.getByText('Product Manager')).toBeInTheDocument()
    expect(screen.getByText('Acme Corp | 1/15/2026')).toBeInTheDocument()
    expect(screen.getByText('Beta Inc | 2/20/2026')).toBeInTheDocument()
    expect(screen.getByText('85 ATS')).toBeInTheDocument()
    expect(screen.getByText('PDF')).toBeInTheDocument()
    expect(screen.getByText('Cover')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
  })

  it('renders empty state when no items', async () => {
    ;(getHistory as Mock).mockResolvedValue([])
    render(
      <MemoryRouter>
        <History />
      </MemoryRouter>
    )
    expect(await screen.findByText('No resume history yet')).toBeInTheDocument()
  })

  it('renders error state on API failure', async () => {
    ;(getHistory as Mock).mockRejectedValue(new Error('Failed to fetch'))
    render(
      <MemoryRouter>
        <History />
      </MemoryRouter>
    )
    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('Failed to fetch')).toBeInTheDocument()
  })
})
