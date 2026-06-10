import { request } from './api';
import type { ExtractionConfidenceReport, LockedFields, MasterProfile } from '../types/profile';

export interface StoredProfileResponse {
  id: string;
  user_id: string;
  profile_json: MasterProfile | null;
  profile_completion_score: number;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ProfileEmbeddingStatusResponse {
  status: 'pending' | 'processing' | 'complete' | 'failed' | string;
  count?: number;
  profile_id?: string | null;
  updated_at?: string | null;
}

export interface SourceResumeSummary {
  id: string;
  display_name: string;
  original_filename: string;
  file_type: string;
  content_type?: string | null;
  file_size: number;
  is_active: boolean;
  profile_json?: MasterProfile | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface SourceResumeListResponse {
  resumes: SourceResumeSummary[];
  active_source_resume_id?: string | null;
}

export interface SourceResumeUploadResponse {
  source_resume: SourceResumeSummary;
  extracted_profile: MasterProfile;
  confidence?: ExtractionConfidenceReport;
  locked_fields?: LockedFields;
  warnings: string[];
}

export async function getMyProfile(): Promise<StoredProfileResponse> {
  return request('/profile/me');
}

export async function saveMyProfile(profile: MasterProfile): Promise<StoredProfileResponse> {
  return request('/profile/me', {
    method: 'PUT',
    body: JSON.stringify({ profile_json: profile }),
  });
}

export async function getProfileEmbeddingStatus(): Promise<ProfileEmbeddingStatusResponse> {
  return request('/profile/embeddings/status');
}

export async function uploadSourceResume(file: File): Promise<SourceResumeUploadResponse> {
  const body = new FormData();
  body.append('resume_file', file);
  return request('/profile/source-resumes', { method: 'POST', body });
}

export async function listSourceResumes(): Promise<SourceResumeListResponse> {
  return request('/profile/source-resumes');
}

export async function activateSourceResume(sourceResumeId: string): Promise<SourceResumeListResponse> {
  return request(`/profile/source-resumes/${sourceResumeId}/activate`, { method: 'POST' });
}
