import type { JDAnalyzeRequest, JDAnalyzeResponse } from '../types/jd';
import type { MasterProfile } from '../types/profile';
import type {
  ResumeRecommendRequest,
  ResumeRecommendResponse,
  ResumeRegenerateRequest,
  ResumeValidateRequest,
  ValidateResponse,
  PipelineGenerateRequest,
  PipelineGenerateResponse,
  ExportFileResponse,
  GenerationFilesResponse,
} from '../types/resume';
import { getApiBase } from './env';
import { useAuthStore } from '../store/useAuthStore';

const API_BASE = getApiBase();

export class ApiError extends Error {
  readonly status: number;
  readonly isAuthError: boolean;
  readonly isForbidden: boolean;
  readonly isNetworkError: boolean;
  readonly isTimeout: boolean;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.isAuthError = status === 401;
    this.isForbidden = status === 403;
    this.isNetworkError = status === 0;
    this.isTimeout = status === 408;
  }
}

function formatApiErrorMessage(body: string): string {
  try {
    const json = JSON.parse(body);
    const detail = json.detail ?? json.message ?? json;

    if (typeof detail === 'string') return detail;

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
    const res = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: controller.signal,
    });

    if (!res.ok) {
      const body = await res.text();
      const message = formatApiErrorMessage(body);

      if (res.status === 401) {
        await useAuthStore.getState().signOut();
        if (window.location.pathname !== '/login') {
          window.location.assign('/login');
        }
        throw new ApiError(message, 401);
      }

      if (res.status === 403) {
        if (window.location.pathname !== '/access-denied') {
          window.location.assign('/access-denied');
        }
        throw new ApiError(message, 403);
      }

      throw new ApiError(message, res.status);
    }

    return res.json();
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      throw new ApiError('Request timed out. The backend did not finish in time.', 408);
    }
    if (isNetworkError(error)) {
      throw new ApiError(
        'Backend is not available. Check your internet connection or try again later.',
        0,
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
      const body = await res.text();
      const message = formatApiErrorMessage(body);

      if (res.status === 401) {
        await useAuthStore.getState().signOut();
        if (window.location.pathname !== '/login') {
          window.location.assign('/login');
        }
        throw new ApiError(message, 401);
      }

      if (res.status === 403) {
        if (window.location.pathname !== '/access-denied') {
          window.location.assign('/access-denied');
        }
        throw new ApiError(message, 403);
      }

      throw new ApiError(message, res.status);
    }

    return {
      blob: await res.blob(),
      filename: filenameFromContentDisposition(res.headers.get('content-disposition'), 'resume'),
      headers: res.headers,
    };
  } catch (error) {
    if ((error as Error).name === 'AbortError') {
      throw new ApiError('Request timed out. The backend did not finish in time.', 408);
    }
    if (isNetworkError(error)) {
      throw new ApiError(
        'Backend is not available. Check your internet connection or try again later.',
        0,
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
  return request('/pipeline/generate', {
    method: 'POST',
    body: JSON.stringify(data),
  }, 180000);
}

export async function getGeneration(generationId: string): Promise<any> {
  return request(`/generations/${generationId}`, { method: 'GET' });
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
  return {
    blob: response.blob,
    filename: response.filename.endsWith('.pdf') ? response.filename : 'resume.pdf',
    file_type: 'pdf',
    compile_warnings: JSON.parse(response.headers.get('x-compile-warnings') || '[]'),
    regenerated: response.headers.get('x-regenerated') === 'true',
  };
}

export async function exportDocx(generationId: string): Promise<ExportFileResponse> {
  const response = await requestBlob(`/resume/${generationId}/export/docx`, { method: 'POST' }, 180000);
  return {
    blob: response.blob,
    filename: response.filename.endsWith('.docx') ? response.filename : 'resume.docx',
    file_type: 'docx',
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
  return {
    blob: response.blob,
    filename: response.filename.endsWith(`.${fileType}`) ? response.filename : `resume.${fileType}`,
    file_type: fileType,
    compile_warnings: fileType === 'pdf' ? JSON.parse(response.headers.get('x-compile-warnings') || '[]') : undefined,
    regenerated: response.headers.get('x-regenerated') === 'true',
  };
}
