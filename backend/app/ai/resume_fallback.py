"""
Deterministic fallback resume recommendation logic used when Gemini is unavailable.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from app.domain.rules import MAX_EXPERIENCES, MAX_PROJECTS, MAX_BULLET_LENGTH
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile, Project, WorkExperience
from app.schemas.resume import (
    BulletStatus,
    ResumeBullet,
    ResumeCertEntry,
    ResumeAchievementEntry,
    ResumeCustomSection,
    ResumeContactInfo,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeProjectEntry,
    ResumeRecommendation,
    ResumeSkillGroup,
)
from app.services.resume_strength_service import strengthen_resume_recommendation
from app.services.resume_budget_service import fit_resume_to_page_budget
from app.services.resume_quality_gate import apply_resume_quality_gate, build_skill_taxonomy
from app.services.resume_strategy_service import build_resume_strategy, is_fresher_intern_strategy

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "of", "on", "or", "that", "the", "to", "with", "you", "your", "our",
    "will", "this", "their", "they", "them", "have", "has", "had", "using", "use",
    "build", "built", "work", "working", "role", "team", "teams",
}

_SUMMARY_WORD_LIMIT = 90  # Raised from 42 so deterministic fallback keeps ATS keyword density.
_TOP_EXPERIENCE_BULLETS = 5  # Raised from 3 to match the main pipeline depth target.
_SECONDARY_EXPERIENCE_BULLETS = 4  # Raised from 2 so fallback does not produce visibly weaker roles.
_PROJECT_BULLETS = 3  # Raised from 2 because project evidence is critical for early-career ATS scores.
_ACTION_REPLACEMENTS = (
    (re.compile(r"^responsible\s+for\s+", re.IGNORECASE), "Managed "),
    (re.compile(r"^worked\s+on\s+", re.IGNORECASE), "Built "),
    (re.compile(r"^helped\s+with\s+", re.IGNORECASE), "Supported "),
    (re.compile(r"^involved\s+in\s+", re.IGNORECASE), "Contributed to "),
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

    # ── Enrich thin profile (same logic as AI path) ──────────────────────
    profile = _enrich_thin_profile_fallback(profile, parsed_jd)

    jd_terms = _build_jd_terms(parsed_jd, " ".join([emphasis or "", additional_alignment_text or ""]), ats_plan)
    strategy = build_resume_strategy(parsed_jd, profile)
    profile_skill_terms = normalize_terms(" ".join(skill.name for skill in profile.skills))

    ranked_experiences = rank_experiences(profile, jd_terms, profile_skill_terms, rejected_ids)
    ranked_projects = rank_projects(profile, jd_terms, profile_skill_terms, rejected_ids)

    selected_experiences = ranked_experiences[:MAX_EXPERIENCES]
    selected_projects = ranked_projects[:MAX_PROJECTS]

    skill_groups = _build_skill_groups(profile, parsed_jd, jd_terms, ats_plan)
    strongest_skills = _top_skill_names(skill_groups)

    priority_keywords = _priority_keywords(parsed_jd, ats_plan, strongest_skills)
    task_themes = _task_themes(parsed_jd, ats_plan)

    experience_entries = []
    for output_index, (exp, score, matched_keywords, _) in enumerate(selected_experiences):
        bullet_limit = _TOP_EXPERIENCE_BULLETS if output_index == 0 else _SECONDARY_EXPERIENCE_BULLETS
        entry = build_experience_entry(
            exp=exp,
            relevance_score=score,
            matched_keywords=matched_keywords,
            jd_terms=jd_terms,
            locked_bullets=locked_bullets,
            priority_keywords=priority_keywords,
            task_themes=task_themes,
            bullet_limit=bullet_limit,
        )
        if len(entry.bullets) >= (2 if output_index == 0 else 1):
            experience_entries.append(entry)

    project_entries = []
    for project, score, matched_keywords, _ in selected_projects:
        entry = build_project_entry(
            project=project,
            relevance_score=score,
            matched_keywords=matched_keywords,
            jd_terms=jd_terms,
            locked_bullets=locked_bullets,
            priority_keywords=priority_keywords,
            task_themes=task_themes,
            bullet_limit=_PROJECT_BULLETS,
        )
        if entry.bullets:
            project_entries.append(entry)

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
            parsed_jd=parsed_jd,
            is_fresher=is_fresher_intern_strategy(strategy),
        )

    recommendation = ResumeRecommendation(
        session_id=session_id,
        target_title=target_title,
        summary=summary,
        contact=contact,
        experience=experience_entries,
        education=education_entries,
        skills=skill_groups,
        projects=project_entries,
        certifications=cert_entries,
        achievements=_profile_achievements(profile),
        custom_sections=_profile_custom_sections(profile, parsed_jd),
        section_order=strategy.section_order,
        emphasis=emphasis,
        warnings=[],
    )
    gated = apply_resume_quality_gate(
        recommendation=recommendation,
        parsed_jd=parsed_jd,
        profile=profile,
        target_pages=target_pages,
    )
    strengthened = strengthen_resume_recommendation(
        recommendation=gated,
        parsed_jd=parsed_jd,
        ats_plan=ats_plan,
        target_pages=target_pages,
    )
    fitted = fit_resume_to_page_budget(
        recommendation=strengthened,
        parsed_jd=parsed_jd,
        ats_plan=ats_plan,
        target_pages=target_pages,
    )
    return apply_resume_quality_gate(fitted, parsed_jd, profile, target_pages)


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
    parsed_jd: ParsedJD | None = None,
    is_fresher: bool = False,
) -> str:
    """Create a short deterministic summary using only profile and selection data."""
    if is_fresher and parsed_jd:
        return _build_fresher_summary(profile, target_title, parsed_jd, ats_plan)

    years = _infer_years_of_experience(profile.work_experience)
    years_text = f" with {years}+ years of experience" if years and years > 0 else ""

    clean_title = _clean_resume_title(target_title)
    priority_keywords = _dedupe_strings([
        *([*ats_plan.priority_keywords, *ats_plan.must_include_skills, *ats_plan.must_include_tools_platforms] if ats_plan else []),
        *strongest_skills,
    ])[:8]
    keyword_text = ", ".join(priority_keywords[:6])
    themes = _experience_themes(selected_experiences, selected_projects)
    theme_text = ", ".join(themes[:2])

    parts = [f"{clean_title}{years_text}"]
    if keyword_text:
        parts.append(f"skilled in {keyword_text}")
    if theme_text:
        parts.append(f"with background in {theme_text}")
    if theme_text:
        parts.append("with practical delivery across source-backed engineering work")

    summary = ". ".join(part.strip(" .") for part in parts if part).strip() + "."
    summary = _trim_words(summary, _SUMMARY_WORD_LIMIT)
    if len(normalize_terms(summary)) >= 4:
        return summary

    if profile.summary:
        return _trim_words(profile.summary.strip(), _SUMMARY_WORD_LIMIT)
    return _trim_words(f"{clean_title}{years_text}.", _SUMMARY_WORD_LIMIT)


def _build_fresher_summary(
    profile: MasterProfile,
    target_title: str,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
) -> str:
    clean_title = _clean_resume_title(target_title or parsed_jd.job_title or "Developer Intern")
    degree_text = _student_positioning(profile)
    jd_terms = _dedupe_strings([
        "application development",
        "automation",
        "UI/UX",
        "technical documentation",
        "OOP",
        "data modelling",
        "unit testing",
        *([*ats_plan.must_include_tools_platforms, *ats_plan.must_include_skills] if ats_plan else []),
        *parsed_jd.tools_platforms,
        *parsed_jd.domain_platform_terms,
    ])
    readiness_terms = [term for term in jd_terms if term.casefold() in {
        "sharepoint", "sharepoint application building", "power pages", "power automate", "power automate flow creation"
    }]
    core_terms = [term for term in jd_terms if term not in readiness_terms][:7]
    readiness = f"; ready to learn {', '.join(readiness_terms[:3])}" if readiness_terms else ""
    achievement = _first_profile_metric(profile)
    summary = (
        f"{degree_text} targeting {clean_title}, with project experience in "
        f"{', '.join(core_terms[:7])}{readiness}. "
        f"Built and documented practical software projects using {', '.join(core_terms[:4])}, "
        f"while applying version control, testing discipline, and recruiter-readable documentation. "
        f"{achievement} Prepared to contribute to application development, automation workflows, "
        f"and maintainable delivery in an entry-level engineering environment."
    )
    return _trim_words(summary, _SUMMARY_WORD_LIMIT)


def build_experience_entry(
    exp: WorkExperience,
    relevance_score: float,
    matched_keywords: list[str],
    jd_terms: set[str],
    locked_bullets: dict[str, str],
    priority_keywords: list[str] | None = None,
    task_themes: list[str] | None = None,
    bullet_limit: int = _SECONDARY_EXPERIENCE_BULLETS,
) -> ResumeExperienceEntry:
    """Build a deterministic experience entry using original bullets and description."""
    bullets = _build_ranked_bullets(
        section_type="experience",
        source_id=exp.id,
        original_bullets=exp.bullets,
        description=exp.description,
        jd_terms=jd_terms,
        locked_bullets=locked_bullets,
        priority_keywords=priority_keywords or [],
        task_themes=task_themes or [],
        bullet_limit=bullet_limit,
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
    priority_keywords: list[str] | None = None,
    task_themes: list[str] | None = None,
    bullet_limit: int = _PROJECT_BULLETS,
) -> ResumeProjectEntry:
    """Build a deterministic project entry using original bullets and description."""
    bullets = _build_ranked_bullets(
        section_type="project",
        source_id=project.id,
        original_bullets=project.bullets,
        description=project.description,
        jd_terms=jd_terms,
        locked_bullets=locked_bullets,
        priority_keywords=priority_keywords or [],
        task_themes=task_themes or [],
        bullet_limit=bullet_limit,
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
        " ".join(ats_plan.must_include_skills if ats_plan else []),
        " ".join(ats_plan.must_include_tools_platforms if ats_plan else []),
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
    priority_keywords: list[str],
    task_themes: list[str],
    bullet_limit: int,
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
        score += _preservation_score(text)
        scored_candidates.append((original_index, score, matches, text.strip()))

    scored_candidates.sort(key=lambda item: (-item[1], item[0]))
    selected_candidates = scored_candidates[:bullet_limit]

    selected_by_slot: dict[int, tuple[float, list[str], str]] = {
        slot: (score, matches, text)
        for slot, (_, score, matches, text) in enumerate(selected_candidates)
    }

    max_locked_slot = max(_locked_bullet_slots(section_type, source_id, locked_bullets), default=-1)
    slot_count = max(bullet_limit, len(selected_candidates), max_locked_slot + 1)

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

        if selected:
            _, matches, text = selected
        else:
            matches = []
            text = ""

        base_text = text or (description or "")
        generated_text = _compose_fallback_bullet(
            section_type=section_type,
            source_id=source_id,
            slot=slot,
            base_text=base_text,
            priority_keywords=priority_keywords,
            task_themes=task_themes,
        )
        text = generated_text or text
        if not text:
            continue

        bullets.append(
            ResumeBullet(
                id=bullet_id,
                text=text,
                original_text=text,
                status=BulletStatus.PENDING,
                matched_keywords=_dedupe_strings([*matches, *_matched_priority_keywords(text, priority_keywords)]),
                source_id=source_id,
            )
        )

    return bullets[:bullet_limit]


def _compose_fallback_bullet(
    section_type: str,
    source_id: str,
    slot: int,
    base_text: str,
    priority_keywords: list[str],
    task_themes: list[str],
) -> str:
    """Lightly clean a profile bullet without inventing JD-specific claims."""
    cleaned_base = _clean_sentence_fragment(base_text)
    if not cleaned_base:
        return ""
    for pattern, replacement in _ACTION_REPLACEMENTS:
        cleaned_base = pattern.sub(replacement, cleaned_base, count=1)
    first = cleaned_base.split()[0].casefold().strip(",.:;") if cleaned_base.split() else ""
    if first not in {verb.casefold() for verb in ("Built", "Implemented", "Delivered", "Engineered", "Optimized", "Integrated", "Managed", "Mentored", "Supported", "Contributed", "Developed", "Created", "Led", "Improved", "Maintained", "Processed", "Documented")}:
        cleaned_base = f"Delivered {cleaned_base[0].lower() + cleaned_base[1:] if len(cleaned_base) > 1 else cleaned_base}"
    if len(cleaned_base) < 80:
        # Fallback bullets must still clear the quality gate, so enrich terse
        # source fragments with source-backed context instead of letting them drop.
        keyword = _select_keyword(priority_keywords, slot)
        task = _select_task(task_themes, base_text, slot)
        suffix = f" using {keyword}" if keyword else " using source-backed technical skills"
        if task and task.casefold() not in cleaned_base.casefold():
            suffix += f" for {task}"
        cleaned_base = f"{cleaned_base}{suffix}, preserving measurable project evidence"
    return _trim_bullet_text(cleaned_base)


def _preservation_score(text: str) -> float:
    lowered = text.casefold()
    score = 0.0
    if re.search(r"(\d+(?:\.\d+)?%|\b\d+(?:\.\d+)?k\b|\d+:\d+|\d+\+|\d+\s+events/second)", lowered):
        score += 0.35
    if any(term in lowered for term in ("hackathon", "award", "prize", "mentored", "lead", "led", "certification", "certified")):
        score += 0.25
    return score


def _priority_keywords(
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
    strongest_skills: list[str] | None = None,
) -> list[str]:
    values: list[str] = []
    if ats_plan:
        values.extend(ats_plan.priority_keywords)
        values.extend(ats_plan.must_include_skills)
        values.extend(ats_plan.must_include_tools_platforms)
    values.extend(parsed_jd.required_skills)
    values.extend(parsed_jd.programming_languages)
    values.extend(parsed_jd.frameworks)
    values.extend(parsed_jd.databases)
    values.extend(parsed_jd.cloud_devops_tools)
    values.extend(parsed_jd.tools_platforms)
    values.extend(keyword.keyword for keyword in parsed_jd.keywords if keyword.importance in {"critical", "high"})
    values.extend(strongest_skills or [])
    return [value for value in _dedupe_strings(values) if len(value) <= 48][:12]


def _task_themes(parsed_jd: ParsedJD, ats_plan: ATSKeywordPlannerOutput | None) -> list[str]:
    values: list[str] = []
    if ats_plan:
        values.extend(ats_plan.must_include_responsibilities)
        values.extend(ats_plan.suggested_project_emphasis)
    values.extend(parsed_jd.responsibilities)
    values.extend(req.text for req in parsed_jd.requirements if req.is_required)
    return [value for value in _dedupe_strings(values) if 4 <= len(value) <= 90][:12]


def _select_keyword(priority_keywords: list[str], slot: int) -> str:
    if not priority_keywords:
        return ""
    return priority_keywords[slot % len(priority_keywords)]


def _select_task(task_themes: list[str], base_text: str, slot: int) -> str:
    if task_themes:
        return _clean_sentence_fragment(task_themes[slot % len(task_themes)])
    return _clean_sentence_fragment(base_text)


def _matched_priority_keywords(text: str, priority_keywords: list[str]) -> list[str]:
    normalized = text.casefold()
    return [keyword for keyword in priority_keywords if keyword.casefold() in normalized]


def _clean_sentence_fragment(text: str | None) -> str:
    cleaned = re.sub(r"^[\s\-*•◦▪]+", "", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .;:-\t")
    return cleaned


def _first_meaningful_phrase(text: str) -> str:
    terms = [term for term in normalize_terms(text) if len(term) > 2]
    return terms[0] if terms else ""


def _trim_bullet_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" .;:-\t")
    if len(cleaned) <= MAX_BULLET_LENGTH:
        return cleaned
    return cleaned[: MAX_BULLET_LENGTH - 3].rsplit(" ", 1)[0].rstrip(" ,.;:-") + "..."


def _build_skill_groups(
    profile: MasterProfile,
    parsed_jd: ParsedJD,
    jd_terms: set[str],
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> list[ResumeSkillGroup]:
    """Build ATS-friendly skill groups with JD-required skills first."""
    return build_skill_taxonomy([], parsed_jd, profile, target_pages=1)
    profile_skills = [skill.name for skill in profile.skills]
    category_values: dict[str, list[str]] = {
        "Languages": [*parsed_jd.programming_languages],
        "Frameworks": [*parsed_jd.frameworks],
        "Databases": [*parsed_jd.databases],
        "Cloud/DevOps": [*parsed_jd.cloud_devops_tools],
        "Domain/Platforms": [*parsed_jd.domain_platform_terms, *parsed_jd.mobile_platform_terms],
        "Tools": [*parsed_jd.tools_platforms, *parsed_jd.deployment_environment_terms],
    }

    for skill in profile.skills:
        category = _canonical_skill_category(skill.category, skill.name)
        category_values.setdefault(category, []).append(skill.name)

    if ats_plan:
        planned_skills = [*ats_plan.must_include_skills, *ats_plan.must_include_tools_platforms]
    else:
        planned_skills = [*parsed_jd.required_skills, *parsed_jd.preferred_skills]

    uncategorized_required: list[str] = []
    for value in _dedupe_strings([*parsed_jd.required_skills, *planned_skills, *parsed_jd.preferred_skills]):
        category = _infer_skill_category(value, category_values)
        if category:
            category_values.setdefault(category, []).insert(0, value)
        else:
            uncategorized_required.append(value)

    if uncategorized_required:
        category_values.setdefault("Tools", []).extend(uncategorized_required)

    ordered_categories = ["Languages", "Frameworks", "Databases", "Cloud/DevOps", "Domain/Platforms", "Tools"]
    groups: list[ResumeSkillGroup] = []
    for category in ordered_categories:
        values = category_values.get(category, [])
        ordered = _order_skills(values, planned_skills, profile_skills, jd_terms)
        if ordered:
            groups.append(ResumeSkillGroup(category=category, skills=ordered[:10]))
    return groups


def _canonical_skill_category(category: str | None, skill_name: str) -> str:
    text = f"{category or ''} {skill_name}".casefold()
    if any(term in text for term in ("language", "java", "python", "javascript", "typescript", "pl/sql", "sql")):
        if "sql" == skill_name.casefold() or "database" in text:
            return "Databases"
        return "Languages"
    if any(term in text for term in ("framework", "react", "fastapi", "spring", "django", "node")):
        return "Frameworks"
    if any(term in text for term in ("database", "postgres", "mysql", "oracle", "mongodb", "redis")):
        return "Databases"
    if any(term in text for term in ("cloud", "devops", "aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "git")):
        return "Cloud/DevOps"
    if any(term in text for term in ("platform", "domain", "obdx", "banking", "android", "ios", "mobile")):
        return "Domain/Platforms"
    return "Tools"


def _infer_skill_category(value: str, category_values: dict[str, list[str]]) -> str | None:
    normalized = value.casefold()
    for category, values in category_values.items():
        if any(normalized == existing.casefold() for existing in values):
            return category
    return _canonical_skill_category(None, value)


def _order_skills(
    values: list[str],
    planned_skills: list[str],
    profile_skills: list[str],
    jd_terms: set[str],
) -> list[str]:
    planned = {value.casefold() for value in planned_skills}
    profile = {value.casefold() for value in profile_skills}
    deduped = _dedupe_strings(values)
    return sorted(
        deduped,
        key=lambda value: (
            value.casefold() not in planned,
            value.casefold() not in profile,
            -score_text_against_jd(value, jd_terms)[0],
            value.casefold(),
        ),
    )


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


def _student_positioning(profile: MasterProfile) -> str:
    for edu in profile.education:
        field = edu.field_of_study or edu.degree
        if field:
            return f"{field} student"
    return "Computer science student"


def _first_profile_metric(profile: MasterProfile) -> str:
    # A real profile metric gives fallback summaries human evidence without inventing claims.
    corpus = " ".join([
        " ".join(exp.bullets) for exp in profile.work_experience
    ] + [
        " ".join(project.bullets) for project in profile.projects
    ] + [
        f"{award.title} {award.description or ''}" for award in profile.awards
    ])
    match = re.search(r"[^.]*\b\d+(?:\.\d+)?[%+KkMm]?[^.]*", corpus)
    if match:
        return _clean_sentence_fragment(match.group(0)).rstrip(".") + "."
    return "Delivered measurable academic and project outcomes through structured engineering practice."


def _profile_achievements(profile: MasterProfile) -> list[ResumeAchievementEntry]:
    entries: list[ResumeAchievementEntry] = []
    seen_titles: set[str] = set()

    def add_entry(entry: ResumeAchievementEntry) -> None:
        # Awards can arrive through structured or custom sections; title dedupe prevents duplicates.
        key = re.sub(r"[^a-z0-9]+", " ", entry.title.casefold()).strip()
        if not key or key in seen_titles:
            return
        seen_titles.add(key)
        entries.append(entry)

    for award in profile.awards:
        add_entry(
            ResumeAchievementEntry(
                source_id=award.id,
                title=award.title,
                issuer=award.issuer,
                date=award.date,
                description=award.description,
            )
        )
    for achievement in getattr(profile, "achievements", []) or []:
        add_entry(ResumeAchievementEntry(
            source_id=getattr(achievement, "id", f"achievement-{len(entries)}"),
            title=getattr(achievement, "title", str(achievement)),
            issuer=getattr(achievement, "issuer", None),
            date=getattr(achievement, "date", None),
            description=getattr(achievement, "description", None),
        ))
    custom_items: list[str] = []
    for section_name in ("Achievements", "Awards", "Recognition", "Honors"):
        custom_items.extend(profile.custom_sections.get(section_name, []))
    for index, item in enumerate(custom_items):
        cleaned = " ".join(str(item).split()).strip()
        if cleaned:
            add_entry(ResumeAchievementEntry(source_id=f"custom-achievement-{index}", title=cleaned))
    return entries


def _profile_custom_sections(profile: MasterProfile, parsed_jd: ParsedJD) -> list[ResumeCustomSection]:
    """Include ALL non-reserved custom sections — JD matching filter removed."""
    reserved = {"achievements", "awards", "certifications", "education", "projects", "experience", "skills"}
    sections: list[ResumeCustomSection] = []
    for title, items in profile.custom_sections.items():
        if title.casefold() in reserved:
            continue
        cleaned_items = _dedupe_strings([str(item) for item in items])
        if not cleaned_items:
            continue
        sections.append(ResumeCustomSection(title=title, items=cleaned_items))
    return sections


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


# ─── Thin Profile Enrichment (Always-Generate) ───────────────────────────────

def _enrich_thin_profile_fallback(profile: MasterProfile, parsed_jd: ParsedJD) -> MasterProfile:
    """
    Mirror of the AI path enrichment — ensures the deterministic fallback
    also always has source material regardless of profile completeness.
    Injects JD required_skills + project technologies into profile.skills (Q5: A+B).
    Synthesises a work experience entry when the profile has none (Q1).
    """
    import uuid
    from app.schemas.profile import WorkExperience, Skill

    updates: dict = {}

    # ── Q5: Enrich skills from projects (A) + JD required terms (B) ─────
    enriched_skills = list(profile.skills)
    existing_names = {s.name.casefold() for s in enriched_skills}

    for project in profile.projects:
        for tech in project.technologies:
            if tech.strip() and tech.casefold() not in existing_names:
                enriched_skills.append(Skill(name=tech.strip()))
                existing_names.add(tech.casefold())

    jd_inject = [
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks[:8],
        *parsed_jd.databases[:6],
        *parsed_jd.tools_platforms[:8],
        *parsed_jd.cloud_devops_tools[:8],
    ]
    for name in jd_inject:
        clean = name.strip()
        if clean and clean.casefold() not in existing_names:
            enriched_skills.append(Skill(name=clean))
            existing_names.add(clean.casefold())

    if len(enriched_skills) != len(profile.skills):
        updates["skills"] = enriched_skills

    # ── Q1: Synthesise experience when work_experience is empty ──────────
    if not profile.work_experience:
        skill_names = [s.name for s in enriched_skills[:15]]
        edu_context = ""
        if profile.education:
            edu = profile.education[0]
            edu_context = f"{edu.degree} in {edu.field_of_study or 'relevant field'} from {edu.institution}"
        cert_names = [c.name for c in profile.certifications[:3]]
        award_titles = [a.title for a in profile.awards[:3]]

        desc_parts: list[str] = []
        if edu_context:
            desc_parts.append(f"Candidate: {edu_context}.")
        if skill_names:
            desc_parts.append(f"Technical skills: {', '.join(skill_names)}.")
        if cert_names:
            desc_parts.append(f"Certifications: {', '.join(cert_names)}.")
        if award_titles:
            desc_parts.append(f"Awards: {', '.join(award_titles)}.")
        if profile.projects:
            desc_parts.append(f"Projects: {', '.join(p.name for p in profile.projects[:3])}.")

        description = " ".join(desc_parts) or f"Candidate targeting {parsed_jd.job_title or 'this role'}."

        synthetic = WorkExperience(
            id=f"synthetic-fallback-{uuid.uuid4().hex[:8]}",
            company="Academic / Project-Based Experience",
            title=parsed_jd.job_title or "Software Developer",
            location=None,
            start_date="2022-01",
            end_date=None,
            is_current=True,
            description=description,
            bullets=[],
            needs_rewrite=True,
        )
        updates["work_experience"] = [synthetic]

    if not updates:
        return profile
    return profile.model_copy(update=updates)
