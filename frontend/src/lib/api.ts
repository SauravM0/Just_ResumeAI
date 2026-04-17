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
} from '../types/resume';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000/api/v1';

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
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const body = await res.text();
    const message = formatApiErrorMessage(body);
    throw new ApiError(message, res.status);
  }

  return res.json();
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
    body: JSON.stringify(data),
  });
}

// ─── Cover Letter ───────────────────────────────────────────────────────────

export interface CoverLetterRequest {
  session_id: string;
  profile: MasterProfile;
  parsed_jd: ParsedJD;
  recommendation: ResumeRecommendation;
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
