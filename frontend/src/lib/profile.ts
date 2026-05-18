import type { MasterProfile } from '../types/profile';

export function createBlankProfile(): MasterProfile {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    version: 1,
    contact: {
      full_name: '',
      email: '',
    },
    summary: '',
    work_experience: [],
    education: [],
    skills: [],
    projects: [],
    certifications: [],
    publications: [],
    volunteer: [],
    awards: [],
    custom_sections: {},
    created_at: now,
    updated_at: now,
  };
}

function emptyToUndefined(value?: string): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

function cleanStringArray(values: string[]): string[] {
  return values.map((value) => value.trim()).filter(Boolean);
}

export function sanitizeProfile(profile: MasterProfile): MasterProfile {
  return {
    ...profile,
    contact: {
      ...profile.contact,
      full_name: profile.contact.full_name.trim(),
      email: profile.contact.email.trim(),
      phone: emptyToUndefined(profile.contact.phone),
      location: emptyToUndefined(profile.contact.location),
      linkedin_url: emptyToUndefined(profile.contact.linkedin_url),
      github_url: emptyToUndefined(profile.contact.github_url),
      portfolio_url: emptyToUndefined(profile.contact.portfolio_url),
    },
    summary: emptyToUndefined(profile.summary),
    work_experience: profile.work_experience
      .map((experience) => ({
        ...experience,
        company: experience.company.trim(),
        title: experience.title.trim(),
        location: emptyToUndefined(experience.location),
        start_date: experience.start_date.trim(),
        end_date: emptyToUndefined(experience.end_date),
        description: emptyToUndefined(experience.description),
        bullets: cleanStringArray(experience.bullets),
        tags: cleanStringArray(experience.tags),
      }))
      .filter((experience) => experience.company && experience.title),
    education: profile.education
      .map((education) => ({
        ...education,
        institution: education.institution.trim(),
        degree: education.degree.trim(),
        field_of_study: emptyToUndefined(education.field_of_study),
        start_date: emptyToUndefined(education.start_date),
        end_date: emptyToUndefined(education.end_date),
        gpa: emptyToUndefined(education.gpa),
        honors: emptyToUndefined(education.honors),
        relevant_coursework: cleanStringArray(education.relevant_coursework),
      }))
      .filter((education) => education.institution && education.degree),
    skills: profile.skills
      .map((skill) => ({
        ...skill,
        name: skill.name.trim(),
        category: emptyToUndefined(skill.category),
      }))
      .filter((skill) => skill.name),
    projects: profile.projects
      .map((project) => ({
        ...project,
        name: project.name.trim(),
        description: emptyToUndefined(project.description),
        url: emptyToUndefined(project.url),
        technologies: cleanStringArray(project.technologies),
        bullets: cleanStringArray(project.bullets),
        start_date: emptyToUndefined(project.start_date),
        end_date: emptyToUndefined(project.end_date),
      }))
      .filter((project) => project.name),
    certifications: profile.certifications
      .map((certification) => ({
        ...certification,
        name: certification.name.trim(),
        issuing_org: emptyToUndefined(certification.issuing_org),
        issue_date: emptyToUndefined(certification.issue_date),
        expiry_date: emptyToUndefined(certification.expiry_date),
        credential_id: emptyToUndefined(certification.credential_id),
        url: emptyToUndefined(certification.url),
      }))
      .filter((certification) => certification.name),
    publications: profile.publications
      .map((publication) => ({
        ...publication,
        title: publication.title.trim(),
        publisher: emptyToUndefined(publication.publisher),
        date: emptyToUndefined(publication.date),
        url: emptyToUndefined(publication.url),
        description: emptyToUndefined(publication.description),
      }))
      .filter((publication) => publication.title),
    volunteer: profile.volunteer
      .map((item) => ({
        ...item,
        organization: item.organization.trim(),
        role: item.role.trim(),
        start_date: emptyToUndefined(item.start_date),
        end_date: emptyToUndefined(item.end_date),
        bullets: cleanStringArray(item.bullets),
      }))
      .filter((item) => item.organization && item.role),
    awards: profile.awards
      .map((award) => ({
        ...award,
        title: award.title.trim(),
        issuer: emptyToUndefined(award.issuer),
        date: emptyToUndefined(award.date),
        description: emptyToUndefined(award.description),
      }))
      .filter((award) => award.title),
    custom_sections: Object.fromEntries(
      Object.entries(profile.custom_sections).map(([key, values]) => [key, cleanStringArray(values)])
    ),
  };
}
