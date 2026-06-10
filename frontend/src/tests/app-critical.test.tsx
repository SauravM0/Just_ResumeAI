import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../App'
import { useAuthStore } from '../store/useAuthStore'

function setAuthState(state: Partial<ReturnType<typeof useAuthStore.getState>>) {
  useAuthStore.setState({
    session: null,
    user: null,
    loading: false,
    error: null,
    initialized: true,
    ...state,
  })
}

describe('critical app routes', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/')
    setAuthState({})
  })

  it('renders the app without crashing while auth initializes', () => {
    setAuthState({ initialized: false, loading: true })

    render(<App />)

    expect(screen.getByRole('heading', { name: /just resume/i })).toBeInTheDocument()
    expect(screen.getByText(/loading your workspace/i)).toBeInTheDocument()
  })

  it('renders the login route', () => {
    window.history.pushState({}, '', '/login')

    render(<App />)

    expect(screen.getByRole('heading', { name: /justresume ai/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument()
  })

  it('redirects unauthenticated protected routes to login', async () => {
    window.history.pushState({}, '', '/dashboard')

    render(<App />)

    await waitFor(() => expect(window.location.pathname).toBe('/login'))
    expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument()
  })
})
