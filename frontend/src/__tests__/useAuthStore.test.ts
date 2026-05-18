import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockGetSession = vi.fn();
const mockOnAuthStateChange = vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } }));
const mockExchangeCodeForSession = vi.fn();
const mockSignInWithOAuth = vi.fn();
const mockSignOut = vi.fn();
const mockRefreshSession = vi.fn();

vi.mock('../lib/supabase', () => ({
  getSupabaseClient: () => ({
    auth: {
      getSession: mockGetSession,
      onAuthStateChange: mockOnAuthStateChange,
      exchangeCodeForSession: mockExchangeCodeForSession,
      signInWithOAuth: mockSignInWithOAuth,
      signOut: mockSignOut,
      refreshSession: mockRefreshSession,
    },
  }),
}));

const originalLocation = window.location;

beforeEach(() => {
  vi.clearAllMocks();
  vi.resetModules();
  Object.defineProperty(window, 'location', {
    value: { ...originalLocation, search: '', pathname: '/dashboard' },
    writable: true,
  });
});

describe('useAuthStore', () => {
  it('initialize gets session and sets listener', async () => {
    mockGetSession.mockResolvedValue({
      data: { session: { access_token: 'tok', user: { id: 'u1' }, expires_at: 9999999999 } },
      error: null,
    });

    const { useAuthStore } = await import('../store/useAuthStore');
    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.initialized).toBe(true);
    expect(state.loading).toBe(false);
    expect(state.user?.id).toBe('u1');
    expect(mockOnAuthStateChange).toHaveBeenCalled();
  });

  it('initialize sets error on failure', async () => {
    mockGetSession.mockRejectedValue(new Error('Network error'));

    const { useAuthStore } = await import('../store/useAuthStore');
    await useAuthStore.getState().initialize();

    const state = useAuthStore.getState();
    expect(state.initialized).toBe(true);
    expect(state.loading).toBe(false);
    expect(state.error).toBeTruthy();
    expect(state.session).toBeNull();
  });

  it('getAccessToken returns existing token if not expired', async () => {
    const futureExpiry = Math.floor(Date.now() / 1000) + 3600;
    const { useAuthStore } = await import('../store/useAuthStore');
    useAuthStore.setState({
      session: { access_token: 'valid-token', expires_at: futureExpiry } as any,
    });

    const token = await useAuthStore.getState().getAccessToken();
    expect(token).toBe('valid-token');
    expect(mockGetSession).not.toHaveBeenCalled();
  });

  it('getAccessToken refreshes session when token is expired', async () => {
    const pastExpiry = Math.floor(Date.now() / 1000) - 60;
    const { useAuthStore } = await import('../store/useAuthStore');
    useAuthStore.setState({
      session: { access_token: 'expired-token', expires_at: pastExpiry, refresh_token: 'rt' } as any,
    });

    mockGetSession.mockResolvedValue({
      data: { session: { access_token: 'expired-token', expires_at: pastExpiry } },
      error: null,
    });

    mockRefreshSession.mockResolvedValue({
      data: { session: { access_token: 'refreshed-token', expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: 'u1' } } },
      error: null,
    });

    const token = await useAuthStore.getState().getAccessToken();
    expect(token).toBe('refreshed-token');
    expect(mockRefreshSession).toHaveBeenCalled();
  });

  it('getAccessToken returns null on refresh failure', async () => {
    const pastExpiry = Math.floor(Date.now() / 1000) - 60;
    const { useAuthStore } = await import('../store/useAuthStore');
    useAuthStore.setState({
      session: { access_token: 'expired-token', expires_at: pastExpiry, refresh_token: 'rt' } as any,
    });

    mockGetSession.mockResolvedValue({
      data: { session: { access_token: 'expired-token', expires_at: pastExpiry } },
      error: null,
    });

    mockRefreshSession.mockRejectedValue(new Error('Refresh failed'));

    const token = await useAuthStore.getState().getAccessToken();
    expect(token).toBeNull();
  });

  it('signOut clears session and calls supabase signOut', async () => {
    mockSignOut.mockResolvedValue({ error: null });

    const { useAuthStore } = await import('../store/useAuthStore');
    useAuthStore.setState({
      session: { access_token: 'tok' } as any,
      user: { id: 'u1' } as any,
    });

    await useAuthStore.getState().signOut();
    expect(mockSignOut).toHaveBeenCalled();
    const state = useAuthStore.getState();
    expect(state.session).toBeNull();
    expect(state.user).toBeNull();
  });

  it('clearError sets error to null', async () => {
    const { useAuthStore } = await import('../store/useAuthStore');
    useAuthStore.setState({ error: 'Some error' });
    useAuthStore.getState().clearError();
    expect(useAuthStore.getState().error).toBeNull();
  });
});
