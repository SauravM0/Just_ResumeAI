"""
Deterministic one-page resume compression.

Design intent: generate at ideal depth first, compress only if page overflow is
detected or a one-page target is explicitly requested. The constants stay roomy
because ATS-ready resumes need keyword density, section depth, and quantified
bullets before any final fit pass trims lower-priority content.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.resume import (
    BulletStatus,
    ResumeBullet,
    ResumeCertEntry,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeProjectEntry,
    ResumeRecommendation,
    ResumeSkillGroup,
)
from app.services.resume_strategy_service import build_resume_strategy, is_fresher_intern_strategy

_ONE_PAGE_SUMMARY_WORDS = 90  # Raised from 42: preserves keyword-rich summaries before fit trimming.
_ONE_PAGE_MAX_SKILL_GROUPS = 5
_ONE_PAGE_MAX_SKILLS_PER_GROUP = 12  # Raised from 10: keeps more JD-required hard skills visible.
_ONE_PAGE_MAX_EXPERIENCE = 3
_ONE_PAGE_MAX_EXPERIENCE_BULLETS = 5  # Raised from 3: stops post-AI trimming from thinning primary roles.
_ONE_PAGE_MAX_SECONDARY_EXPERIENCE_BULLETS = 4  # Raised from 2: keeps supporting roles recruiter-readable.
_ONE_PAGE_MAX_PROJECTS = 3  # Raised from 2: preserves enough project evidence for fresher/early-career profiles.
_ONE_PAGE_MAX_PROJECT_BULLETS = 3  # Raised from 2: projects need depth for ATS skill matching.
_ONE_PAGE_MAX_CERTIFICATIONS = 3
_ONE_PAGE_MAX_BULLET_CHARS = 210  # Raised from 180: avoids cutting quantified Achievement Formula bullets.

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]{1,}", re.IGNORECASE)
_SENTENCE_END_RE = re.compile(r"[.!?]\s+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
    "is", "it", "of", "on", "or", "the", "to", "with", "using", "use",
}
_ALLOWED_BULLET_STATUSES = {
    BulletStatus.ACCEPTED,
    BulletStatus.EDITED,
    BulletStatus.LOCKED,
    BulletStatus.PENDING,
}


def fit_resume_to_page_budget(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
    target_pages: int = 1,
) -> ResumeRecommendation:
    """
    Compress a resume recommendation for a target page budget.

    The function is intentionally conservative and idempotent: it removes empty
    or low-priority content, caps section sizes, and keeps required JD terms
    near the front of skills and bullets.
    """
    rec = recommendation.model_copy(deep=True)
    strategy = build_resume_strategy(parsed_jd)
    is_fresher = is_fresher_intern_strategy(strategy)
    priority_terms = _priority_terms(parsed_jd, ats_plan)

    _remove_empty_sections(rec)

    if target_pages != 1:
        return rec

    rec.summary = _compact_summary(rec.summary, priority_terms)
    rec.skills = _compact_skills(rec.skills, priority_terms)
    rec.experience = _compact_experience(rec.experience, priority_terms)
    rec.projects = _compact_projects(rec.projects, priority_terms, project_limit=3 if is_fresher else _ONE_PAGE_MAX_PROJECTS)
    rec.certifications = _compact_certifications(rec.certifications, priority_terms, preserve_all=is_fresher)
    rec.education = _compact_education(rec.education, priority_terms)
    if not is_fresher and target_pages == 1:
        rec.achievements = rec.achievements[:3]
        rec.awards = rec.awards[:3]

    _remove_empty_sections(rec)
    return rec


def _remove_empty_sections(rec: ResumeRecommendation) -> None:
    rec.skills = [
        group.model_copy(update={"skills": _dedupe_clean(group.skills)})
        for group in rec.skills
    ]
    rec.skills = [group for group in rec.skills if group.skills]

    rec.experience = [
        entry.model_copy(update={"bullets": _valid_bullets(entry.bullets)})
        for entry in rec.experience
        if entry.included
    ]
    rec.experience = [entry for entry in rec.experience if entry.bullets]

    rec.projects = [
        entry.model_copy(
            update={
                "technologies": _dedupe_clean(entry.technologies),
                "bullets": _valid_bullets(entry.bullets),
            }
        )
        for entry in rec.projects
        if entry.included
    ]
    rec.projects = [entry for entry in rec.projects if entry.bullets]

    rec.certifications = [
        cert for cert in rec.certifications
        if cert.included and _clean_text(cert.name)
    ]

    rec.achievements = [
        item for item in rec.achievements
        if item.included and _clean_text(item.title)
    ]

    rec.awards = [
        item for item in rec.awards
        if item.included and _clean_text(item.title)
    ]

    rec.custom_sections = [
        section.model_copy(update={"items": _dedupe_clean(section.items)})
        for section in rec.custom_sections
        if section.included and _clean_text(section.title) and _dedupe_clean(section.items)
    ]

    rec.education = [
        edu for edu in rec.education
        if edu.included and (_clean_text(edu.degree) or _clean_text(edu.institution))
    ]


def _compact_summary(summary: str | None, priority_terms: set[str]) -> str | None:
    text = _clean_text(summary)
    if not text:
        return None

    sentences = [part.strip() for part in _SENTENCE_END_RE.split(text) if part.strip()]
    if sentences:
        ordered = sorted(
            enumerate(sentences),
            key=lambda item: (-_priority_score(item[1], priority_terms), item[0]),
        )
        kept: list[str] = []
        word_count = 0
        for _, sentence in ordered:
            words = sentence.split()
            if kept and word_count + len(words) > _ONE_PAGE_SUMMARY_WORDS:
                continue
            kept.append(sentence.rstrip(".!?"))
            word_count += len(words)
            # Raised from 28 because ATS summaries need enough natural language
            # surface area for target title, priority skills, and one metric.
            if word_count >= 70:
                break
        if kept:
            text = ". ".join(kept) + "."

    return _trim_words(text, _ONE_PAGE_SUMMARY_WORDS)


def _compact_skills(groups: list[ResumeSkillGroup], priority_terms: set[str]) -> list[ResumeSkillGroup]:
    compacted: list[ResumeSkillGroup] = []
    overflow: list[str] = []

    cleaned_groups = [
        group.model_copy(update={"skills": _order_priority_values(group.skills, priority_terms)})
        for group in groups
        if _clean_text(group.category) and group.skills
    ]
    cleaned_groups = [group for group in cleaned_groups if group.skills]
    cleaned_groups.sort(
        key=lambda group: (-_priority_score(" ".join(group.skills), priority_terms), group.category.casefold())
    )

    for index, group in enumerate(cleaned_groups):
        if index < _ONE_PAGE_MAX_SKILL_GROUPS:
            kept = group.skills[:_ONE_PAGE_MAX_SKILLS_PER_GROUP]
            overflow.extend(group.skills[_ONE_PAGE_MAX_SKILLS_PER_GROUP:])
            compacted.append(group.model_copy(update={"skills": kept}))
        else:
            overflow.extend(group.skills)

    if overflow:
        additional = _order_priority_values(overflow, priority_terms)[:_ONE_PAGE_MAX_SKILLS_PER_GROUP]
        if additional:
            if len(compacted) < _ONE_PAGE_MAX_SKILL_GROUPS:
                compacted.append(ResumeSkillGroup(category="Additional Skills", skills=additional))
            else:
                last = compacted[-1]
                merged = _order_priority_values([*last.skills, *additional], priority_terms)
                compacted[-1] = last.model_copy(update={"skills": merged[:_ONE_PAGE_MAX_SKILLS_PER_GROUP]})

    return compacted[:_ONE_PAGE_MAX_SKILL_GROUPS]


def _compact_experience(
    entries: list[ResumeExperienceEntry],
    priority_terms: set[str],
) -> list[ResumeExperienceEntry]:
    if not entries:
        return []

    chosen_indexes = _choose_relevant_indexes(entries, _ONE_PAGE_MAX_EXPERIENCE, force_first=True)
    compacted: list[ResumeExperienceEntry] = []

    for output_index, entry_index in enumerate(chosen_indexes):
        entry = entries[entry_index]
        bullet_limit = (
            _ONE_PAGE_MAX_EXPERIENCE_BULLETS
            if output_index == 0
            else _ONE_PAGE_MAX_SECONDARY_EXPERIENCE_BULLETS
        )
        bullets = _compact_bullets(entry.bullets, priority_terms, bullet_limit)
        if bullets:
            compacted.append(entry.model_copy(update={"bullets": bullets}))

    if not compacted:
        fallback = _first_entry_with_bullets(entries)
        if fallback:
            # Keep the fallback per-entry cap aligned with the normal primary cap so a
            # temporary scoring miss does not collapse the entire experience section.
            compacted.append(fallback.model_copy(update={
                "bullets": _compact_bullets(fallback.bullets, priority_terms, _ONE_PAGE_MAX_EXPERIENCE_BULLETS)
            }))

    return [entry for entry in compacted if entry.bullets]


def _compact_projects(
    entries: list[ResumeProjectEntry],
    priority_terms: set[str],
    project_limit: int = _ONE_PAGE_MAX_PROJECTS,
) -> list[ResumeProjectEntry]:
    chosen_indexes = _choose_relevant_indexes(entries, project_limit, force_first=False)
    compacted: list[ResumeProjectEntry] = []

    for entry_index in chosen_indexes:
        entry = entries[entry_index]
        bullets = _compact_bullets(entry.bullets, priority_terms, _ONE_PAGE_MAX_PROJECT_BULLETS)
        technologies = _order_priority_values(entry.technologies, priority_terms)[:6]
        if bullets:
            compacted.append(entry.model_copy(update={"bullets": bullets, "technologies": technologies}))

    return compacted


def _compact_certifications(
    certifications: list[ResumeCertEntry],
    priority_terms: set[str],
    preserve_all: bool = False,
) -> list[ResumeCertEntry]:
    if preserve_all:
        return certifications[:_ONE_PAGE_MAX_CERTIFICATIONS + 2]
    if not priority_terms:
        return []

    relevant = [
        cert
        for cert in certifications
        if _priority_score(f"{cert.name} {cert.issuing_org or ''}", priority_terms) > 0
    ]
    relevant.sort(
        key=lambda cert: -_priority_score(f"{cert.name} {cert.issuing_org or ''}", priority_terms)
    )
    return relevant[:_ONE_PAGE_MAX_CERTIFICATIONS]


def _compact_education(
    education: list[ResumeEducationEntry],
    priority_terms: set[str],
) -> list[ResumeEducationEntry]:
    compacted: list[ResumeEducationEntry] = []
    for edu in education:
        coursework = [
            course for course in _dedupe_clean(edu.relevant_coursework)
            if _priority_score(course, priority_terms) > 0
        ]
        compacted.append(edu.model_copy(update={"relevant_coursework": coursework[:4]}))
    return compacted


def _compact_bullets(
    bullets: list[ResumeBullet],
    priority_terms: set[str],
    limit: int,
) -> list[ResumeBullet]:
    valid = _valid_bullets(bullets)
    ordered = sorted(
        enumerate(valid),
        key=lambda item: (
            item[0] != 0,
            -max(item[1].relevance_score, _priority_score(item[1].text, priority_terms)),
            item[0],
        ),
    )
    selected = sorted(ordered[:limit], key=lambda item: item[0])
    compacted: list[ResumeBullet] = []
    for _, bullet in selected:
        compacted.append(bullet.model_copy(update={"text": _trim_bullet_text(bullet.text)}))
    return compacted


def _choose_relevant_indexes(entries: list, limit: int, force_first: bool) -> list[int]:
    if not entries:
        return []

    chosen: set[int] = {0} if force_first else set()
    ranked = sorted(
        enumerate(entries),
        key=lambda item: (-getattr(item[1], "relevance_score", 0.0), item[0]),
    )
    for index, _ in ranked:
        if len(chosen) >= limit:
            break
        chosen.add(index)
    return sorted(chosen)


def _first_entry_with_bullets(entries: Iterable) -> object | None:
    for entry in entries:
        if _valid_bullets(entry.bullets):
            return entry
    return None


def _valid_bullets(bullets: list[ResumeBullet]) -> list[ResumeBullet]:
    valid: list[ResumeBullet] = []
    for bullet in bullets:
        if bullet.status not in _ALLOWED_BULLET_STATUSES:
            continue
        text = _clean_text(bullet.text)
        if not text:
            continue
        valid.append(bullet.model_copy(update={"text": text}))
    return valid


def _priority_terms(parsed_jd: ParsedJD, ats_plan: ATSKeywordPlannerOutput | None) -> set[str]:
    values: list[str] = [
        parsed_jd.job_title,
        *parsed_jd.required_skills,
        *parsed_jd.preferred_skills,
        *parsed_jd.tools_platforms,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.domain_platform_terms,
        *parsed_jd.deployment_environment_terms,
        *parsed_jd.mobile_platform_terms,
        *parsed_jd.important_exact_phrases,
        *(keyword.keyword for keyword in parsed_jd.keywords),
    ]
    if ats_plan:
        values.extend(
            [
                ats_plan.target_resume_title,
                *ats_plan.priority_keywords,
                *ats_plan.must_include_skills,
                *ats_plan.must_include_tools_platforms,
                *ats_plan.must_include_responsibilities,
                *ats_plan.suggested_project_emphasis,
            ]
        )

    terms: set[str] = set()
    for value in values:
        text = _clean_text(value).casefold()
        if text:
            terms.add(text)
        for token in _TOKEN_RE.findall(text):
            if token not in _STOPWORDS:
                terms.add(token)
    return terms


def _priority_score(text: str | None, priority_terms: set[str]) -> float:
    if not text or not priority_terms:
        return 0.0
    normalized = _clean_text(text).casefold()
    tokens = set(_TOKEN_RE.findall(normalized))
    score = 0.0
    for term in priority_terms:
        if not term:
            continue
        if " " in term and term in normalized:
            score += 2.0
        elif term in tokens:
            score += 1.0
    return score


def _order_priority_values(values: list[str], priority_terms: set[str]) -> list[str]:
    cleaned = _dedupe_clean(values)
    cleaned.sort(key=lambda value: (-_priority_score(value, priority_terms), value.casefold()))
    return cleaned


def _dedupe_clean(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _trim_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(".,;:") + "."


def _trim_bullet_text(text: str) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= _ONE_PAGE_MAX_BULLET_CHARS:
        return cleaned
    truncated = cleaned[: _ONE_PAGE_MAX_BULLET_CHARS + 1]
    truncated = truncated.rsplit(" ", 1)[0]
    return truncated.rstrip(".,;:") + "."
