/**
 * Master Profile types — mirrors backend schemas/profile.py exactly.
 * These types are the contract between IndexedDB, frontend UI, and backend API.
 */

export type SkillLevel = 'beginner' | 'intermediate' | 'advanced' | 'expert';

export type DegreeType =
  | 'high_school'
  | 'associate'
  | 'bachelor'
  | 'master'
  | 'doctorate'
  | 'certification'
  | 'other';

export interface ContactInfo {
  full_name: string;
  email: string;
  phone?: string;
  location?: string;
  linkedin_url?: string;
  github_url?: string;
  portfolio_url?: string;
}

export interface WorkExperience {
  id: string;
  company: string;
  title: string;
  location?: string;
  start_date: string;
  end_date?: string;
  is_current: boolean;
  description?: string;
  bullets: string[];
  tags: string[];
}

export interface Education {
  id: string;
  institution: string;
  degree: string;
  degree_type: DegreeType;
  field_of_study?: string;
  start_date?: string;
  end_date?: string;
  gpa?: string;
  honors?: string;
  relevant_coursework: string[];
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  url?: string;
  technologies: string[];
  bullets: string[];
  start_date?: string;
  end_date?: string;
}

export interface Skill {
  name: string;
  level?: SkillLevel;
  category?: string;
}

export interface Certification {
  id: string;
  name: string;
  issuing_org?: string;
  issue_date?: string;
  expiry_date?: string;
  credential_id?: string;
  url?: string;
}

export interface Publication {
  id: string;
  title: string;
  publisher?: string;
  date?: string;
  url?: string;
  description?: string;
}

export interface VolunteerExperience {
  id: string;
  organization: string;
  role: string;
  start_date?: string;
  end_date?: string;
  bullets: string[];
}

export interface Award {
  id: string;
  title: string;
  issuer?: string;
  date?: string;
  description?: string;
}

export interface MasterProfile {
  id: string;
  version: number;
  contact: ContactInfo;
  summary?: string;
  work_experience: WorkExperience[];
  education: Education[];
  skills: Skill[];
  projects: Project[];
  certifications: Certification[];
  publications: Publication[];
  volunteer: VolunteerExperience[];
  awards: Award[];
  custom_sections: Record<string, string[]>;
  created_at?: string;
  updated_at?: string;
}
