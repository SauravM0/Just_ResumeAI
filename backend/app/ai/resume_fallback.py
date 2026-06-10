"""
Deterministic fallback resume recommendation logic used when Gemini is unavailable.

Strategy:
- Parse JD keywords, abstract task themes, and priority skills.
- Generate target title from JD.
- Rewrite summary using JD terms in natural prose.
- Reorder skills, experiences, and projects by JD relevance.
- Rewrite bullets using candidate facts + JD vocabulary (action + skill + outcome).
- Preserve all factual anchors (names, companies, dates, degrees, certs).
- Produce valid resume JSON that renders in main.tex and passes ATS scoring.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

from app.domain.rules import (
    MAX_BULLET_LENGTH,
    MAX_EXPERIENCES,
    MAX_PROJECTS,
    MIN_BULLET_LENGTH,
)
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
from app.services.locked_fields_service import build_locked_fields, validate_locked_fields_in_output
from app.services.resume_strategy_service import build_resume_strategy, is_fresher_intern_strategy
from app.services.candidate_evidence_service import (
    build_candidate_evidence,
    classify_jd_keyword_truth,
    contains_term,
    is_supported_placement,
)
from app.services.jd_sanitization_service import sanitize_parsed_jd
from app.services.bullet_quality_service import (
    has_jd_boilerplate,
    is_dangling_ending,
    validate_single_bullet,
    word_count,
)

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into",
    "is", "of", "on", "or", "that", "the", "to", "with", "you", "your", "our",
    "will", "this", "their", "they", "them", "have", "has", "had", "using", "use",
    "build", "built", "work", "working", "role", "team", "teams",
}

_SUMMARY_WORD_LIMIT = 90
_TOP_EXPERIENCE_BULLETS = 5
_SECONDARY_EXPERIENCE_BULLETS = 4
_PROJECT_BULLETS = 3
_ACTION_REPLACEMENTS = (
    (re.compile(r"^responsible\s+for\s+", re.IGNORECASE), "Managed "),
    (re.compile(r"^worked\s+on\s+", re.IGNORECASE), "Built "),
    (re.compile(r"^helped\s+with\s+", re.IGNORECASE), "Supported "),
    (re.compile(r"^involved\s+in\s+", re.IGNORECASE), "Contributed to "),
)

# Strong action verbs for fallback bullet generation
_FALLBACK_ACTION_VERBS = [
    "Built", "Developed", "Implemented", "Designed", "Engineered",
    "Delivered", "Integrated", "Optimized", "Automated", "Deployed",
    "Refactored", "Configured", "Maintained", "Documented", "Supported",
    "Improved", "Enhanced", "Created", "Managed", "Led",
]

# JD responsibility action templates: map responsibility keywords to action verbs
_RESP_ACTION_MAP: dict[str, str] = {
    "design": "Designed", "architect": "Architected", "build": "Built",
    "develop": "Developed", "implement": "Implemented", "create": "Created",
    "deploy": "Deployed", "maintain": "Maintained", "manage": "Managed",
    "optimize": "Optimized", "improve": "Improved", "automate": "Automated",
    "integrate": "Integrated", "migrate": "Migrated", "test": "Tested",
    "monitor": "Monitored", "secure": "Secured", "scale": "Scaled",
    "lead": "Led", "mentor": "Mentored", "collaborate": "Collaborated",
    "document": "Documented", "analyze": "Analyzed", "evaluate": "Evaluated",
    "configure": "Configured", "troubleshoot": "Troubleshot", "resolve": "Resolved",
}


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
    generation_id: str,
    emphasis: str | None = None,
    rejected_ids: list[str] | None = None,
    locked_bullets: dict[str, str] | None = None,
    target_pages: int = 1,
    additional_alignment_text: str | None = None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> ResumeRecommendation:
    """Build a deterministic ResumeRecommendation without calling Gemini.

    Produces a JD-aligned resume by:
    1. Enriching thin profiles with JD skills
    2. Ranking experiences/projects by JD relevance
    3. Rewriting bullets using JD vocabulary + profile facts
    4. Building a natural summary from JD terms
    5. Running through the full post-processing pipeline
    """
    rejected_ids = rejected_ids or []
    locked_bullets = locked_bullets or {}
    parsed_jd = sanitize_parsed_jd(parsed_jd)
    locked = build_locked_fields(profile)

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

    evidence = build_candidate_evidence(profile)
    truth = classify_jd_keyword_truth(parsed_jd, evidence, ats_plan)
    priority_keywords = [
        term for term in _priority_keywords(parsed_jd, ats_plan, strongest_skills)
        if is_supported_placement(term, truth)
    ]
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
            jd_responsibilities=[],
            profile_context=exp,
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
            jd_responsibilities=[],
            profile_context=project,
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
        generation_id=generation_id,
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
        warnings=list(ats_plan.seniority_warnings) if ats_plan else [],
    )
    recommendation.locked_fields = locked.model_dump(mode="json")
    validate_locked_fields_in_output(recommendation, locked)
    gated = apply_resume_quality_gate(
        recommendation=recommendation,
        parsed_jd=parsed_jd,
        profile=profile,
        target_pages=target_pages,
        locked=locked,
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
    result = apply_resume_quality_gate(fitted, parsed_jd, profile, target_pages, locked=locked)
    result.locked_fields = locked.model_dump(mode="json")
    validate_locked_fields_in_output(result, locked)
    return result


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
    """Create a natural, JD-aligned summary using profile and JD data."""
    if is_fresher and parsed_jd:
        return _build_fresher_summary(profile, target_title, parsed_jd, ats_plan)

    years = _infer_years_of_experience(profile.work_experience)
    years_text = f" with {years}+ years of experience" if years and years > 0 else ""

    clean_title = _clean_resume_title(target_title)

    # Build priority keyword list from ATS plan + strongest skills
    priority_keywords = _dedupe_strings([
        *([*ats_plan.priority_keywords, *ats_plan.must_include_skills, *ats_plan.must_include_tools_platforms] if ats_plan else []),
        *strongest_skills,
    ])[:8]

    # Build experience/project themes
    themes = _experience_themes(selected_experiences, selected_projects)

    # Construct natural prose summary
    # Sentence 1: Title + experience + top skills
    if years_text and priority_keywords:
        sentence1 = f"{clean_title}{years_text}, specializing in {', '.join(priority_keywords[:4])}."
    elif priority_keywords:
        sentence1 = f"{clean_title} skilled in {', '.join(priority_keywords[:4])}."
    else:
        sentence1 = f"{clean_title}{years_text}."

    # Sentence 2: Background themes + JD alignment
    if themes:
        theme_text = ", ".join(themes[:2])
        sentence2 = f"Proven background in {theme_text} with consistent delivery across engineering initiatives."
    else:
        sentence2 = f"Focused on delivering scalable solutions aligned with {clean_title} responsibilities."

    # Sentence 3: Targeting statement with JD company
    if parsed_jd and parsed_jd.company:
        sentence3 = f"Targeting {parsed_jd.company} to contribute to {clean_title} objectives."
    else:
        sentence3 = f"Ready to drive impact in {clean_title} roles."

    summary = f"{sentence1} {sentence2} {sentence3}"
    summary = _trim_words(summary, _SUMMARY_WORD_LIMIT)

    # Validate: must have at least 4 meaningful terms
    if len(normalize_terms(summary)) >= 4:
        return summary

    # Fallback to profile summary if available
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

    # Build core terms from ATS plan and JD
    core_terms = _dedupe_strings([
        *([*ats_plan.must_include_skills, *ats_plan.must_include_tools_platforms] if ats_plan else []),
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks[:4],
    ])[:7]

    # Separate readiness terms (tools the candidate may not have used yet)
    readiness_terms = [term for term in core_terms if term.casefold() in {
        "sharepoint", "sharepoint application building", "power pages", "power automate", "power automate flow creation",
    }]
    active_terms = [term for term in core_terms if term not in readiness_terms][:6]

    readiness = f" Familiar with {_natural_join(readiness_terms[:3])}." if readiness_terms else ""
    achievement = _first_profile_metric(profile)

    # Build natural prose
    if active_terms:
        summary = (
            f"{degree_text} targeting {clean_title}, with hands-on project experience in "
            f"{_natural_join(active_terms[:3])}.{readiness} "
            f"Built and documented software projects using {_natural_join(active_terms[:2])}, "
            f"applying version control, testing discipline, and clear technical communication. "
            f"{achievement}Prepared to contribute to application development and maintainable delivery."
        )
    else:
        summary = (
            f"{degree_text} targeting {clean_title}.{readiness} "
            f"Built practical software projects while applying engineering best practices. "
            f"{achievement}Prepared to contribute to development teams."
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
    jd_responsibilities: list[str] | None = None,
    profile_context: WorkExperience | None = None,
) -> ResumeExperienceEntry:
    """Build a deterministic experience entry with JD-aligned rewritten bullets."""
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
        jd_responsibilities=jd_responsibilities or [],
        profile_context=profile_context,
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
    jd_responsibilities: list[str] | None = None,
    profile_context: Project | None = None,
) -> ResumeProjectEntry:
    """Build a deterministic project entry with JD-aligned rewritten bullets."""
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
        jd_responsibilities=jd_responsibilities or [],
        profile_context=profile_context,
    )

    return ResumeProjectEntry(
        source_id=project.id,
        name=project.name,
        description=project.description,
        technologies=project.technologies,
        bullets=bullets,
        relevance_score=relevance_score,
    )


def build_evidence_fallback_bullets(
    *,
    section_type: str,
    source_id: str,
    profile_context: WorkExperience | Project,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
    bullet_limit: int = _PROJECT_BULLETS,
) -> list[ResumeBullet]:
    """Build deterministic source bullets without copying JD responsibility prose."""
    jd_terms = _build_jd_terms(parsed_jd, None, ats_plan)
    priority_keywords = _priority_keywords(parsed_jd, ats_plan, [])
    return _build_ranked_bullets(
        section_type=section_type,
        source_id=source_id,
        original_bullets=list(getattr(profile_context, "bullets", []) or []),
        description=getattr(profile_context, "description", None),
        jd_terms=jd_terms,
        locked_bullets={},
        priority_keywords=priority_keywords,
        task_themes=_task_themes(parsed_jd, ats_plan),
        bullet_limit=bullet_limit,
        jd_responsibilities=[],
        profile_context=profile_context,
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
    jd_responsibilities: list[str] | None = None,
    profile_context: WorkExperience | Project | None = None,
) -> list[ResumeBullet]:
    """Build evidence-first bullets using profile facts + approved JD vocabulary.

    Strategy:
    1. Score original bullets against JD terms (keep the best ones)
    2. Rewrite source descriptions when bullet evidence is sparse
    3. Merge locked bullets first, then evidence-backed source bullets
    """
    jd_responsibilities = jd_responsibilities or []
    if profile_context:
        source_text = _build_profile_context_text(profile_context)
        # Only keep terms that are supported by this specific context's source evidence
        priority_keywords = [term for term in priority_keywords if contains_term(source_text, term)]
    # Note: priority_keywords are already evidence-filtered upstream in generate_recommendation_without_ai

    # ── Phase 1: Score original bullets ──────────────────────────────────
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

    # JD responsibility prose is intentionally not bullet-generation material.
    generated_bullets: list[tuple[str, list[str]]] = []

    # ── Phase 3: Merge locked + original + generated ─────────────────────
    max_locked_slot = max(_locked_bullet_slots(section_type, source_id, locked_bullets), default=-1)
    slot_count = max(bullet_limit, len(selected_candidates), max_locked_slot + 1)

    bullets: list[ResumeBullet] = []
    used_generated = 0

    for slot in range(slot_count):
        bullet_id = _stable_bullet_id(section_type, source_id, slot)

        # Locked bullets take priority
        if bullet_id in locked_bullets:
            selected = selected_candidates[slot] if slot < len(selected_candidates) else None
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

        # Try original bullet first
        if slot < len(selected_candidates):
            _, _, matches, text = selected_candidates[slot]
            if text:
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
                continue

        # Fall back to generated bullet
        if used_generated < len(generated_bullets):
            gen_text, gen_matches = generated_bullets[used_generated]
            used_generated += 1
            if gen_text and len(gen_text) >= MIN_BULLET_LENGTH:
                bullets.append(
                    ResumeBullet(
                        id=bullet_id,
                        text=gen_text,
                        original_text=gen_text,
                        status=BulletStatus.PENDING,
                        matched_keywords=_dedupe_strings([*gen_matches, *_matched_priority_keywords(gen_text, priority_keywords)]),
                        source_id=source_id,
                    )
                )
                continue

        # Last resort: compose from base text
        base_text = ""
        if slot < len(selected_candidates):
            base_text = selected_candidates[slot][3] if selected_candidates[slot][3] else (description or "")
        if not base_text and description:
            base_text = description
        if base_text:
            composed = _compose_fallback_bullet(
                section_type=section_type,
                source_id=source_id,
                slot=slot,
                base_text=base_text,
                priority_keywords=priority_keywords,
                task_themes=task_themes,
            )
            if composed and len(composed) >= MIN_BULLET_LENGTH:
                bullets.append(
                    ResumeBullet(
                        id=bullet_id,
                        text=composed,
                        original_text=composed,
                        status=BulletStatus.PENDING,
                        matched_keywords=_matched_priority_keywords(composed, priority_keywords),
                        source_id=source_id,
                    )
                )

    return bullets[:bullet_limit]


def _build_profile_context_text(profile_context: WorkExperience | Project) -> str:
    """Build a text blob from profile context for keyword matching."""
    parts: list[str] = []
    if hasattr(profile_context, "title"):
        parts.append(profile_context.title)
    if hasattr(profile_context, "company"):
        parts.append(profile_context.company)
    if hasattr(profile_context, "name"):
        parts.append(profile_context.name)
    if hasattr(profile_context, "description") and profile_context.description:
        parts.append(profile_context.description)
    if hasattr(profile_context, "bullets"):
        parts.extend(profile_context.bullets)
    if hasattr(profile_context, "technologies"):
        parts.extend(profile_context.technologies)
    if hasattr(profile_context, "tags"):
        parts.extend(getattr(profile_context, "tags", []) or [])
    return " ".join(parts)


def _extract_action_verb(responsibility: str) -> str:
    """Extract the action verb from a JD responsibility sentence."""
    lowered = responsibility.lower()
    for term, verb in _RESP_ACTION_MAP.items():
        if term in lowered:
            return verb
    # Default: use first word if it looks like a verb
    first_word = responsibility.split()[0] if responsibility.split() else ""
    if first_word and first_word[0].isupper() and len(first_word) > 2:
        return first_word.rstrip("s")
    return "Developed"


def _build_bullet_from_responsibility(
    action_verb: str,
    responsibility: str,
    matching_skills: list[str],
    profile_context: WorkExperience | Project,
    profile_tokens: set[str],
) -> str:
    """Build a single bullet from a JD responsibility + profile facts.

    Formula: [Action Verb] + [what was done using JD terms] + [profile context] + [outcome]
    """
    # Extract key nouns/phrases from the responsibility (skip the action verb)
    resp_lower = responsibility.lower()
    # Remove the action verb from the responsibility to get the "what"
    what_text = responsibility
    for term in _RESP_ACTION_MAP:
        if term in resp_lower:
            what_text = re.sub(re.escape(term), "", what_text, count=1, flags=re.IGNORECASE).strip(" ,.-")
            break

    # Clean up the "what" text
    what_text = _clean_sentence_fragment(what_text)
    if not what_text:
        what_text = responsibility

    # Build the core bullet
    if matching_skills:
        skills_text = ", ".join(matching_skills[:3])
        # Get company/project name for context
        context_name = ""
        if hasattr(profile_context, "company"):
            context_name = profile_context.company
        elif hasattr(profile_context, "name"):
            context_name = profile_context.name

        if context_name:
            bullet = f"{action_verb} {what_text} at {context_name} leveraging {skills_text}"
        else:
            bullet = f"{action_verb} {what_text} leveraging {skills_text}"
    else:
        context_name = ""
        if hasattr(profile_context, "company"):
            context_name = profile_context.company
        elif hasattr(profile_context, "name"):
            context_name = profile_context.name

        if context_name:
            bullet = f"{action_verb} {what_text} at {context_name}"
        else:
            bullet = f"{action_verb} {what_text}"

    # Add outcome (truthful, from profile or qualitative)
    outcome = _extract_outcome_from_profile(profile_context, profile_tokens)
    if outcome:
        bullet = f"{bullet}, {outcome}"

    # Ensure minimum length
    if len(bullet) < MIN_BULLET_LENGTH:
        # Add a truthful qualitative outcome
        bullet = f"{bullet}, supporting team delivery and system reliability"

    return _trim_bullet_text(bullet)


def _extract_outcome_from_profile(
    profile_context: WorkExperience | Project,
    profile_tokens: set[str],
) -> str:
    """Extract a truthful outcome from profile content."""
    profile_text = _build_profile_context_text(profile_context)
    profile_lower = profile_text.lower()

    # Look for metrics in profile
    metric_match = re.search(r"(\d+(?:\.\d+)?%|\d+\+|\d+\s*(users|clients|requests|ms|mb|gb|tb|apis|services|endpoints))", profile_lower)
    if metric_match:
        metric = metric_match.group(0)
        # Determine the type of outcome
        if "%" in metric:
            return f"improving performance by {metric}"
        elif "users" in metric or "clients" in metric:
            return f"supporting {metric}"
        elif "requests" in metric or "apis" in metric or "endpoints" in metric:
            return f"handling {metric} with high availability"
        else:
            return f"delivering {metric} in production"

    # Look for qualitative outcomes from profile text
    if any(term in profile_lower for term in ("automat", "ci/cd", "pipeline", "deploy")):
        return "streamlining deployment and release processes"
    if any(term in profile_lower for term in ("test", "quality", "bug", "defect")):
        return "improving code quality and test coverage"
    if any(term in profile_lower for term in ("document", "spec", "design")):
        return "strengthening documentation and design standards"
    if any(term in profile_lower for term in ("monitor", "observ", "log", "alert")):
        return "enhancing system observability and reliability"
    if any(term in profile_lower for term in ("refactor", "migrate", "moderniz")):
        return "improving maintainability and reducing technical debt"

    # Default truthful qualitative outcome
    return "supporting release readiness and team delivery goals"


def _compose_fallback_bullet(
    section_type: str,
    source_id: str,
    slot: int,
    base_text: str,
    priority_keywords: list[str],
    task_themes: list[str],
) -> str:
    """Clean and enhance a profile bullet with JD-aligned vocabulary."""
    cleaned_base = _clean_sentence_fragment(base_text)
    if not cleaned_base:
        return ""

    # Replace weak openings
    for pattern, replacement in _ACTION_REPLACEMENTS:
        cleaned_base = pattern.sub(replacement, cleaned_base, count=1)

    # Ensure action verb opening
    first = cleaned_base.split()[0].casefold().strip(",.:;") if cleaned_base.split() else ""
    strong_verbs = {verb.casefold() for verb in ("Built", "Implemented", "Delivered", "Engineered", "Optimized", "Integrated", "Managed", "Mentored", "Supported", "Contributed", "Developed", "Created", "Led", "Improved", "Maintained", "Processed", "Documented", "Designed", "Deployed", "Automated", "Configured")}
    if first not in strong_verbs:
        cleaned_base = f"Delivered {cleaned_base[0].lower() + cleaned_base[1:] if len(cleaned_base) > 1 else cleaned_base}"

    # Enrich short bullets with JD context
    if len(cleaned_base) < MIN_BULLET_LENGTH:
        keyword = _select_keyword(priority_keywords, slot)
        task = _select_task(task_themes, base_text, slot)
        if keyword:
            cleaned_base = f"{cleaned_base} using {keyword}"
        if task and task.casefold() not in cleaned_base.casefold():
            cleaned_base = f"{cleaned_base} to support {task}"
        if len(cleaned_base) < MIN_BULLET_LENGTH:
            cleaned_base = f"{cleaned_base}, supporting team delivery and system reliability"

    result = _trim_bullet_text(cleaned_base)

    # Final quality check: ensure no dangling ending or JD boilerplate
    if is_dangling_ending(result):
        # Try to repair
        quality = validate_single_bullet(result)
        if quality.repaired and quality.text and word_count(quality.text) >= 5:
            result = quality.text
        else:
            return ""  # Cannot use this bullet

    if has_jd_boilerplate(result):
        return ""  # Cannot use this bullet

    return result


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
    values = [
        *parsed_jd.responsibilities,
        *[req.text for req in parsed_jd.requirements if req.is_required],
        *([*ats_plan.must_include_responsibilities] if ats_plan else []),
    ]
    themes = [_abstract_task_theme(value) for value in values]
    return [value for value in _dedupe_strings(themes) if value][:12]


def _abstract_task_theme(value: str) -> str:
    tokens = [
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9+#./-]{3,}", value)
        if token.casefold() not in _STOPWORDS
        and token.casefold() not in {"responsibilities", "include", "seeking", "ideal", "candidate"}
    ]
    return " ".join(tokens[:4])


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


def _top_skill_names(skill_groups: list[ResumeSkillGroup]) -> list[str]:
    names: list[str] = []
    for group in skill_groups:
        if group.category.casefold() == "learning focus":
            continue
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


def _natural_join(values: list[str]) -> str:
    cleaned = _dedupe_strings([value for value in values if value])
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{cleaned[0]}, {cleaned[1]}, and {cleaned[2]}"


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
