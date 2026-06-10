/**
 * History API service layer.
 */

import { request } from './api';

export interface FileExpiryInfo {
  has_files: boolean;
  pdf_available: boolean;
  docx_available: boolean;
  expires_at: string | null;
  earliest_expiry: string | null;
  is_expired: boolean;
  regenerate_available: boolean;
  files: Array<{
    file_type: string;
    expires_at: string | null;
    is_expired: boolean;
  }>;
}

export interface HistoryItem {
  generation_id: string;
  job_title: string | null;
  company: string | null;
  created_at: string | null;
  updated_at: string | null;
  status: string;
  ats_score_summary: {
    overall_score: number | null;
    keyword_coverage: number | null;
  };
  has_pdf: boolean;
  has_cover_letter: boolean;
  file_expiry_info: FileExpiryInfo;
}

export interface HistoryDetail {
  generation_id: string;
  job_title: string | null;
  company: string | null;
  raw_jd_text: string;
  parsed_jd_json: any;
  resume_json: any;
  ats_score_json: any;
  alignment_report_json: any;
  ats_pre_check_json: any;
  recruiter_review_json: any;
  cover_letter_text: string | null;
  latex_source: string | null;
  docx_fallback_path: string | null;
  pdf_compile_error: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
  has_pdf: boolean;
  has_cover_letter: boolean;
  file_expiry_info: FileExpiryInfo;
}

export async function getHistory(limit: number = 50, offset: number = 0): Promise<HistoryItem[]> {
  return request(`/history?limit=${limit}&offset=${offset}`);
}

export async function getHistoryDetail(generationId: string): Promise<HistoryDetail> {
  return request(`/history/${generationId}`);
}

export async function updateHistory(
  generationId: string,
  data: { status?: string; cover_letter_text?: string; resume_json?: any; ats_score_json?: any }
): Promise<{ generation_id: string; status: string; updated_at: string }> {
  return request(`/history/${generationId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function deleteHistory(generationId: string): Promise<{ generation_id: string; message: string }> {
  return request(`/history/${generationId}`, {
    method: 'DELETE',
  });
}
