import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, ErrorCode, requestBlob } from '../lib/api'

const authStoreMocks = vi.hoisted(() => ({
  getAccessToken: vi.fn(),
}))

vi.mock('../store/useAuthStore', () => ({
  useAuthStore: {
    getState: () => ({
      getAccessToken: authStoreMocks.getAccessToken,
      signOut: vi.fn(),
    }),
  },
}))

describe('ApiError', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    authStoreMocks.getAccessToken.mockReset()
  })

  it('uses backend error codes and messages when present', () => {
    const error = ApiError.fromResponse(422, {
      error: ErrorCode.JD_INVALID,
      message: 'Paste a real job description.',
    })

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe(ErrorCode.JD_INVALID)
    expect(error.message).toBe('Paste a real job description.')
    expect(error.status).toBe(422)
    expect(error.retryable).toBe(false)
  })

  it('maps retryable HTTP responses to stable error codes', () => {
    const rateLimited = ApiError.fromResponse(429, { message: 'Slow down' })
    const serverError = ApiError.fromResponse(503, {})

    expect(rateLimited.code).toBe(ErrorCode.RATE_LIMITED)
    expect(rateLimited.retryable).toBe(true)
    expect(serverError.code).toBe(ErrorCode.UNKNOWN)
    expect(serverError.retryable).toBe(true)
  })

  it('marks auth, network, and timeout errors with convenience flags', () => {
    expect(new ApiError('auth', 401).isAuthError).toBe(true)
    expect(new ApiError('network', 0).isNetworkError).toBe(true)
    expect(new ApiError('timeout', 408, ErrorCode.AI_TIMEOUT)).toMatchObject({
      isTimeout: true,
      retryable: true,
      code: ErrorCode.AI_TIMEOUT,
    })
  })

  it('parses standard backend error shape with request id', () => {
    const error = ApiError.fromResponse(503, {
      error: {
        code: ErrorCode.PIPELINE_ERROR,
        message: 'Generation failed safely.',
        request_id: 'req-body-123',
      },
    }, 'req-header-456')

    expect(error.code).toBe(ErrorCode.PIPELINE_ERROR)
    expect(error.message).toBe('Generation failed safely.')
    expect(error.request_id).toBe('req-body-123')
    expect(error.retryable).toBe(true)
  })

  it('preserves exported blob filename from content-disposition header', async () => {
    authStoreMocks.getAccessToken.mockResolvedValue('token-123')
    const blob = new Blob(['file'], { type: 'application/pdf' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({
        'content-disposition': 'attachment; filename="tailored-resume.pdf"',
      }),
      blob: async () => blob,
    }))

    const result = await requestBlob('/resume/gen-1/export/pdf', { method: 'POST' })

    expect(result.blob).toBe(blob)
    expect(result.filename).toBe('tailored-resume.pdf')
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/resume/gen-1/export/pdf'),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer token-123' }),
      }),
    )
  })
})
