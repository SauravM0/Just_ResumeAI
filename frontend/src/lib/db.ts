/**
 * IndexedDB abstraction layer for master profile storage.
 *
 * Uses the `idb` library for a Promise-based IndexedDB API.
 * The master profile is the PRIMARY data store — the backend never persists it.
 *
 * DB Schema:
 *   - Store: "profiles" — keyed by profile.id
 *   - Only one profile is expected for MVP (single-user).
 */

import { openDB, type IDBPDatabase } from 'idb';
import type { MasterProfile } from '../types/profile';
import type { ParsedJD } from '../types/jd';
import type { ATSScore, PipelinePdfResult, ResumeRecommendation } from '../types/resume';
import { sanitizeProfile } from './profile';

const DB_NAME = 'justresume';
const DB_VERSION = 2;
const STORE_NAME = 'profiles';
const RECENT_RESUMES_STORE = 'recent_resumes';

export interface RecentResume {
  id: string;
  date: string;
  job_title: string;
  company?: string;
  ats_score?: number;
  recommendation: ResumeRecommendation;
  pdf_url?: string;
  cover_letter?: string;
}

interface RecentResumeInput {
  sessionId: string;
  parsedJD: ParsedJD | null;
  recommendation: ResumeRecommendation;
  atsScore: ATSScore | null;
  pipelinePdf?: PipelinePdfResult | null;
  coverLetterText?: string;
}

let dbPromise: Promise<IDBPDatabase> | null = null;

function getDB(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains(RECENT_RESUMES_STORE)) {
          db.createObjectStore(RECENT_RESUMES_STORE, { keyPath: 'id' });
        }
      },
    });
  }
  return dbPromise;
}

/**
 * Save or update a master profile in IndexedDB.
 */
export async function saveProfile(profile: MasterProfile): Promise<void> {
  const db = await getDB();
  const updated: MasterProfile = {
    ...sanitizeProfile(profile),
    updated_at: new Date().toISOString(),
  };
  await db.put(STORE_NAME, updated);
}

/**
 * Get a profile by ID.
 */
export async function getProfile(id: string): Promise<MasterProfile | undefined> {
  const db = await getDB();
  const profile = await db.get(STORE_NAME, id);
  return profile ? sanitizeProfile(profile as MasterProfile) : undefined;
}

/**
 * Get all profiles (for MVP, usually just one).
 */
export async function getAllProfiles(): Promise<MasterProfile[]> {
  const db = await getDB();
  const profiles = await db.getAll(STORE_NAME);
  return profiles.map((profile) => sanitizeProfile(profile as MasterProfile));
}

/**
 * Delete a profile by ID.
 */
export async function deleteProfile(id: string): Promise<void> {
  const db = await getDB();
  await db.delete(STORE_NAME, id);
}

/**
 * Get the default/first profile, or null if none exists.
 * For MVP single-user mode.
 */
export async function getDefaultProfile(): Promise<MasterProfile | null> {
  const profiles = await getAllProfiles();
  return profiles.length > 0 ? profiles[0] : null;
}

export async function saveRecentResumeSnapshot({
  sessionId,
  parsedJD,
  recommendation,
  atsScore,
  pipelinePdf,
  coverLetterText,
}: RecentResumeInput): Promise<void> {
  const db = await getDB();
  const existing = await db.get(RECENT_RESUMES_STORE, sessionId) as RecentResume | undefined;
  const pdfUrl = pipelinePdf?.compile_success ? pipelinePdf.pdf_url : undefined;
  const recent: RecentResume = {
    id: sessionId,
    date: existing?.date ?? new Date().toISOString(),
    job_title: parsedJD?.job_title || recommendation.target_title || 'Untitled role',
    company: parsedJD?.company || undefined,
    ats_score: atsScore?.overall_score,
    recommendation,
    pdf_url: pdfUrl ?? existing?.pdf_url,
    cover_letter: coverLetterText?.trim() || existing?.cover_letter,
  };
  await db.put(RECENT_RESUMES_STORE, recent);
}

export async function getRecentResumes(limit = 5): Promise<RecentResume[]> {
  const db = await getDB();
  const recent = await db.getAll(RECENT_RESUMES_STORE) as RecentResume[];
  return recent
    .sort((a, b) => Date.parse(b.date) - Date.parse(a.date))
    .slice(0, limit);
}

/**
 * Create a blank profile scaffold with a generated ID.
 */
export function createBlankProfile(): MasterProfile {
  return {
    id: crypto.randomUUID(),
    version: 1,
    contact: {
      full_name: '',
      email: '',
    },
    work_experience: [],
    education: [],
    skills: [],
    projects: [],
    certifications: [],
    publications: [],
    volunteer: [],
    awards: [],
    custom_sections: {},
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}
