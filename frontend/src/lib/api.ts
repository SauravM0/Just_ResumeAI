/**
 * API service layer — typed HTTP client for all backend endpoints.
 */

import type { JDAnalyzeRequest, JDAnalyzeResponse, ParsedJD } from '../types/jd';
import type { MasterProfile } from '../types/profile';
import type {
  ResumeRecommendation,
  ResumeRecommendRequest,
  ResumeRecommendResponse,
  ResumeRegenerateRequest,
  ResumeValidateRequest,
  ValidateResponse,
  RenderLatexRequest,
  RenderLatexResponse,
  RenderPdfRequest,
  RenderPdfResponse,
  ApproveGeneratePdfRequest,
  ApproveGeneratePdfResponse,
  PipelineGenerateRequest,
  PipelineGenerateResponse,
} from '../types/resume';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api/v1';
const CLIENT_USER_ID_KEY = 'just-resume-client-user-id';

function getClientUserId(): string {
  const existing = localStorage.getItem(CLIENT_USER_ID_KEY);
  if (existing) return existing;

  const generated =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  localStorage.setItem(CLIENT_USER_ID_KEY, generated);
  return generated;
}

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

function formatApiErrorMessage(body: string): string {
  try {
    const json = JSON.parse(body);
    const detail = json.detail ?? json.message ?? json;

    if (typeof detail === 'string') {
      return detail;
    }

    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === 'string') return item;
          const path = Array.isArray(item?.loc) ? item.loc.join('.') : 'request';
          const message = item?.msg || JSON.stringify(item);
          return `${path}: ${message}`;
        })
        .join('\n');
    }

    return JSON.stringify(detail);
  } catch {
    return body;
  }
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {},
  timeoutMs = 120000,
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const controller = new AbortController();
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
    const res = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        'X-Client-User-Id': getClientUserId(),
        ...options.headers,
      },
      ...options,
      signal: controller.signal,
    });

    if (!res.ok) {
      const body = await res.text();
      const message = formatApiErrorMessage(body);
      throw new ApiError(message, res.status);
    }

    return res.json();
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      throw new ApiError('Request timed out. The backend did not finish in time.', 408);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

// ─── Health ─────────────────────────────────────────────────────────────────

export async function healthCheck(): Promise<{ status: string }> {
  return request('/health');
}

// ─── JD Analysis ────────────────────────────────────────────────────────────

export async function analyzeJD(data: JDAnalyzeRequest): Promise<JDAnalyzeResponse> {
  return request('/jd/analyze', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function generateResumePipeline(data: PipelineGenerateRequest): Promise<PipelineGenerateResponse> {
  return request('/pipeline/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  }, 180000);
}

// ─── Resume ─────────────────────────────────────────────────────────────────

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

export async function renderLatex(data: RenderLatexRequest): Promise<RenderLatexResponse> {
  return request('/resume/render-latex', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function renderPdf(data: RenderPdfRequest): Promise<RenderPdfResponse> {
  return request('/resume/render-pdf', {
    method: 'POST',
    body: JSON.stringify({ session_id: data.session_id }),
  });
}

export async function approveGeneratePdf(
  data: ApproveGeneratePdfRequest,
): Promise<ApproveGeneratePdfResponse> {
  return request('/resume/approve-generate-pdf', {
    method: 'POST',
    body: JSON.stringify(data),
  }, 180000);
}

// ─── Cover Letter ───────────────────────────────────────────────────────────

export interface CoverLetterRequest {
  session_id: string;
  profile: MasterProfile;
  parsed_jd: ParsedJD;
  recommendation: ResumeRecommendation;
  job_title?: string;
  tone?: string;
  additional_context?: string;
}

export interface CoverLetterResponse {
  session_id: string;
  cover_letter_text: string;
  word_count: number;
  warnings: string[];
}

export async function generateCoverLetter(data: CoverLetterRequest): Promise<CoverLetterResponse> {
  return request('/cover-letter/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}
