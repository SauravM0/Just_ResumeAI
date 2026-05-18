import { request } from './api';
import type { MasterProfile } from '../types/profile';

export interface StoredProfileResponse {
  id: string;
  user_id: string;
  profile_json: MasterProfile | null;
  profile_completion_score: number;
  status: string;
  created_at?: string | null;
  updated_at?: string | null;
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
