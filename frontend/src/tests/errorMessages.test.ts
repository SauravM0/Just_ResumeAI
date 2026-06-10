import { describe, expect, it, vi } from 'vitest'
import {
  checkNetworkOnline,
  extractErrorCode,
  getErrorMessage,
  isRetryable,
} from '../lib/errorMessages'

describe('errorMessages', () => {
  it('returns configured user-facing messages for known backend codes', () => {
    expect(getErrorMessage('JD_INVALID')).toMatchObject({
      title: 'Job description not recognised',
      action: 'Try a different job description',
      retryable: false,
    })
    expect(getErrorMessage('AI_TIMEOUT')).toMatchObject({
      action: 'Retry',
      retryable: true,
    })
    expect(getErrorMessage('PDF_FAILED')).toMatchObject({
      action: 'Download Word document',
      retryable: false,
    })
  })

  it('falls back to UNKNOWN for unrecognised codes', () => {
    expect(getErrorMessage('NOPE')).toEqual(getErrorMessage('UNKNOWN'))
  })

  it('extracts retry-relevant codes from common error shapes', () => {
    expect(extractErrorCode({ code: 'AI_TIMEOUT' })).toBe('AI_TIMEOUT')
    expect(extractErrorCode({ status: 401 })).toBe('AUTH_EXPIRED')
    expect(extractErrorCode({ status: 429 })).toBe('RATE_LIMITED')
    expect(extractErrorCode(new Error('boom'))).toBe('UNKNOWN')

    expect(isRetryable({ code: 'AI_TIMEOUT' })).toBe(true)
    expect(isRetryable({ code: 'AUTH_EXPIRED' })).toBe(false)
  })

  it('reports offline browser state before API calls', () => {
    vi.stubGlobal('navigator', { onLine: false })

    expect(checkNetworkOnline()).toEqual({
      code: 'NETWORK_ERROR',
      message: 'No internet connection. Please check your connection and try again.',
    })

    vi.stubGlobal('navigator', { onLine: true })
    expect(checkNetworkOnline()).toBeNull()
  })
})
