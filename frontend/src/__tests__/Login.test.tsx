import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockSignInWithGoogle = vi.fn()
const mockClearError = vi.fn()
let mockSession: any = null
let mockLoading = false
let mockError: string | null = null

vi.mock('../store/useAuthStore', () => ({
  useAuthStore: (selector: any) => {
    const state = {
      session: mockSession,
      user: null,
      loading: mockLoading,
      error: mockError,
      initialized: true,
      initialize: vi.fn(),
      signInWithGoogle: mockSignInWithGoogle,
      signOut: vi.fn(),
      clearError: mockClearError,
    }
    return selector ? selector(state) : state
  },
}))

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Login from '../pages/Login'

describe('Login Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSession = null
    mockLoading = false
    mockError = null
  })

  it('renders sign-in heading and Google button', () => {
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    )
    expect(screen.getByText('Sign in to continue')).toBeInTheDocument()
    expect(screen.getByText('Continue with Google')).toBeInTheDocument()
  })

  it('starts Google login with the protected route return path', async () => {
    const { default: userEvent } = await import('@testing-library/user-event')
    render(
      <MemoryRouter initialEntries={[{ pathname: '/login', state: { from: { pathname: '/history/abc', search: '?tab=files' } } }]}>
        <Login />
      </MemoryRouter>
    )

    await userEvent.click(screen.getByText('Continue with Google'))

    expect(mockClearError).toHaveBeenCalled()
    expect(mockSignInWithGoogle).toHaveBeenCalledWith('/history/abc?tab=files')
  })

  it('redirects to dashboard when already authenticated', () => {
    mockSession = { user: { id: 'test-user' } }
    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/dashboard" element={<div>Dashboard</div>} />
        </Routes>
      </MemoryRouter>
    )
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.queryByText('Sign in to continue')).not.toBeInTheDocument()
  })

  it('shows error message when auth error exists', () => {
    mockError = 'Google sign-in failed.'
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    )
    expect(screen.getByText('Google sign-in failed.')).toBeInTheDocument()
  })

  it('shows loading spinner when signing in', () => {
    mockLoading = true
    render(
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    )
    expect(screen.getByText('Connecting...')).toBeInTheDocument()
  })
})
