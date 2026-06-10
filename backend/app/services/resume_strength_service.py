"""
Deterministic resume strengthening pass.

This is a finalizer for AI and fallback recommendations: it cleans noisy output,
improves weak bullet openings, and keeps content ATS-readable without inventing
employers, dates, degrees, or certifications.
"""

from __future__ import annotations

import re

from app.domain.rules import ACTION_VERBS, MAX_BULLET_LENGTH, MIN_BULLET_LENGTH
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.resume import BulletStatus, ResumeBullet, ResumeRecommendation, ResumeSkillGroup
from app.services.jd_sanitization_service import sanitize_parsed_jd
from app.services.skill_taxonomy_service import merge_typed_skill_groups


_ACTION_VERBS = {verb.casefold() for verb in ACTION_VERBS}
_CORRUPTED_MARKERS_RE = re.compile(
    r"^(?:[\s\-–—•◦▪●·*]+|(?:â€¢|â—¦|â–ª|Ã‚Â[\w¤®©£¥§¶°±²³µ¹º»¼½¾¿]?|ï¸|âœ…|âš )+)+"
)
_WEIRD_SYMBOLS_RE = re.compile(
    r"(?:â€¢|â—¦|â–ª|Ã‚Â[\w¤®©£¥§¶°±²³µ¹º»¼½¾¿]?|ï¸|âœ…|âš |[•◦▪●·])"
)
_SPACE_RE = re.compile(r"\s+")

_WEAK_OPENING_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^responsible\s+for\s+", re.IGNORECASE), "Managed "),
    (re.compile(r"^worked\s+on\s+", re.IGNORECASE), "Built "),
    (re.compile(r"^helped\s+with\s+", re.IGNORECASE), "Supported "),
    (re.compile(r"^good\s+knowledge\s+of\s+", re.IGNORECASE), "Applied "),
    (re.compile(r"^involved\s+in\s+", re.IGNORECASE), "Contributed to "),
]

_IMPACT_PHRASES = (
    "improving reliability",
    "streamlining deployment",
    "supporting production readiness",
    "reducing manual effort",
    "strengthening troubleshooting",
)


def strengthen_resume_recommendation(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
    target_pages: int = 1,
) -> ResumeRecommendation:
    """Return a cleaned and strengthened copy of a resume recommendation."""
    parsed_jd = sanitize_parsed_jd(parsed_jd)
    strengthened = recommendation.model_copy(deep=True)
    strengthened.target_title = _clean_target_title(
        (ats_plan.target_resume_title if ats_plan and ats_plan.target_resume_title else None)
        or strengthened.target_title
        or parsed_jd.job_title
        or ""
    )
    # External ATS tools weight exact title/company/domain terms heavily, so this
    # pass ensures they appear in the highest-signal text without inventing work.
    strengthened.summary = _strengthen_summary(strengthened.summary, strengthened.target_title, parsed_jd, ats_plan)
    strengthened.skills = _strengthen_skill_groups(strengthened.skills, parsed_jd, ats_plan)
    strengthened.warnings = _dedupe([
        *strengthened.warnings,
        *([] if not ats_plan else ats_plan.seniority_warnings),
        *_unsupported_certification_warnings(parsed_jd, strengthened),
    ])

    strengthened.experience = [
        entry
        for entry in strengthened.experience
        if _strengthen_entry_bullets(entry)
    ]

    strengthened.projects = [
        entry
        for entry in strengthened.projects
        if _strengthen_entry_bullets(entry)
    ]

    return strengthened


def _strengthen_summary(
    summary: str | None,
    target_title: str,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
) -> str:
    existing = _SPACE_RE.sub(" ", summary or "").strip()
    phrases = _summary_phrases(parsed_jd, ats_plan)
    missing = [phrase for phrase in phrases if not _contains_phrase(existing, phrase)]
    if not existing:
        existing = f"{target_title or parsed_jd.job_title} candidate aligned with {', '.join(phrases[:8])}."
    if missing:
        # Use an honest targeting sentence: it adds exact ATS terms while avoiding
        # a false claim that unsupported platform tools were used professionally.
        target_context = _natural_join(missing[:3])
        existing = f"{existing.rstrip('.')}. Targeting {parsed_jd.company or 'the organization'} {parsed_jd.job_title} work involving {target_context}."
    return _trim_words(existing, 120)


def _strengthen_skill_groups(
    groups: list[ResumeSkillGroup],
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
) -> list[ResumeSkillGroup]:
    """
    Inject ALL missing JD-required skills/tools into the skill groups.

    CHANGED: Removed _looks_like_certification() gate — certification terms
    from the JD (e.g., "AWS Certified", "RHCSA") are valid skills and should
    appear in the skills section. Trusting the AI and the JD as source of truth.
    """
    result = [group.model_copy(deep=True) for group in groups]
    existing = {_skill_key(skill) for group in result for skill in group.skills}

    required_terms = _skill_terms_for_ats(parsed_jd, ats_plan)
    learning_terms: list[str] = []
    for term in required_terms:
        key = _skill_key(term)
        if key in existing or not _skill_like(term):
            continue
        # Domain/company-specific tools go into Learning Focus — all others direct.
        learning_terms.append(term)
        existing.add(key)

    return merge_typed_skill_groups(result, [], learning_focus_values=learning_terms)


def _clean_target_title(title: str) -> str:
    cleaned = _SPACE_RE.sub(" ", str(title or "")).strip()
    cleaned = re.sub(r"^\s*(designation|job\s*title|title|role)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*:+\s*$", "", cleaned)
    return cleaned.strip(" :-\t")


def _natural_join(values: list[str]) -> str:
    cleaned = [value for value in values if value]
    if not cleaned:
        return "role-relevant delivery"
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{cleaned[0]}, {cleaned[1]}, and {cleaned[2]}"


def _strengthen_entry_bullets(entry) -> bool:
    valid_bullets: list[ResumeBullet] = []
    original_bullets = list(entry.bullets)

    for index, bullet in enumerate(original_bullets):
        if bullet.status == BulletStatus.LOCKED:
            if _clean_bullet_text(bullet.text):
                valid_bullets.append(bullet)
            continue

        text = _strengthen_bullet_text(
            bullet.text,
        )
        if not text:
            continue
        updated = bullet.model_copy(update={"text": text, "original_text": bullet.original_text or text})
        valid_bullets.append(updated)

    entry.bullets = valid_bullets
    return bool(valid_bullets)


def _strengthen_bullet_text(text: str | None) -> str:
    cleaned = _clean_bullet_text(text)
    if not cleaned:
        return ""

    cleaned = _replace_weak_opening(cleaned)
    cleaned = _ensure_action_opening(cleaned)
    cleaned = _trim_bullet(cleaned)

    return cleaned if len(cleaned) >= MIN_BULLET_LENGTH else ""


def _clean_bullet_text(text: str | None) -> str:
    cleaned = str(text or "")
    cleaned = _WEIRD_SYMBOLS_RE.sub(" ", cleaned)
    cleaned = _CORRUPTED_MARKERS_RE.sub("", cleaned)
    cleaned = re.sub(r"^(?:[-–—*]\s*)+", "", cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip(" .;:-\t")
    return cleaned


def _replace_weak_opening(text: str) -> str:
    for pattern, replacement in _WEAK_OPENING_REPLACEMENTS:
        if pattern.search(text):
            return pattern.sub(replacement, text, count=1).strip()
    return text


def _ensure_action_opening(text: str) -> str:
    first_word = text.split()[0].lower().rstrip(",.:;") if text.split() else ""
    if first_word in _ACTION_VERBS:
        return _capitalize_first(text)
    if re.match(r"^(built|developed|implemented|managed|supported|contributed|delivered)\b", text, re.IGNORECASE):
        return _capitalize_first(text)
    return f"Delivered {text[0].lower() + text[1:] if len(text) > 1 else text}"


def _trim_bullet(text: str) -> str:
    cleaned = _SPACE_RE.sub(" ", text).strip(" .;:-\t")
    if len(cleaned) <= MAX_BULLET_LENGTH:
        return cleaned
    clipped = cleaned[: MAX_BULLET_LENGTH - 3].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return f"{clipped}..."


def _summary_phrases(parsed_jd: ParsedJD, ats_plan: ATSKeywordPlannerOutput | None) -> list[str]:
    values = [
        parsed_jd.job_title,
        parsed_jd.company or "",
        *parsed_jd.domain_platform_terms,
        *parsed_jd.deployment_environment_terms,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.tools_platforms,
        *parsed_jd.important_exact_phrases,
        *([*ats_plan.priority_keywords[:12]] if ats_plan else []),
    ]
    return [value for value in _dedupe(values) if value and len(value) <= 80][:14]


def _skill_terms_for_ats(parsed_jd: ParsedJD, ats_plan: ATSKeywordPlannerOutput | None) -> list[str]:
    values = [
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.tools_platforms,
        *parsed_jd.domain_platform_terms,
        *parsed_jd.deployment_environment_terms,
        *parsed_jd.mobile_platform_terms,
        *parsed_jd.preferred_skills,
    ]
    if ats_plan:
        values.extend(ats_plan.must_include_skills)
        values.extend(ats_plan.must_include_tools_platforms)
    return _dedupe(values)[:50]


def _unsupported_certification_warnings(parsed_jd: ParsedJD, recommendation: ResumeRecommendation) -> list[str]:
    cert_text = " ".join(f"{cert.name} {cert.issuing_org or ''}" for cert in recommendation.certifications).casefold()
    warnings: list[str] = []
    for term in _dedupe([*parsed_jd.required_skills, *parsed_jd.keywords]):
        keyword = getattr(term, "keyword", term)
        if _looks_like_certification(str(keyword)) and str(keyword).casefold() not in cert_text:
            warnings.append(f"JD asks for certification '{keyword}', but it is not in the master profile.")
    return warnings[:5]


def _contains_phrase(text: str, phrase: str) -> bool:
    return _normalize_text(phrase) in _normalize_text(text)


def _normalize_text(value: str | None) -> str:
    lowered = (value or "").casefold()
    lowered = re.sub(r"[^a-z0-9+#/.\- ]+", " ", lowered)
    return _SPACE_RE.sub(" ", lowered).strip()


def _skill_key(value: str) -> str:
    return _normalize_text(value).replace("golang", "go")


def _skill_like(value: str) -> bool:
    text = _SPACE_RE.sub(" ", str(value or "")).strip()
    if not text or len(text.split()) > 4:
        return False
    lowered = text.casefold()
    if any(phrase in lowered for phrase in ("recent graduation", "apprenticeship program", "customer experience", "cross-functional", "teams")):
        return False
    return True


def _looks_like_certification(value: str) -> bool:
    lowered = str(value or "").casefold()
    return bool(re.search(r"\b(certification|certified|certificate|rhcsa|rhce)\b", lowered))


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = getattr(value, "keyword", value)
        cleaned = _SPACE_RE.sub(" ", str(text or "")).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _trim_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(".,;:") + "."


def _priority_keywords(parsed_jd: ParsedJD, ats_plan: ATSKeywordPlannerOutput | None) -> list[str]:
    candidates: list[str] = []
    if ats_plan:
        candidates.extend(ats_plan.priority_keywords)
        candidates.extend(ats_plan.must_include_skills)
        candidates.extend(ats_plan.must_include_tools_platforms)
        candidates.extend(ats_plan.must_include_responsibilities)

    deduped: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        cleaned = _SPACE_RE.sub(" ", str(value or "")).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen or len(cleaned) > 48:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped[:12]


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text
