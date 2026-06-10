import type { ResumeBullet, ResumeRecommendation } from '../types/resume';
import { objectArray, stringArray } from './resumeSafe';

function clean(value: string | undefined | null): string {
  return (value || '').trim();
}

function joinPresent(values: Array<string | undefined | null>, separator = ' | '): string {
  return values.map(clean).filter(Boolean).join(separator);
}

function includedBullets(bullets: unknown): ResumeBullet[] {
  return objectArray<ResumeBullet>(bullets).filter((bullet) => bullet.status !== 'rejected' && clean(bullet.text));
}

function section(title: string, lines: string[]): string[] {
  const body = lines.map(clean).filter(Boolean);
  return body.length ? [title, ...body] : [];
}

const FORBIDDEN_RESUME_PHRASES = [
  'Invalid Job Description Content',
  'Job Description Content',
  'We are seeking',
  'The ideal candidate',
  'Apply now',
  'ATS Keywords',
  'Responsibilities include',
  'Equal opportunity employer',
];

type TextEntry = {
  included?: boolean;
  title?: string;
  name?: string;
  company?: string;
  institution?: string;
  degree?: string;
  start_date?: string;
  end_date?: string;
  issuing_org?: string;
  issuer?: string;
  date?: string;
  description?: string;
  technologies?: unknown;
  bullets?: unknown;
  items?: unknown;
};

function blockContaminatedResumeText(value: string): string {
  const lowered = value.toLowerCase();
  return FORBIDDEN_RESUME_PHRASES.some((phrase) => lowered.includes(phrase.toLowerCase()))
    ? ''
    : value;
}

export function recommendationSummaryToText(recommendation: ResumeRecommendation): string {
  return clean(recommendation.summary);
}

export function recommendationSkillsToText(recommendation: ResumeRecommendation): string {
  return objectArray<{ category?: string; skills?: unknown }>(recommendation.skills)
    .map((group) => ({
      category: clean(group.category),
      skills: stringArray(group.skills).map(clean).filter(Boolean),
    }))
    .filter((group) => group.category && group.skills.length > 0)
    .map((group) => `${group.category}: ${group.skills.join(', ')}`)
    .filter(Boolean)
    .join('\n');
}

export function recommendationToPlainText(recommendation: ResumeRecommendation): string {
  const contact = recommendation.contact;
  const blocks: string[] = [];

  if (contact) {
    const name = clean(contact.full_name);
    const details = joinPresent([
      contact.email,
      contact.phone,
      contact.location,
      contact.linkedin_url,
      contact.github_url,
      contact.portfolio_url,
    ]);
    if (name) blocks.push(name.toUpperCase());
    if (details) blocks.push(details);
  }

  if (clean(recommendation.target_title)) blocks.push(clean(recommendation.target_title).toUpperCase());

  blocks.push(...section('SUMMARY', [recommendationSummaryToText(recommendation)]));
  blocks.push(...section('TECHNICAL SKILLS', [recommendationSkillsToText(recommendation)]));

  const experienceLines = objectArray<TextEntry>(recommendation.experience)
    .filter((entry) => entry.included)
    .flatMap((entry) => {
      const heading = `${entry.title} — ${entry.company} | ${entry.start_date} - ${entry.end_date || 'Present'}`;
      return [
        heading,
        ...includedBullets(entry.bullets).map((bullet) => `- ${bullet.text}`),
      ];
    });
  blocks.push(...section('EXPERIENCE', experienceLines));

  const projectLines = objectArray<TextEntry>(recommendation.projects)
    .filter((entry) => entry.included)
    .flatMap((entry) => {
      const heading = joinPresent([entry.name, stringArray(entry.technologies).join(', ')]);
      return [
        heading,
        ...includedBullets(entry.bullets).map((bullet) => `- ${bullet.text}`),
      ];
    });
  blocks.push(...section('PROJECTS', projectLines));

  const educationLines = objectArray<TextEntry>(recommendation.education)
    .filter((entry) => entry.included)
    .map((entry) => joinPresent([entry.degree, entry.institution], ', '));
  blocks.push(...section('EDUCATION', educationLines));

  const certificationLines = objectArray<TextEntry>(recommendation.certifications)
    .filter((entry) => entry.included)
    .map((entry) => joinPresent([entry.name, entry.issuing_org, entry.date]));
  blocks.push(...section('CERTIFICATIONS', certificationLines));

  const achievementLines = [...objectArray<TextEntry>(recommendation.achievements), ...objectArray<TextEntry>(recommendation.awards)]
    .filter((entry) => entry.included)
    .map((entry) => joinPresent([entry.title, entry.issuer, entry.date, entry.description]));
  blocks.push(...section('ACHIEVEMENTS', achievementLines));

  objectArray<TextEntry>(recommendation.custom_sections)
    .filter((entry) => entry.included && stringArray(entry.items).length)
    .forEach((entry) => blocks.push(...section((entry.title || '').toUpperCase(), stringArray(entry.items))));

  return blockContaminatedResumeText(blocks.filter(Boolean).join('\n\n'));
}

export function recommendationToMarkdown(recommendation: ResumeRecommendation): string {
  const contact = recommendation.contact;
  const lines: string[] = [];

  if (contact?.full_name) lines.push(`# ${clean(contact.full_name)}`);
  const details = contact
    ? joinPresent([
        contact.email,
        contact.phone,
        contact.location,
        contact.linkedin_url,
        contact.github_url,
        contact.portfolio_url,
      ])
    : '';
  if (details) lines.push(details);

  if (clean(recommendation.target_title)) lines.push(`## ${clean(recommendation.target_title)}`);
  if (clean(recommendation.summary)) lines.push(`### Summary\n${clean(recommendation.summary)}`);

  const skills = recommendationSkillsToText(recommendation);
  if (skills) lines.push(`### Technical Skills\n${skills}`);

  const experiences = objectArray<TextEntry>(recommendation.experience).filter((entry) => entry.included);
  if (experiences.length) {
    lines.push('### Experience');
    experiences.forEach((entry) => {
      lines.push(`**${entry.title} - ${entry.company}** | ${entry.start_date} - ${entry.end_date || 'Present'}`);
      includedBullets(entry.bullets).forEach((bullet) => lines.push(`- ${bullet.text}`));
    });
  }

  const projects = objectArray<TextEntry>(recommendation.projects).filter((entry) => entry.included);
  if (projects.length) {
    lines.push('### Projects');
    projects.forEach((entry) => {
      const technologies = stringArray(entry.technologies);
      lines.push(`**${entry.name}**${technologies.length ? ` | ${technologies.join(', ')}` : ''}`);
      includedBullets(entry.bullets).forEach((bullet) => lines.push(`- ${bullet.text}`));
    });
  }

  const education = objectArray<TextEntry>(recommendation.education).filter((entry) => entry.included);
  if (education.length) {
    lines.push('### Education');
    education.forEach((entry) => lines.push(`- ${joinPresent([entry.degree, entry.institution], ', ')}`));
  }

  const certifications = objectArray<TextEntry>(recommendation.certifications).filter((entry) => entry.included);
  if (certifications.length) {
    lines.push('### Certifications');
    certifications.forEach((entry) => lines.push(`- ${joinPresent([entry.name, entry.issuing_org, entry.date])}`));
  }

  const achievements = [...objectArray<TextEntry>(recommendation.achievements), ...objectArray<TextEntry>(recommendation.awards)].filter((entry) => entry.included);
  if (achievements.length) {
    lines.push('### Achievements');
    achievements.forEach((entry) => lines.push(`- ${joinPresent([entry.title, entry.issuer, entry.date, entry.description])}`));
  }

  objectArray<TextEntry>(recommendation.custom_sections)
    .filter((entry) => entry.included && stringArray(entry.items).length)
    .forEach((entry) => {
      lines.push(`### ${entry.title}`);
      stringArray(entry.items).forEach((item) => lines.push(`- ${item}`));
    });

  return lines.filter(Boolean).join('\n\n');
}
