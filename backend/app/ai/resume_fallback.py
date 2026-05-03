"""
Deterministic fallback resume recommendation logic used when Gemini is unavailable.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from app.domain.rules import MAX_EXPERIENCES, MAX_PROJECTS, MAX_BULLETS_PER_EXPERIENCE, MAX_SUMMARY_WORDS
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile, Project, WorkExperience
from app.schemas.resume import (
    BulletStatus,
    ResumeBullet,
    ResumeCertEntry,
    ResumeContactInfo,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeProjectEntry,
    ResumeRecommendation,
    ResumeSkillGroup,
)

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "of", "on", "or", "that", "the", "to", "with", "you", "your", "our",
    "will", "this", "their", "they", "them", "have", "has", "had", "using", "use",
    "build", "built", "work", "working", "role", "team", "teams",
}

_FALLBACK_WARNING = (
    "AI generation was unavailable; this resume was generated using deterministic fallback ranking."
)


def normalize_terms(text: str | None) -> set[str]:
    """Normalize free text into a lowercase token set."""
    if not text:
        return set()
    tokens = re.findall(r"[a-z0-9][a-z0-9\+\#\.\-]{1,}", text.lower())
    return {token for token in tokens if token not in _STOPWORDS}


def score_text_against_jd(text: str | None, jd_terms: set[str]) -> tuple[float, list[str]]:
    """Return normalized overlap score and the matched JD terms for a text blob."""
    if not text or not jd_terms:
        return 0.0, []

    text_terms = normalize_terms(text)
    if not text_terms:
        return 0.0, []

    matches = sorted(text_terms & jd_terms)
    score = len(matches) / max(len(jd_terms), 1)
    return min(score, 1.0), matches


def generate_recommendation_without_ai(
    profile: MasterProfile,
    parsed_jd: ParsedJD,
    session_id: str,
    emphasis: str | None = None,
    rejected_ids: list[str] | None = None,
    locked_bullets: dict[str, str] | None = None,
    target_pages: int = 1,
    additional_alignment_text: str | None = None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> ResumeRecommendation:
    """Build a deterministic ResumeRecommendation without calling Gemini."""
    rejected_ids = rejected_ids or []
    locked_bullets = locked_bullets or {}

    jd_terms = _build_jd_terms(parsed_jd, " ".join([emphasis or "", additional_alignment_text or ""]), ats_plan)
    profile_skill_terms = normalize_terms(" ".join(skill.name for skill in profile.skills))

    ranked_experiences = rank_experiences(profile, jd_terms, profile_skill_terms, rejected_ids)
    ranked_projects = rank_projects(profile, jd_terms, profile_skill_terms, rejected_ids)

    selected_experiences = ranked_experiences[:MAX_EXPERIENCES]
    selected_projects = ranked_projects[:MAX_PROJECTS]

    skill_groups = _build_skill_groups(profile, jd_terms, ats_plan)
    strongest_skills = _top_skill_names(skill_groups)

    experience_entries = [
        build_experience_entry(exp, score, matched_keywords, jd_terms, locked_bullets)
        for exp, score, matched_keywords, _ in selected_experiences
    ]
    experience_entries = [e for e in experience_entries if len(e.bullets) >= 2]

    project_entries = [
        build_project_entry(project, score, matched_keywords, jd_terms, locked_bullets)
        for project, score, matched_keywords, _ in selected_projects
    ]
    project_entries = [p for p in project_entries if len(p.bullets) >= 2]

    contact = ResumeContactInfo(
        full_name=profile.contact.full_name,
        email=profile.contact.email,
        phone=profile.contact.phone,
        location=profile.contact.location,
        linkedin_url=profile.contact.linkedin_url,
        github_url=profile.contact.github_url,
        portfolio_url=profile.contact.portfolio_url,
    )

    education_entries = [
        ResumeEducationEntry(
            source_id=edu.id,
            institution=edu.institution,
            degree=edu.degree,
            field_of_study=edu.field_of_study,
            start_date=edu.start_date,
            end_date=edu.end_date,
            gpa=edu.gpa,
            honors=edu.honors,
            relevant_coursework=edu.relevant_coursework,
        )
        for edu in profile.education
    ]

    cert_entries = [
        ResumeCertEntry(
            source_id=cert.id,
            name=cert.name,
            issuing_org=cert.issuing_org,
            date=cert.issue_date,
        )
        for cert in profile.certifications
    ]

    raw_target_title = ats_plan.target_resume_title if ats_plan else _fallback_target_title(profile, parsed_jd, "")
    target_title = _clean_resume_title(raw_target_title)
    summary = build_fallback_summary(
        profile=profile,
        target_title=target_title,
        strongest_skills=strongest_skills,
        selected_experiences=[exp for exp, _, _, _ in selected_experiences],
        selected_projects=[project for project, _, _, _ in selected_projects],
        ats_plan=ats_plan,
    )

    warnings = [_FALLBACK_WARNING]
    if not experience_entries:
        warnings.append("No work experience strongly matched the job description; fallback selected the closest available profile content.")
    if not project_entries and profile.projects:
        warnings.append("Projects were available but did not strongly match the job description; fallback selected none.")

    return ResumeRecommendation(
        session_id=session_id,
        target_title=target_title,
        summary=summary,
        contact=contact,
        experience=experience_entries,
        education=education_entries,
        skills=skill_groups,
        projects=project_entries,
        certifications=cert_entries,
        emphasis=emphasis,
        warnings=warnings,
    )


def rank_experiences(
    profile: MasterProfile,
    jd_terms: set[str],
    profile_skill_terms: set[str],
    rejected_ids: list[str],
) -> list[tuple[WorkExperience, float, list[str], int]]:
    """Rank experiences by deterministic JD overlap, preserving input order for ties."""
    ranked: list[tuple[WorkExperience, float, list[str], int]] = []
    skill_overlap = len(profile_skill_terms & jd_terms) / max(len(jd_terms), 1) if jd_terms else 0.0

    for index, exp in enumerate(profile.work_experience):
        if exp.id in rejected_ids:
            continue

        score, matched_keywords = _score_experience(exp, jd_terms, skill_overlap)
        ranked.append((exp, score, matched_keywords, index))

    return sorted(ranked, key=lambda item: (-item[1], item[3]))


def rank_projects(
    profile: MasterProfile,
    jd_terms: set[str],
    profile_skill_terms: set[str],
    rejected_ids: list[str],
) -> list[tuple[Project, float, list[str], int]]:
    """Rank projects by deterministic JD overlap, preserving input order for ties."""
    ranked: list[tuple[Project, float, list[str], int]] = []
    skill_overlap = len(profile_skill_terms & jd_terms) / max(len(jd_terms), 1) if jd_terms else 0.0

    for index, project in enumerate(profile.projects):
        if project.id in rejected_ids:
            continue

        score, matched_keywords = _score_project(project, jd_terms, skill_overlap)
        ranked.append((project, score, matched_keywords, index))

    return sorted(ranked, key=lambda item: (-item[1], item[3]))


def build_fallback_summary(
    profile: MasterProfile,
    target_title: str,
    strongest_skills: list[str],
    selected_experiences: list[WorkExperience],
    selected_projects: list[Project],
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> str:
    """Create a short deterministic summary using only profile and selection data."""
    years = _infer_years_of_experience(profile.work_experience)
    years_text = f" with {years}+ years of experience" if years and years > 0 else ""

    themes = _experience_themes(selected_experiences, selected_projects)
    clean_title = _clean_resume_title(target_title)
    parts = [f"{clean_title}{years_text}."]

    priority_keywords = ats_plan.priority_keywords[:8] if ats_plan else []
    if priority_keywords:
        keyword_text = ", ".join(priority_keywords[:5])
        parts.append(f"Skilled in {keyword_text}.")

    planned_skills = ats_plan.must_include_skills[:5] if ats_plan else strongest_skills[:4]
    if planned_skills and len(priority_keywords) < 5:
        parts.append(f"Core strengths include {', '.join(planned_skills[:3])}.")
    if themes:
        parts.append(f"Background includes {', '.join(themes[:3])}.")

    summary = " ".join(part for part in parts if part).strip()
    summary = _trim_words(summary, MAX_SUMMARY_WORDS)
    if len(normalize_terms(summary)) >= 4:
        return summary

    if profile.summary:
        return _trim_words(profile.summary.strip(), MAX_SUMMARY_WORDS)
    return _trim_words(f"{clean_title}{years_text}.", MAX_SUMMARY_WORDS)


def build_experience_entry(
    exp: WorkExperience,
    relevance_score: float,
    matched_keywords: list[str],
    jd_terms: set[str],
    locked_bullets: dict[str, str],
) -> ResumeExperienceEntry:
    """Build a deterministic experience entry using original bullets and description."""
    bullets = _build_ranked_bullets(
        section_type="experience",
        source_id=exp.id,
        original_bullets=exp.bullets,
        description=exp.description,
        jd_terms=jd_terms,
        locked_bullets=locked_bullets,
    )

    return ResumeExperienceEntry(
        source_id=exp.id,
        company=exp.company,
        title=exp.title,
        location=exp.location,
        start_date=exp.start_date,
        end_date=exp.end_date,
        is_current=exp.is_current,
        bullets=bullets,
        relevance_score=relevance_score,
    )


def build_project_entry(
    project: Project,
    relevance_score: float,
    matched_keywords: list[str],
    jd_terms: set[str],
    locked_bullets: dict[str, str],
) -> ResumeProjectEntry:
    """Build a deterministic project entry using original bullets and description."""
    bullets = _build_ranked_bullets(
        section_type="project",
        source_id=project.id,
        original_bullets=project.bullets,
        description=project.description,
        jd_terms=jd_terms,
        locked_bullets=locked_bullets,
    )

    return ResumeProjectEntry(
        source_id=project.id,
        name=project.name,
        description=project.description,
        technologies=project.technologies,
        bullets=bullets,
        relevance_score=relevance_score,
    )


def _build_jd_terms(
    parsed_jd: ParsedJD,
    emphasis: str | None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> set[str]:
    """Build normalized JD term set from structured JD fields and optional emphasis."""
    parts = [
        parsed_jd.job_title,
        " ".join(parsed_jd.required_skills),
        " ".join(parsed_jd.preferred_skills),
        " ".join(keyword.keyword for keyword in parsed_jd.keywords),
        " ".join(parsed_jd.responsibilities),
        " ".join(parsed_jd.tools_platforms),
        " ".join(parsed_jd.programming_languages),
        " ".join(parsed_jd.frameworks),
        " ".join(parsed_jd.databases),
        " ".join(parsed_jd.cloud_devops_tools),
        " ".join(parsed_jd.domain_platform_terms),
        " ".join(parsed_jd.deployment_environment_terms),
        " ".join(parsed_jd.mobile_platform_terms),
        " ".join(parsed_jd.important_exact_phrases),
        " ".join(ats_plan.priority_keywords if ats_plan else []),
        " ".join(ats_plan.must_include_responsibilities if ats_plan else []),
        emphasis or "",
    ]
    return normalize_terms(" ".join(part for part in parts if part))


def _score_experience(exp: WorkExperience, jd_terms: set[str], skill_overlap: float) -> tuple[float, list[str]]:
    fields = [
        (exp.title, 0.30),
        (exp.company, 0.10),
        (exp.description or "", 0.20),
        (" ".join(exp.bullets), 0.30),
        (" ".join(exp.tags), 0.10),
    ]
    return _weighted_overlap(fields, jd_terms, skill_overlap)


def _score_project(project: Project, jd_terms: set[str], skill_overlap: float) -> tuple[float, list[str]]:
    fields = [
        (project.name, 0.30),
        (project.description or "", 0.25),
        (" ".join(project.bullets), 0.20),
        (" ".join(project.technologies), 0.25),
    ]
    return _weighted_overlap(fields, jd_terms, skill_overlap)


def _weighted_overlap(
    fields: list[tuple[str, float]],
    jd_terms: set[str],
    skill_overlap: float,
) -> tuple[float, list[str]]:
    total_score = 0.0
    matched_terms: set[str] = set()

    for text, weight in fields:
        score, matches = score_text_against_jd(text, jd_terms)
        total_score += score * weight
        matched_terms.update(matches)

    total_score += min(skill_overlap * 0.15, 0.15)
    return min(total_score, 1.0), sorted(matched_terms)


def _build_ranked_bullets(
    section_type: str,
    source_id: str,
    original_bullets: list[str],
    description: str | None,
    jd_terms: set[str],
    locked_bullets: dict[str, str],
) -> list[ResumeBullet]:
    """Build deterministic bullets with stable IDs and exact locked-bullet preservation."""
    candidates = list(original_bullets)
    if description:
        description_text = description.strip()
        if description_text and description_text not in candidates:
            candidates.append(description_text)

    scored_candidates: list[tuple[int, float, list[str], str]] = []
    for original_index, text in enumerate(candidates):
        score, matches = score_text_against_jd(text, jd_terms)
        scored_candidates.append((original_index, score, matches, text.strip()))

    scored_candidates.sort(key=lambda item: (-item[1], item[0]))
    selected_candidates = scored_candidates[:MAX_BULLETS_PER_EXPERIENCE]

    selected_by_slot: dict[int, tuple[float, list[str], str]] = {
        slot: (score, matches, text)
        for slot, (_, score, matches, text) in enumerate(selected_candidates)
    }

    max_locked_slot = max(_locked_bullet_slots(section_type, source_id, locked_bullets), default=-1)
    slot_count = max(len(selected_candidates), max_locked_slot + 1)

    bullets: list[ResumeBullet] = []
    for slot in range(slot_count):
        bullet_id = _stable_bullet_id(section_type, source_id, slot)
        selected = selected_by_slot.get(slot)

        if bullet_id in locked_bullets:
            bullets.append(
                ResumeBullet(
                    id=bullet_id,
                    text=locked_bullets[bullet_id],
                    status=BulletStatus.LOCKED,
                    matched_keywords=selected[1] if selected else [],
                    source_id=source_id,
                )
            )
            continue

        if not selected:
            continue

        _, matches, text = selected
        if not text:
            continue

        bullets.append(
            ResumeBullet(
                id=bullet_id,
                text=text,
                original_text=text,
                status=BulletStatus.PENDING,
                matched_keywords=matches,
                source_id=source_id,
            )
        )

    return bullets


def _build_skill_groups(
    profile: MasterProfile,
    jd_terms: set[str],
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> list[ResumeSkillGroup]:
    """Group skills by category, ordering JD-relevant skills first inside each group."""
    grouped: dict[str, list[tuple[float, int, str]]] = {}
    for index, skill in enumerate(profile.skills):
        category = skill.category or "Technical Skills"
        score, _ = score_text_against_jd(skill.name, jd_terms)
        grouped.setdefault(category, []).append((score, index, skill.name))

    groups: list[ResumeSkillGroup] = []
    for category, items in grouped.items():
        ordered = [name for _, _, name in sorted(items, key=lambda item: (-item[0], item[1]))]
        groups.append(ResumeSkillGroup(category=category, skills=ordered))

    if ats_plan:
        technical_skills = _dedupe_strings([*ats_plan.must_include_skills, *ats_plan.must_include_tools_platforms])
        if technical_skills:
            existing = next((group for group in groups if group.category.lower() in {"technical skills", "programming languages"}), None)
            if existing:
                existing.skills = _dedupe_strings([*technical_skills, *existing.skills])
            else:
                groups.insert(0, ResumeSkillGroup(category="Technical Skills", skills=technical_skills))

    groups.sort(key=lambda group: (-_group_skill_score(group, jd_terms), group.category.lower()))
    return groups


def _group_skill_score(group: ResumeSkillGroup, jd_terms: set[str]) -> float:
    score, _ = score_text_against_jd(" ".join(group.skills), jd_terms)
    return score


def _top_skill_names(skill_groups: list[ResumeSkillGroup]) -> list[str]:
    names: list[str] = []
    for group in skill_groups:
        for skill in group.skills:
            if skill not in names:
                names.append(skill)
            if len(names) >= 4:
                return names
    return names


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _experience_themes(
    experiences: list[WorkExperience],
    projects: list[Project],
) -> list[str]:
    terms = Counter[str]()
    for exp in experiences:
        terms.update(normalize_terms(f"{exp.title} {' '.join(exp.tags)} {exp.description or ''}"))
    for project in projects:
        terms.update(normalize_terms(f"{project.name} {project.description or ''} {' '.join(project.technologies)}"))
    return [term for term, _ in terms.most_common(5)]


def _infer_years_of_experience(experiences: list[WorkExperience]) -> int | None:
    starts: list[date] = []
    latest: list[date] = []
    for exp in experiences:
        start = _parse_partial_date(exp.start_date)
        end = date.today() if exp.is_current else _parse_partial_date(exp.end_date)
        if start:
            starts.append(start)
        if end:
            latest.append(end)

    if not starts or not latest:
        return None

    total_days = max(latest) - min(starts)
    if total_days.days <= 0:
        return None
    return max(total_days.days // 365, 1)


def _parse_partial_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            if fmt == "%Y-%m":
                year, month = value.split("-")
                return date(int(year), int(month), 1)
            return date.fromisoformat(value)
        except ValueError:
            continue
    return None


def _fallback_target_title(
    profile: MasterProfile,
    parsed_jd: ParsedJD,
    role_family: str,
) -> str:
    if parsed_jd.job_title:
        return parsed_jd.job_title
    if profile.work_experience:
        return profile.work_experience[0].title
    if profile.projects:
        return f"{profile.projects[0].name} Contributor"
    return "Resume Candidate"


def _trim_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(".,;:") + "."


def _stable_bullet_id(section_type: str, source_id: str, index: int) -> str:
    return f"{section_type}:{source_id}:{index}"


def _locked_bullet_slots(
    section_type: str,
    source_id: str,
    locked_bullets: dict[str, str],
) -> set[int]:
    prefix = f"{section_type}:{source_id}:"
    slots: set[int] = set()
    for bullet_id in locked_bullets:
        if not bullet_id.startswith(prefix):
            continue
        try:
            slots.add(int(bullet_id.rsplit(":", 1)[1]))
        except ValueError:
            continue
    return slots


def _clean_resume_title(title: str) -> str:
    """Clean resume title by removing labels like 'Designation:'."""
    cleaned = re.sub(r"^\s*(designation|job\s*title|title|role)\s*:\s*", "", title, flags=re.IGNORECASE)
    return cleaned.strip(" :-\t")
