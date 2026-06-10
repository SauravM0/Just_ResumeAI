import type { JDAnalyzeRequest, JDAnalyzeResponse } from '../types/jd';
import type { MasterProfile } from '../types/profile';
import type {
  ResumeRecommendRequest,
  ResumeRecommendResponse,
  ResumeRegenerateRequest,
  ResumeValidateRequest,
  ValidateResponse,
  ConfirmKeywordsRequest,
  ConfirmKeywordsResponse,
  FastResumeGenerateRequest,
  FastResumeGenerateResponse,
  PipelineGenerateRequest,
  PipelineGenerateResponse,
  ExportFileResponse,
  GenerationFilesResponse,
} from '../types/resume';
import { getApiBase } from './env';
import { useAuthStore } from '../store/useAuthStore';

const API_BASE = getApiBase();

// ── SSE Streaming Types ──────────────────────────────────────────────────

export interface SSEProgressEvent {
  event: string;
  data: Record<string, unknown>;
}

export type SSECallback = (event: SSEProgressEvent) => void;

export type GenerationLifecycleStatus = 'draft' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface GenerationStatusResponse {
  generation_id: string;
  status: GenerationLifecycleStatus;
  current_step?: string;
  progress_percentage?: number;
  message?: string;
  channel_available?: boolean;
  updated_at?: string | null;
}


// ── API Error Types & Error Codes ─────────────────────────────────────────

/** Well-known error codes the backend emits in SSE error events and HTTP error bodies. */
export const ErrorCode = {
  JD_INVALID: 'JD_INVALID',
  AI_TIMEOUT: 'AI_TIMEOUT',
  AI_QUOTA: 'AI_QUOTA',
  PDF_FAILED: 'PDF_FAILED',
  PIPELINE_ERROR: 'PIPELINE_ERROR',
  PROFILE_INCOMPLETE: 'PROFILE_INCOMPLETE',
  AUTH_EXPIRED: 'AUTH_EXPIRED',
  RATE_LIMITED: 'RATE_LIMITED',
  NETWORK_ERROR: 'NETWORK_ERROR',
  UNKNOWN: 'UNKNOWN',
} as const;

export type ErrorCodeType = (typeof ErrorCode)[keyof typeof ErrorCode];

/** HTTP status codes that are safe to retry automatically. */
const RETRYABLE_HTTP_CODES = new Set([429, 500, 502, 503, 504]);

export class ApiError extends Error {
  readonly code: ErrorCodeType;
  readonly status: number;
  readonly request_id?: string;
  readonly isAuthError: boolean;
  readonly isForbidden: boolean;
  readonly isNetworkError: boolean;
  readonly isTimeout: boolean;
  readonly retryable: boolean;

  constructor(message: string, status: number, code?: ErrorCodeType, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code ?? _httpStatusToErrorCode(status);
    this.request_id = requestId;
    this.isAuthError = status === 401;
    this.isForbidden = status === 403;
    this.isNetworkError = status === 0;
    this.isTimeout = status === 408;
    this.retryable = RETRYABLE_HTTP_CODES.has(status) || code === ErrorCode.AI_TIMEOUT;
  }

  /**
   * Create an ApiError from an HTTP response.
   * Respects backend error codes in {"error": "JD_INVALID", "message": "..."} format.
   */
  static fromResponse(status: number, body: BackendErrorBody, headerRequestId?: string | null): ApiError {
    const normalized = normalizeBackendError(body);
    const code = (normalized.code && Object.values(ErrorCode).includes(normalized.code as ErrorCodeType))
      ? (normalized.code as ErrorCodeType)
      : _httpStatusToErrorCode(status);
    const message = normalized.message ?? `Request failed with status ${status}`;
    const requestId = normalized.request_id ?? headerRequestId ?? undefined;
    return new ApiError(message, status, code, requestId);
  }
}

type BackendErrorBody = {
  error?: string | {
    code?: string;
    message?: string;
    request_id?: string;
  };
  message?: string;
  detail?: unknown;
};

function normalizeBackendError(body: BackendErrorBody): { code?: string; message?: string; request_id?: string } {
  if (body.error && typeof body.error === 'object') {
    return {
      code: body.error.code,
      message: body.error.message,
      request_id: body.error.request_id,
    };
  }

  if (typeof body.error === 'string') {
    return {
      code: body.error,
      message: body.message ?? formatDetail(body.detail) ?? body.error,
    };
  }

  return {
    message: body.message ?? formatDetail(body.detail),
  };
}

function formatDetail(detail: unknown): string | undefined {
  if (detail == null) return undefined;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') return item;
        const record = item && typeof item === 'object' ? item as { loc?: unknown; msg?: unknown } : {};
        const path = Array.isArray(record.loc) ? record.loc.join('.') : 'request';
        const message = record.msg || JSON.stringify(item);
        return `${path}: ${message}`;
      })
      .join('\n');
  }
  return JSON.stringify(detail);
}

function _httpStatusToErrorCode(status: number): ErrorCodeType {
  if (status === 0) return ErrorCode.NETWORK_ERROR;
  if (status === 401) return ErrorCode.AUTH_EXPIRED;
  if (status === 413) return ErrorCode.PIPELINE_ERROR;
  if (status === 422) return ErrorCode.PIPELINE_ERROR;
  if (status === 429) return ErrorCode.RATE_LIMITED;
  return ErrorCode.UNKNOWN;
}

function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError && error.message === 'Failed to fetch';
}

function filenameFromContentDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const utf8Match = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1].replace(/"/g, ''));
  const plainMatch = header.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1] ?? fallback;
}

function parseJsonHeader<T>(headers: Headers, name: string, fallback: T): T {
  try {
    return JSON.parse(headers.get(name) || '') as T;
  } catch {
    return fallback;
  }
}

function pageCountFromHeaders(headers: Headers): number | undefined {
  const value = Number(headers.get('x-pdf-page-count'));
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

function pdfExportMetadata(headers: Headers) {
  return {
    compile_warnings: parseJsonHeader<string[]>(headers, 'x-compile-warnings', []),
    inspection_warnings: parseJsonHeader<string[]>(headers, 'x-pdf-inspection-warnings', []),
    page_count: pageCountFromHeaders(headers),
    compressed: headers.get('x-resume-compressed') === 'true',
    compression_actions: parseJsonHeader<string[]>(headers, 'x-compression-actions', []),
  };
}

export function validationMetadata(headers: Headers) {
  return {
    validation_repaired: headers.get('x-validation-repaired') === 'true',
    validation_warnings: parseJsonHeader<string[]>(headers, 'x-validation-warnings', []),
  };
}

export async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  timeoutMs = 120000,
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const controller = new AbortController();
  const token = await useAuthStore.getState().getAccessToken();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  const externalSignal = options.signal;
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort();
    } else {
      externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
    }
  }
  try {
    const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
    const res = await fetch(url, {
      ...options,
      headers: {
        ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
        ...options.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: controller.signal,
    });

    if (!res.ok) {
      let body: BackendErrorBody = {};
      try {
        body = await res.json();
      } catch {
        // Response body wasn't JSON — use default
      }

      const apiError = ApiError.fromResponse(res.status, body, res.headers.get('x-request-id'));
      if (apiError.request_id) {
        console.error('[API] Request failed', {
          status: apiError.status,
          code: apiError.code,
          request_id: apiError.request_id,
        });
      }

      if (res.status === 401) {
        await useAuthStore.getState().signOut();
        if (window.location.pathname !== '/login') {
          window.location.assign('/login');
        }
        throw apiError;
      }

      if (res.status === 403) {
        if (window.location.pathname !== '/access-denied') {
          window.location.assign('/access-denied');
        }
        throw apiError;
      }

      throw apiError;
    }

    return res.json();
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      throw new ApiError('Request timed out. The backend did not finish in time.', 408, ErrorCode.AI_TIMEOUT);
    }
    if (isNetworkError(error)) {
      throw new ApiError(
        'Backend is not available. Check your internet connection or try again later.',
        0,
        ErrorCode.NETWORK_ERROR,
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function requestBlob(
  endpoint: string,
  options: RequestInit = {},
  timeoutMs = 120000,
): Promise<{ blob: Blob; filename: string; headers: Headers }> {
  const url = `${API_BASE}${endpoint}`;
  const controller = new AbortController();
  const token = await useAuthStore.getState().getAccessToken();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        ...options.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: controller.signal,
    });

    if (!res.ok) {
      let body: BackendErrorBody = {};
      try {
        body = await res.json();
      } catch {
        // Response body wasn't JSON — use default
      }

      const apiError = ApiError.fromResponse(res.status, body, res.headers.get('x-request-id'));
      if (apiError.request_id) {
        console.error('[API] Blob request failed', {
          status: apiError.status,
          code: apiError.code,
          request_id: apiError.request_id,
        });
      }

      if (res.status === 401) {
        await useAuthStore.getState().signOut();
        if (window.location.pathname !== '/login') {
          window.location.assign('/login');
        }
        throw apiError;
      }

      if (res.status === 403) {
        if (window.location.pathname !== '/access-denied') {
          window.location.assign('/access-denied');
        }
        throw apiError;
      }

      throw apiError;
    }

    return {
      blob: await res.blob(),
      filename: filenameFromContentDisposition(res.headers.get('content-disposition'), 'resume'),
      headers: res.headers,
    };
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      throw new ApiError('Request timed out. The backend did not finish in time.', 408, ErrorCode.AI_TIMEOUT);
    }
    if (isNetworkError(error)) {
      throw new ApiError(
        'Backend is not available. Check your internet connection or try again later.',
        0,
        ErrorCode.NETWORK_ERROR,
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export async function healthCheck(): Promise<{ status: string }> {
  return request('/health');
}

export async function analyzeJD(data: JDAnalyzeRequest): Promise<JDAnalyzeResponse> {
  return request('/jd/analyze', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function generateResumePipeline(data: PipelineGenerateRequest): Promise<PipelineGenerateResponse> {
  return request('/pipeline/generate/optimized', {
    method: 'POST',
    body: JSON.stringify(data),
  }, 180000);
}

// ── SSE Streaming ──────────────────────────────────────────────────────────

/**
 * Start a resume generation and get a generation_id immediately.
 * The actual generation runs in a background task.
 * Connect to startGenerationStream() for progress events.
 */
export async function startGeneration(
  data: PipelineGenerateRequest,
): Promise<{ generation_id: string; status: GenerationLifecycleStatus }> {
  return request('/pipeline/generate/start', {
    method: 'POST',
    body: JSON.stringify({
      target_ats_score: 90,
      max_repair_attempts: 3,
      ...data,  // User values override defaults
    }),
  }, 30000); // Supabase/auth latency can make startup slower than the background work handoff.
}

/**
 * Open an SSE connection to stream generation progress events.
 * Uses @microsoft/fetch-event-source for auth header support.
 *
 * Events emitted by the backend:
 *   started, jd_parsing, jd_parsed, scoring_original, original_scored,
 *   building_evidence, composing, repair_pass, pdf_compile, complete, error
 */
export async function connectGenerationStream(
  generationId: string,
  onEvent: SSECallback,
  onComplete?: () => void,
  onError?: (error: Error) => void,
): Promise<() => void> {
  const { fetchEventSource } = await import('@microsoft/fetch-event-source');
  const token = await useAuthStore.getState().getAccessToken();
  const abortController = new AbortController();

  const stream = fetchEventSource(`${API_BASE}/pipeline/generate/${generationId}/stream`, {
    method: 'GET',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    signal: abortController.signal,

    onopen: async (response) => {
      if (!response.ok) {
        throw new ApiError(
          `SSE connection failed: ${response.status}`,
          response.status,
          undefined,
          response.headers.get('x-request-id') ?? undefined,
        );
      }
    },

    onmessage: (event) => {
      try {
        const parsed = event.data ? JSON.parse(event.data) : {};
        onEvent({ event: event.event, data: parsed });

        if (event.event === 'complete' || event.event === 'error') {
          abortController.abort();
        }
      } catch (err) {
        console.error('[SSE] Failed to parse event:', err);
      }
    },

    onerror: (error) => {
      console.error('[SSE] Connection error:', error);
      // Don't abort — allow reconnect
      abortController.abort();
      onError?.(error instanceof Error ? error : new Error(String(error)));
      throw error;
    },
  });

  stream.catch((error) => {
    if (!abortController.signal.aborted) {
      onError?.(error instanceof Error ? error : new Error(String(error)));
    }
  });

  stream.then(() => {
    if (!abortController.signal.aborted) {
      onComplete?.();
    }
  });

  // Return a cleanup function
  return () => {
    abortController.abort();
  };
}

/**
 * Fetch the full generation result after SSE streaming completes.
 */
export async function getGenerationResult(generationId: string): Promise<any | GenerationStatusResponse> {
  return request(`/pipeline/generate/${generationId}/result`, { method: 'GET' }, 5000);
}

export async function getGeneration(generationId: string): Promise<any> {
  return request(`/generations/${generationId}`, { method: 'GET' });
}

/**
 * Build the PDF download URL for direct linking.
 * The backend handles auth via the Bearer token header — this is a convenience
 * for elements that need a direct URL (e.g. <iframe>, window.open).
 */
export function getPdfDownloadUrl(generationId: string): string {
  return `${API_BASE}/resume/${generationId}/download/pdf`;
}

/**
 * Build the DOCX download URL for direct linking.
 */
export function getDocxDownloadUrl(generationId: string): string {
  return `${API_BASE}/resume/${generationId}/download/docx`;
}

export async function recommendResume(data: ResumeRecommendRequest): Promise<ResumeRecommendResponse> {
  return request('/resume/recommend', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function regenerateResume(data: ResumeRegenerateRequest): Promise<ResumeRecommendResponse> {
  return request('/resume/regenerate', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function validateResume(data: ResumeValidateRequest): Promise<ValidateResponse> {
  return request('/resume/validate', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function confirmResumeKeywords(
  generationId: string,
  data: ConfirmKeywordsRequest,
): Promise<ConfirmKeywordsResponse> {
  return request(`/resume/${generationId}/confirm-keywords`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function generateFastResume(data: FastResumeGenerateRequest): Promise<FastResumeGenerateResponse> {
  return request('/resume/fast-generate', {
    method: 'POST',
    body: JSON.stringify(data),
  }, 120000);
}

export interface CoverLetterGenerateRequest {
  profile: MasterProfile;
  job_title?: string;
  tone?: string;
  additional_context?: string;
}

export interface CoverLetterResponse {
  generation_id: string;
  cover_letter_text: string;
  word_count: number;
  warnings: string[];
}

export async function generateCoverLetter(
  generationId: string,
  data: CoverLetterGenerateRequest,
): Promise<CoverLetterResponse> {
  return request(`/cover-letter/${generationId}/generate`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getCoverLetter(generationId: string): Promise<CoverLetterResponse> {
  return request(`/cover-letter/${generationId}`, { method: 'GET' });
}

export async function updateCoverLetter(
  generationId: string,
  coverLetterText: string,
): Promise<CoverLetterResponse> {
  return request(`/cover-letter/${generationId}`, {
    method: 'PUT',
    body: JSON.stringify({ cover_letter_text: coverLetterText }),
  });
}

export async function exportPdf(generationId: string): Promise<ExportFileResponse> {
  const response = await requestBlob(`/resume/${generationId}/export/pdf`, { method: 'POST' }, 180000);
  
  const isDocxFallback = response.headers.get('x-pdf-failed') === 'true';
  const file_type = isDocxFallback ? 'docx' : 'pdf';
  const extension = isDocxFallback ? '.docx' : '.pdf';
  const fallbackName = `resume${extension}`;
  
  return {
    blob: response.blob,
    filename: response.filename.endsWith(extension) ? response.filename : fallbackName,
    file_type: file_type,
    ...pdfExportMetadata(response.headers),
    ...validationMetadata(response.headers),
    regenerated: response.headers.get('x-regenerated') === 'true',
  };
}

export async function exportDocx(generationId: string): Promise<ExportFileResponse> {
  const response = await requestBlob(`/resume/${generationId}/export/docx`, { method: 'POST' }, 180000);
  return {
    blob: response.blob,
    filename: response.filename.endsWith('.docx') ? response.filename : 'resume.docx',
    file_type: 'docx',
    ...validationMetadata(response.headers),
    regenerated: response.headers.get('x-regenerated') === 'true',
  };
}

export async function getGenerationFiles(generationId: string): Promise<GenerationFilesResponse> {
  return request(`/resume/${generationId}/files`, { method: 'GET' });
}

export async function regenerateExportFile(
  generationId: string,
  fileType: 'pdf' | 'docx',
): Promise<ExportFileResponse> {
  const response = await requestBlob(`/resume/${generationId}/files/${fileType}/regenerate`, { method: 'POST' }, 180000);
  
  const isDocxFallback = response.headers.get('x-pdf-failed') === 'true';
  const finalFileType = fileType === 'pdf' && isDocxFallback ? 'docx' : fileType;
  const extension = `.${finalFileType}`;

  return {
    blob: response.blob,
    filename: response.filename.endsWith(extension) ? response.filename : `resume${extension}`,
    file_type: finalFileType,
    ...(fileType === 'pdf' ? pdfExportMetadata(response.headers) : {}),
    ...validationMetadata(response.headers),
    regenerated: response.headers.get('x-regenerated') === 'true',
  };
}
