/**
 * User-facing error messages mapped to backend error codes.
 *
 * Each entry provides:
 *  - title:       Short headline shown in error card
 *  - message:     Explanation the user sees
 *  - action:      Label for the primary action button
 *  - retryable:   Whether auto-retry / manual retry is appropriate
 */

export interface ErrorMessageConfig {
  title: string;
  message: string;
  action: string;
  retryable: boolean;
}

export const ERROR_MESSAGES: Record<string, ErrorMessageConfig> = {
  JD_INVALID: {
    title: 'Job description not recognised',
    message:
      'The job description could not be parsed. Please make sure you are pasting an actual job posting with role responsibilities, requirements, and relevant details.',
    action: 'Try a different job description',
    retryable: false,
  },
  AI_TIMEOUT: {
    title: 'AI took too long',
    message: 'Generation timed out. This is usually temporary and retrying often works.',
    action: 'Retry',
    retryable: true,
  },
  AI_QUOTA: {
    title: 'High demand right now',
    message: 'Our AI service is under high demand. Please wait a moment and try again.',
    action: 'Retry in 30 seconds',
    retryable: true,
  },
  PDF_FAILED: {
    title: 'PDF could not be generated',
    message:
      'Your resume is ready — we just could not create the PDF. Download as a Word document instead.',
    action: 'Download Word document',
    retryable: false,
  },
  PIPELINE_ERROR: {
    title: 'Generation failed',
    message: 'Something went wrong during generation. Please try again.',
    action: 'Retry',
    retryable: true,
  },
  PROFILE_INCOMPLETE: {
    title: 'Profile needs more information',
    message:
      'Your profile needs additional details (name, experience, or skills) before we can generate a complete resume.',
    action: 'Complete your profile',
    retryable: false,
  },
  AUTH_EXPIRED: {
    title: 'Session expired',
    message: 'Your session has expired. Please sign in again to continue.',
    action: 'Sign in',
    retryable: false,
  },
  RATE_LIMITED: {
    title: 'Too many requests',
    message: 'You have made too many requests. Please wait a moment and try again.',
    action: 'Try again',
    retryable: true,
  },
  NETWORK_ERROR: {
    title: 'Connection lost',
    message: 'Please check your internet connection and try again.',
    action: 'Retry',
    retryable: true,
  },
  UNKNOWN: {
    title: 'Something went wrong',
    message:
      'An unexpected error occurred. Our team has been notified. Please try again or come back later.',
    action: 'Try again',
    retryable: true,
  },
};

/**
 * Get the user-facing error message config for a given error code.
 * Falls back to UNKNOWN if the code is not recognised.
 */
export function getErrorMessage(code: string): ErrorMessageConfig {
  return ERROR_MESSAGES[code] || ERROR_MESSAGES.UNKNOWN;
}

/**
 * Extract the error code from any thrown value.
 * Handles ApiError, Error objects with code property, and plain strings.
 */
export function extractErrorCode(error: unknown): string {
  if (error && typeof error === 'object' && 'code' in error) {
    return (error as { code: string }).code;
  }
  if (error && typeof error === 'object' && 'status' in error) {
    const status = (error as { status: number }).status;
    if (status === 0) return 'NETWORK_ERROR';
    if (status === 401) return 'AUTH_EXPIRED';
    if (status === 429) return 'RATE_LIMITED';
  }
  return 'UNKNOWN';
}

/**
 * Check if the error indicates a condition that makes retrying useful.
 */
export function isRetryable(error: unknown): boolean {
  const code = extractErrorCode(error);
  return ERROR_MESSAGES[code]?.retryable ?? true;
}

/**
 * Check for offline state before making API calls.
 * Returns an ApiError-styled object if the browser reports offline.
 */
export function checkNetworkOnline(): { code: string; message: string } | null {
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    return {
      code: 'NETWORK_ERROR',
      message: 'No internet connection. Please check your connection and try again.',
    };
  }
  return null;
}
