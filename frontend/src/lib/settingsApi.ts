import { request } from './api';

export interface UserSettings {
  id: string;
  user_id: string;
  target_resume_pages: number;
  preferred_tone: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface SettingsUpdate {
  target_resume_pages?: number;
  preferred_tone?: string;
}

export async function getSettings(): Promise<UserSettings> {
  return request('/settings', { method: 'GET' });
}

export async function updateSettings(data: SettingsUpdate): Promise<UserSettings> {
  return request('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}
