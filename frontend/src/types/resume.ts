/**
 * Resume pipeline types — mirrors backend schemas/resume.py and schemas/scoring.py.
 */

import type { MasterProfile } from './profile';
import type { ParsedJD } from './jd';
import type { ATSAlignmentReport } from './alignment';

export type BulletStatus = 'pending' | 'accepted' | 'edited' | 'locked' | 'rejected';

export interface ResumeBullet {
  id: string;
  text: string;
  original_text?: string;
  status: BulletStatus;
  relevance_score: number;
  matched_keywords: string[];
  source_id?: string;
}

export interface ResumeExperienceEntry {
  source_id: string;
  company: string;
  title: string;
  location?: string;
  start_date: string;
  end_date?: string;
  is_current: boolean;
  bullets: ResumeBullet[];
  included: boolean;
  relevance_score: number;
}

export interface ResumeEducationEntry {
  source_id: string;
  institution: string;
  degree: string;
  field_of_study?: string;
  start_date?: string;
  end_date?: string;
  gpa?: string;
  honors?: string;
  relevant_coursework: string[];
  included: boolean;
}

export interface ResumeProjectEntry {
  source_id: string;
  name: string;
  description?: string;
  technologies: string[];
  bullets: ResumeBullet[];
  included: boolean;
  relevance_score: number;
}

export interface ResumeSkillGroup {
  category: string;
  skills: string[];
}

export interface ResumeCertEntry {
  source_id: string;
  name: string;
  issuing_org?: string;
  date?: string;
  included: boolean;
}

export interface ResumeAchievementEntry {
  source_id: string;
  title: string;
  issuer?: string;
  date?: string;
  description?: string;
  included: boolean;
}

export interface ResumeCustomSection {
  title: string;
  items: string[];
  included: boolean;
}

export interface ResumeContactInfo {
  full_name: string;
  email: string;
  phone?: string;
  location?: string;
  linkedin_url?: string;
  github_url?: string;
  portfolio_url?: string;
}

export interface ResumeRecommendation {
  generation_id: string;
  target_title: string;
  summary?: string;
  contact?: ResumeContactInfo;
  experience: ResumeExperienceEntry[];
  education: ResumeEducationEntry[];
  skills: ResumeSkillGroup[];
  projects: ResumeProjectEntry[];
  certifications: ResumeCertEntry[];
  achievements: ResumeAchievementEntry[];
  awards: ResumeAchievementEntry[];
  custom_sections: ResumeCustomSection[];
  section_order: string[];
  emphasis?: string;
  warnings: string[];
}

// ─── Scoring ────────────────────────────────────────────────────────────────

export interface KeywordMatch {
  keyword: string;
  found: boolean;
  location: string;
}

export interface KeywordScore {
  total_keywords: number;
  matched_keywords: number;
  coverage_percent: number;
  critical_missing: string[];
  details: KeywordMatch[];
}

export interface SkillScore {
  required_total: number;
  required_matched: number;
  required_coverage_percent: number;
  preferred_total: number;
  preferred_matched: number;
  preferred_coverage_percent: number;
}

export interface ReadabilityScore {
  score: number;
  avg_bullet_length: number;
  issues: string[];
}

export interface SectionScore {
  score: number;
  missing_sections: string[];
  has_contact: boolean;
  has_summary: boolean;
  has_experience: boolean;
  has_skills: boolean;
  has_education: boolean;
}

export interface ATSScore {
  overall_score: number;
  keyword_score: KeywordScore;
  skill_score: SkillScore;
  readability_score: ReadabilityScore;
  format_score: number;
  section_score: SectionScore;
  responsibility_score: number;
  title_alignment_score: number;
  missing_keywords: string[];
  warnings: string[];
  recommendations: string[];
}

// ─── API Contracts ──────────────────────────────────────────────────────────

export interface ResumeRecommendRequest {
  generation_id: string;
  profile: MasterProfile;
  emphasis?: string;
  additional_alignment_text?: string;
  rejected_item_ids: string[];
}

export interface ResumeRecommendResponse {
  recommendation: ResumeRecommendation;
  alignment_report?: ATSAlignmentReport;
}

export interface ResumeRegenerateRequest {
  generation_id: string;
  profile: MasterProfile;
  emphasis?: string;
  additional_alignment_text?: string;
  locked_bullet_ids: string[];
  rejected_item_ids: string[];
}

export interface ResumeValidateRequest {
  generation_id: string;
  recommendation: ResumeRecommendation;
}

export interface ValidateResponse {
  generation_id: string;
  ats_score: ATSScore;
}

export type EligibilityStatus = 'match' | 'partial_match' | 'hard_mismatch';
export type PipelineStepState = 'pending' | 'success' | 'failed' | 'skipped';

/**
 * @deprecated Compatibility-only response field. The MVP does not display or gate on eligibility.
 */
export interface EligibilityResult {
  status: EligibilityStatus;
  blocking_issues: string[];
  warnings: string[];
  matched_points: string[];
}

export interface PipelineStepStatus {
  name: string;
  status: PipelineStepState;
  detail?: string;
}

export interface PipelineGenerateRequest {
  profile: MasterProfile;
  raw_jd_text: string;
  target_pages?: number;
  allow_two_pages_for_senior?: boolean;
  generate_pdf?: boolean;
  emphasis?: string;
  additional_alignment_text?: string;
}

export interface PipelinePdfResult {
  requested: boolean;
  compile_success: boolean;
  pdf_url?: string;
  expires_at?: string;
  compile_errors: string[];
  compile_warnings: string[];
  generated_tex_path?: string;
  pdflatex_excerpt?: string;
  line_number?: number;
}

export interface PipelineGenerateResponse {
  generation_id: string;
  parsed_jd: ParsedJD;
  eligibility: EligibilityResult;
  recommendation: ResumeRecommendation;
  ats_score: ATSScore;
  alignment_report: ATSAlignmentReport;
  latex_source: string;
  pdf: PipelinePdfResult;
  steps: PipelineStepStatus[];
  warnings: string[];
}

// ─── Direct Download Export ─────────────────────────────────────────────

export interface ExportFileResponse {
  blob: Blob;
  filename: string;
  file_type: 'pdf' | 'docx';
  compile_warnings?: string[];
  regenerated?: boolean;
}

export interface GenerationFileInfo {
  id: string;
  file_type: string;
  storage_path: string;
  expires_at: string | null;
  is_expired: boolean;
  created_at: string | null;
  signed_url: string | null;
}

export interface GenerationFilesResponse {
  generation_id: string;
  has_files: boolean;
  pdf_available: boolean;
  docx_available: boolean;
  expires_at: string | null;
  earliest_expiry: string | null;
  is_expired: boolean;
  regenerate_available: boolean;
  files: GenerationFileInfo[];
}
