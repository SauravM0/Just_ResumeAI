/**
 * JD analysis types — mirrors backend schemas/jd.py.
 */

export type JDQualityLevel = 'strong' | 'moderate' | 'weak';

export type SeniorityLevel =
  | 'intern' | 'entry' | 'mid' | 'senior' | 'lead'
  | 'staff' | 'principal' | 'director' | 'vp' | 'c_level' | 'unknown';

export interface JDRequirement {
  text: string;
  is_required: boolean;
  category?: string;
}

export interface JDKeyword {
  keyword: string;
  frequency: number;
  importance: 'critical' | 'high' | 'medium' | 'low';
}

export interface ParsedJD {
  job_title: string;
  company?: string;
  location?: string;
  seniority: SeniorityLevel;
  department?: string;
  industry?: string;
  requirements: JDRequirement[];
  responsibilities: string[];
  keywords: JDKeyword[];
  required_skills: string[];
  preferred_skills: string[];
  tools_platforms: string[];
  programming_languages: string[];
  frameworks: string[];
  databases: string[];
  cloud_devops_tools: string[];
  domain_platform_terms: string[];
  deployment_environment_terms: string[];
  mobile_platform_terms: string[];
  soft_skills: string[];
  important_exact_phrases: string[];
  required_experience_years?: number;
  required_education?: string;
  quality: JDQualityLevel;
  quality_warnings: string[];
  raw_text: string;
}

export interface JDAnalyzeRequest {
  raw_jd_text: string;
}

import type { ValidationStatus } from './resume';

export interface JDAnalyzeResponse {
  generation_id: string;
  parsed_jd: ParsedJD;
  warnings: string[];
  validation_status?: ValidationStatus;
}

export interface JDAnalysisPreview {
  parsed_jd: ParsedJD;
  warnings: string[];
}
