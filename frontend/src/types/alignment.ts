export interface KeywordPlacementReport {
  keywords_in_target_title: string[];
  keywords_in_summary: string[];
  keywords_in_skills: string[];
  keywords_in_first_experience_bullets: string[];
  keywords_in_projects: string[];
  missing_high_priority_keywords: string[];
  weakly_placed_keywords: string[];
}

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
  keyword_placement: KeywordPlacementReport;
  suggestions: string[];
  resume_rewrite_strategy: string;
}
