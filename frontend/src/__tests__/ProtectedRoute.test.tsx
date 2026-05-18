import { describe, it, expect, vi, beforeEach } from 'vitest'

let mockSession: any = null
let mockLoading = false
let mockInitialized = true

vi.mock('../store/useAuthStore', () => ({
  useAuthStore: (selector: any) => {
    const state = {
      session: mockSession,
      loading: mockLoading,
      initialized: mockInitialized,
    }
    return selector ? selector(state) : state
  },
}))

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import ProtectedRoute from '../components/ProtectedRoute'

describe('ProtectedRoute', () => {
  beforeEach(() => {
    mockSession = null
    mockLoading = false
    mockInitialized = true
  })

  it('redirects to /login when no session', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/login" element={<div>Login Page</div>} />
          <Route path="/dashboard" element={
            <ProtectedRoute>
              <div>Dashboard Content</div>
            </ProtectedRoute>
          } />
        </Routes>
      </MemoryRouter>
    )
    expect(screen.getByText('Login Page')).toBeInTheDocument()
    expect(screen.queryByText('Dashboard Content')).not.toBeInTheDocument()
  })

  it('renders children when authenticated', () => {
    mockSession = { user: { id: 'test-user' } }
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/login" element={<div>Login Page</div>} />
          <Route path="/dashboard" element={
            <ProtectedRoute>
              <div>Dashboard Content</div>
            </ProtectedRoute>
          } />
        </Routes>
      </MemoryRouter>
    )
    expect(screen.getByText('Dashboard Content')).toBeInTheDocument()
  })

  it('shows loading screen while initializing', () => {
    mockLoading = true
    mockInitialized = false
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/login" element={<div>Login Page</div>} />
          <Route path="/dashboard" element={
            <ProtectedRoute>
              <div>Dashboard Content</div>
            </ProtectedRoute>
          } />
        </Routes>
      </MemoryRouter>
    )
    expect(screen.getByText('Preparing your workspace...')).toBeInTheDocument()
    expect(screen.queryByText('Login Page')).not.toBeInTheDocument()
    expect(screen.queryByText('Dashboard Content')).not.toBeInTheDocument()
  })
})
