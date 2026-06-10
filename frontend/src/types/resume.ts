/**
 * Resume pipeline types — mirrors backend schemas/resume.py and schemas/scoring.py.
 */

import type { MasterProfile } from './profile';
import type { ParsedJD } from './jd';
import type { ATSAlignmentReport } from './alignment';

export type BulletStatus = 'pending' | 'accepted' | 'edited' | 'locked' | 'needs_repair' | 'rejected';

export interface ResumeBullet {
  id: string;
  text: string;
  original_text?: string;
  status: BulletStatus;
  relevance_score: number;
  matched_keywords: string[];
  source_id?: string;
  repair_note?: string;
  star_score?: number;
  has_strong_verb?: boolean;
  has_context?: boolean;
  has_outcome?: boolean;
  has_banned_phrase?: boolean;
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
  version_id: string;
  content_hash?: string;
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
  bullet_quality_score?: number;
  overall_score: number;
  resume_version_id?: string;
  keyword_score: KeywordScore;
  skill_score: SkillScore;
  readability_score: ReadabilityScore;
  format_score: number;
  section_score: SectionScore;
  responsibility_score: number;
  title_alignment_score: number;
  missing_keywords: string[];
  matched_supported_keywords?: string[];
  unsupported_jd_keywords?: string[];
  learning_focus_keywords?: string[];
  warnings: string[];
  recommendations: string[];
  stuffing_warnings?: string[];
  final_pdf_parse_status?: string;
  score_breakdown?: Record<string, number>;
  // Honest sub-scores
  keyword_coverage_score?: number;
  supported_coverage_score?: number;
  formatting_readiness_score?: number;
  seniority_honesty_score?: number;
  validation_readiness_score?: number;
  readability_warnings_count?: number;
  export_ready?: boolean;
}

// ─── Validation Status (mirrors backend schemas/validation.py) ────────────

export type ValidationSeverity = 'pass' | 'warning' | 'blocked';

export interface ValidationStatus {
  export_ready: boolean;
  severity: ValidationSeverity;
  blocked_reasons: string[];
  warnings: string[];
  repair_actions: string[];
  user_actions: string[];
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
  validation_status?: ValidationStatus;
}

export type KeywordConfirmationLevel = 'professional' | 'project' | 'basic' | 'learning' | 'no';

export interface KeywordConfirmation {
  keyword: string;
  level: KeywordConfirmationLevel;
}

export interface ConfirmKeywordsRequest {
  keywords: KeywordConfirmation[];
}

export interface ConfirmKeywordsResponse {
  generation_id: string;
  confirmed_keywords: KeywordConfirmation[];
  usable_keywords: KeywordConfirmation[];
}

export interface FastResumeGenerateRequest {
  profile: MasterProfile;
  raw_jd_text?: string;
  source_generation_id?: string;
  job_title?: string;
  company?: string;
  emphasis?: string;
  target_pages?: number;
  save_to_database?: boolean;
  ats_optimization_mode?: 'realistic' | 'aggressive';
}

export interface FastResumeGenerateResponse {
  generation_id: string;
  persisted: boolean;
  resume_json: ResumeRecommendation;
  ats_score: number;
  matched_keywords: string[];
  missing_keywords: string[];
  extracted_keywords: string[];
  confirmed_keywords: KeywordConfirmation[];
  score_breakdown: Record<string, number>;
  score_explanation: string[];
  improvement_suggestions: string[];
  score_disclaimer: string;
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
  ats_optimization_mode?: 'realistic' | 'aggressive';
  target_ats_score?: number;
  max_repair_attempts?: number;
}

export interface PipelinePdfResult {
  requested: boolean;
  compile_success: boolean;
  pdf_url?: string;
  expires_at?: string;
  compile_errors: string[];
  compile_warnings: string[];
  inspection_warnings: string[];
  page_count?: number;
  target_pages?: number;
  compression_applied: boolean;
  compression_actions: string[];
  generated_tex_path?: string;
  pdflatex_excerpt?: string;
  line_number?: number;
}

export interface OptimizationAttemptDiagnostics {
  attempt: number;
  json_score: ATSScore;
  pdf_text_score?: ATSScore | null;
  missing_keywords: string[];
  matched_keywords: string[];
  title_alignment_score: number;
  skills_coverage_percent: number;
  section_quality_score: number;
  page_count?: number | null;
  compile_success: boolean;
  repair_actions: string[];
  warnings: string[];
}

export interface ResumeOptimizationResult {
  target_score: number;
  target_pages: number;
  attempts_used: number;
  reached_target: boolean;
  final_score_source: string;
  final_pdf_text_score?: ATSScore | null;
  final_json_score?: ATSScore | null;
  final_page_count?: number | null;
  final_pdf_path?: string | null;
  final_latex_source: string;
  final_recommendation: ResumeRecommendation;
  diagnostics: OptimizationAttemptDiagnostics[];
  score_history: number[];
  missing_keywords: string[];
  matched_keywords: string[];
  title_alignment_score: number;
  skills_coverage_percent: number;
  section_quality_score: number;
  score_explanation: string[];
  compile_warnings: string[];
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
  optimization: ResumeOptimizationResult;
  steps: PipelineStepStatus[];
  warnings: string[];
  validation_status?: ValidationStatus;
  recruiter_review?: RecruiterReview;
  score_history?: number[];
  strategy_history?: string[];
}

// ─── Direct Download Export ─────────────────────────────────────────────

export interface ExportFileResponse {
  blob: Blob;
  filename: string;
  file_type: 'pdf' | 'docx';
  compile_warnings?: string[];
  inspection_warnings?: string[];
  page_count?: number;
  compressed?: boolean;
  compression_actions?: string[];
  regenerated?: boolean;
  /** Validation gate repaired the resume before export */
  validation_repaired?: boolean;
  /** Validation warnings from the gate */
  validation_warnings?: string[];
  /** Whether export passed all validation checks */
  export_ready?: boolean;
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

// ─── Quality Visualization ───────────────────────────────────────────────────

export interface RecruiterReview {
  overall_impression: number;
  summary_assessment: string;
  weak_bullet_ids: string[];
  recommended_for_shortlist: boolean;
  hr_flags: string[];
}

export interface ScoreHistoryEntry {
  score: number;
  strategy: string;
  attempt: number;
}
