export interface ATSAlignmentReport {
  overall_alignment_percent: number;
  keyword_coverage_percent: number;
  formatting_score: number;
  section_completeness_score: number;
  jd_title_detected: string;
  required_skills: string[];
  preferred_skills: string[];
  role_responsibilities: string[];
  important_ats_keywords: string[];
  keywords_included: string[];
  keywords_missing: string[];
  suggestions: string[];
  resume_rewrite_strategy: string;
}
