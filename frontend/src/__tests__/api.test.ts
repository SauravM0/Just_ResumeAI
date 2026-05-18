import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ApiError } from '../lib/api';

const mockGetAccessToken = vi.fn();
const mockSignOut = vi.fn();
const originalLocation = window.location;

vi.mock('../store/useAuthStore', () => ({
  useAuthStore: {
    getState: () => ({
      getAccessToken: mockGetAccessToken,
      signOut: mockSignOut,
    }),
  },
}));

vi.mock('../lib/env', () => ({
  getApiBase: () => 'http://localhost:8000/api/v1',
}));

let mockWindowLocation: any;

beforeEach(() => {
  vi.clearAllMocks();
  mockGetAccessToken.mockResolvedValue(null);

  mockWindowLocation = {
    pathname: '/dashboard',
    assign: vi.fn(),
    href: '',
  };
  Object.defineProperty(window, 'location', {
    value: mockWindowLocation,
    writable: true,
  });
});

afterEach(() => {
  Object.defineProperty(window, 'location', {
    value: originalLocation,
    writable: true,
  });
});

async function importRequest() {
  const mod = await import('../lib/api');
  return mod.request;
}

describe('API request helper', () => {
  it('sends Authorization header when token exists', async () => {
    mockGetAccessToken.mockResolvedValue('test-token-123');
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: 'ok' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    const request = await importRequest();
    await request('/health');

    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/health',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer test-token-123',
        }),
      }),
    );
  });

  it('does not send Authorization header when no token', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: 'ok' }),
    });
    vi.stubGlobal('fetch', mockFetch);

    const request = await importRequest();
    await request('/health');

    const callArgs = mockFetch.mock.calls[0];
    const headers = (callArgs[1] as any).headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  it('throws ApiError on 500 response', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      text: () => Promise.resolve('Server error'),
    });
    vi.stubGlobal('fetch', mockFetch);

    const request = await importRequest();
    let error: any;
    try {
      await request('/health');
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
    expect(error.isAuthError).toBe(false);
    expect(error.isForbidden).toBe(false);
    expect(error.isNetworkError).toBe(false);
    expect(error.isTimeout).toBe(false);
    expect(error.message).toBe('Server error');
  });

  it('throws ApiError with parsed detail from response body', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
      text: () => Promise.resolve(JSON.stringify({ detail: 'Validation failed' })),
    });
    vi.stubGlobal('fetch', mockFetch);

    const request = await importRequest();
    await expect(request('/health')).rejects.toThrow('Validation failed');
  });

  it('throws timeout error when request exceeds timeout', async () => {
    const abortError = new Error('The operation was aborted');
    abortError.name = 'AbortError';
    const mockFetch = vi.fn().mockRejectedValue(abortError);
    vi.stubGlobal('fetch', mockFetch);

    const request = await importRequest();
    let error: any;
    try {
      await request('/health');
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(408);
    expect(error.isTimeout).toBe(true);
    expect(error.message).toContain('timed out');
  });

  it('returns ApiError.isNetworkError for fetch TypeError', async () => {
    const networkError = new TypeError('Failed to fetch');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(networkError));

    const request = await importRequest();
    let error: any;
    try {
      await request('/health');
    } catch (e) {
      error = e;
    }
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.isNetworkError).toBe(true);
    expect(error.message).toContain('Backend is not available');
  });
});

describe('401 handling', () => {
  it('signs out and redirects to login on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: () => Promise.resolve('Unauthorized'),
    }));

    const request = await importRequest();
    let error: any;
    try {
      await request('/health');
    } catch (e) {
      error = e;
    }

    expect(mockSignOut).toHaveBeenCalled();
    expect(mockWindowLocation.assign).toHaveBeenCalledWith('/login');
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(401);
    expect(error.isAuthError).toBe(true);
  });
});

describe('403 handling', () => {
  it('redirects to access-denied on 403', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      text: () => Promise.resolve('Forbidden'),
    }));

    const request = await importRequest();
    let error: any;
    try {
      await request('/health');
    } catch (e) {
      error = e;
    }

    expect(mockWindowLocation.assign).toHaveBeenCalledWith('/access-denied');
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(403);
    expect(error.isForbidden).toBe(true);
  });

  it('does not sign out on 403', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      text: () => Promise.resolve('Forbidden'),
    }));

    const request = await importRequest();
    try {
      await request('/health');
    } catch (e) {}

    expect(mockSignOut).not.toHaveBeenCalled();
  });

  it('does not redirect to /access-denied if already there', async () => {
    mockWindowLocation.pathname = '/access-denied';
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      text: () => Promise.resolve('Forbidden'),
    }));

    const request = await importRequest();
    let error: any;
    try {
      await request('/health');
    } catch (e) {
      error = e;
    }

    expect(mockWindowLocation.assign).not.toHaveBeenCalledWith('/access-denied');
    expect(error.status).toBe(403);
  });
});

describe('ApiError class', () => {
  it('sets isAuthError for 401', () => {
    const err = new ApiError('Unauthorized', 401);
    expect(err.isAuthError).toBe(true);
    expect(err.isForbidden).toBe(false);
    expect(err.isNetworkError).toBe(false);
    expect(err.isTimeout).toBe(false);
  });

  it('sets isForbidden for 403', () => {
    const err = new ApiError('Forbidden', 403);
    expect(err.isForbidden).toBe(true);
    expect(err.isAuthError).toBe(false);
  });

  it('sets isNetworkError for status 0', () => {
    const err = new ApiError('Network error', 0);
    expect(err.isNetworkError).toBe(true);
  });

  it('sets isTimeout for status 408', () => {
    const err = new ApiError('Timeout', 408);
    expect(err.isTimeout).toBe(true);
  });
});
