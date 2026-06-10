"""
resume_quality_gate.py — ATS-first quality pass.

PHILOSOPHY (v2 — Always-Generate):
  * NEVER delete a bullet because it lacks source-connection evidence.
  * NEVER delete a bullet because the profile has no certifications.
  * Evidence checks are WARNINGS ONLY — they never kill content.
  * Only truly corrupted / duplicate / impossibly-fake text is fatal.
  * Skills are ALWAYS guaranteed: JD required terms inject when profile is thin.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from app.domain.rules import MIN_BULLET_LENGTH
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import BulletStatus, ResumeBullet, ResumeRecommendation, ResumeSkillGroup
from app.services.resume_strategy_service import build_resume_strategy, is_fresher_intern_strategy
from app.services.jd_sanitization_service import sanitize_parsed_jd
from app.services.locked_fields_service import LockedFields, guard_bullet_company_references
from app.services.resume_validation_gate import validate_resume_for_mode
from app.services.skill_taxonomy_service import (
    build_typed_skill_taxonomy,
    classify_skill,
    clean_keyword_terms,
    normalize_skill_value,
    typed_taxonomy_to_resume_groups,
)
from app.services.candidate_timeline_service import (
    allows_seniority_claims,
    assess_candidate_timeline,
    choose_honest_target_title,
)
from app.services.bullet_quality_service import (
    has_jd_boilerplate,
    is_dangling_ending,
    repair_incomplete_bullet,
    validate_single_bullet,
)

logger = logging.getLogger(__name__)


_FILLER_PATTERNS = [
    re.compile(r"\bATS-friendly delivery\b", re.IGNORECASE),
    re.compile(r"\bBuilt\s+OBDX\s+Developer\s+Installation\b", re.IGNORECASE),
]
_FOCUSED_ON_FILLER_RE = re.compile(r"^\s*focused\s+on\s*$", re.IGNORECASE)
_GENERIC_FILLER_PHRASES = [
    "improving reliability",
    "supporting production readiness",
    "streamlining delivery",
    "reducing manual effort",
    "strengthening troubleshooting",
    "enhancing application development",
    "ATS-friendly delivery",
]
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]{1,}", re.IGNORECASE)
_CORRUPTED_TEXT_RE = re.compile(r"(?:\\u00c3|\\u00c2|\\ufffd)")
_UNREADABLE_RE = re.compile(r"(?:[A-Z0-9/+#.-]{2,}\s*){10,}")
# Only literal impossible fabrications are fatal — nothing evidence-based.
_FATAL_FAKE_TERMS = ("fake employer", "invented employer", "impossible certification")


def apply_resume_quality_gate(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    target_pages: int = 1,
    locked: LockedFields | None = None,
) -> ResumeRecommendation:
    """Remove only fatal defects; weak source overlap is a warning-level signal."""
    parsed_jd = sanitize_parsed_jd(parsed_jd)
    rec = recommendation.model_copy(deep=True)
    strategy = build_resume_strategy(parsed_jd, profile)
    title_decision = choose_honest_target_title(parsed_jd, profile, rec.target_title)
    rec.target_title = title_decision.title
    rec.summary = _clean_summary(rec.summary, rec.target_title)
    timeline = assess_candidate_timeline(profile)
    if rec.summary and not allows_seniority_claims(timeline):
        rec.summary = _remove_unsupported_seniority_claims(rec.summary)
    rec.skills = build_skill_taxonomy(rec.skills, parsed_jd, profile, target_pages)

    seen_bullets: set[str] = set()
    repair_counts = {"experience": 0, "projects": 0}
    rec.experience = [
        entry for entry in rec.experience
        if _clean_entry_bullets(entry, parsed_jd, profile, seen_bullets, repair_counts, "experience", locked)
    ]
    rec.projects = [
        entry for entry in rec.projects
        if _clean_entry_bullets(entry, parsed_jd, profile, seen_bullets, repair_counts, "projects", locked)
    ]
    total_needs_repair = repair_counts["experience"] + repair_counts["projects"]
    if total_needs_repair:
        logger.info(
            "resume_quality_gate.needs_repair bullets=%s experience=%s projects=%s",
            total_needs_repair,
            repair_counts["experience"],
            repair_counts["projects"],
        )
    rec.education = [edu for edu in rec.education if edu.included and (edu.institution.strip() or edu.degree.strip())]
    rec.certifications = [cert for cert in rec.certifications if cert.included and cert.name.strip()]
    rec.achievements = [item for item in rec.achievements if item.included and item.title.strip()]
    rec.awards = [item for item in rec.awards if item.included and item.title.strip()]
    rec.custom_sections = [
        section.model_copy(update={"items": _dedupe(section.items)})
        for section in rec.custom_sections
        if section.included and section.title.strip() and _dedupe(section.items)
    ]

    warnings = [*rec.warnings, *title_decision.warnings]
    if is_fresher_intern_strategy(strategy):
        warnings.append("Fresher/intern strategy: preserved education, projects, achievements, and certifications.")
    rec.warnings = _dedupe(warnings)
    return validate_resume_for_mode(
        rec,
        parsed_jd=parsed_jd,
        profile=profile,
        mode="draft_mode",
        repair=True,
        locked=locked,
    ).recommendation


def build_skill_taxonomy(
    existing_groups: list[ResumeSkillGroup],
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    target_pages: int = 1,
) -> list[ResumeSkillGroup]:
    """
    Build the final skill taxonomy.

    Final resume skill groups are display output from the typed taxonomy. JD-only
    terms can become honest learning-focus items, but not arbitrary raw skill
    groups.
    """
    parsed_jd = sanitize_parsed_jd(parsed_jd)
    taxonomy = build_typed_skill_taxonomy(
        existing_groups=existing_groups,
        parsed_jd=parsed_jd,
        profile=profile,
        include_review_needed=False,
    )
    groups = typed_taxonomy_to_resume_groups(
        taxonomy,
        include_soft_skills=False,
        include_review_needed=False,
        target_pages=target_pages,
    )
    groups = _restore_required_profile_soft_skills(groups, parsed_jd, profile)

    # ALWAYS-POPULATE SAFETY NET: if taxonomy is still empty, inject everything.
    jd_priority = _build_jd_priority(parsed_jd)
    if not groups and jd_priority:
        logger.warning("Skill taxonomy produced 0 groups — injecting all JD priority terms as fallback.")
        all_clean = clean_keyword_terms(v for v in jd_priority if _is_allowed_jd_skill(v, parsed_jd.required_skills))
        if all_clean:
            fallback_taxonomy = build_typed_skill_taxonomy(
                existing_groups=[ResumeSkillGroup(category="Skills", skills=all_clean)],
                parsed_jd=parsed_jd,
                profile=profile,
                include_review_needed=False,
            )
            groups = typed_taxonomy_to_resume_groups(
                fallback_taxonomy,
                include_soft_skills=False,
                include_review_needed=False,
                target_pages=target_pages,
            )
            groups = _restore_required_profile_soft_skills(groups, parsed_jd, profile)

    return groups


def _restore_required_profile_soft_skills(
    groups: list[ResumeSkillGroup],
    parsed_jd: ParsedJD,
    profile: MasterProfile,
) -> list[ResumeSkillGroup]:
    profile_skill_keys = {
        _dedupe_key(skill.name)
        for skill in profile.skills
        if skill.name
    }
    existing_keys = {
        _dedupe_key(skill)
        for group in groups
        for skill in group.skills
    }
    restored: list[str] = []
    for raw in parsed_jd.required_skills:
        normalized = normalize_skill_value(raw)
        if not normalized:
            continue
        key = _dedupe_key(normalized)
        if key in existing_keys or key not in profile_skill_keys:
            continue
        if classify_skill(normalized) == "soft_skills" and _is_allowed_jd_skill(normalized, parsed_jd.required_skills):
            restored.append(normalized)
            existing_keys.add(key)
    if not restored:
        return groups
    return [*groups, ResumeSkillGroup(category="Soft Skills", skills=_dedupe(restored))]


def _clean_summary(summary: str | None, target_title: str) -> str | None:
    cleaned = _clean_text(summary)
    for pattern in _FILLER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"^\s*possessing\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*,\s*,+", ",", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned).strip(" .")
    if not cleaned:
        return target_title.strip() or None
    return cleaned[:1].upper() + cleaned[1:] + "."


def _remove_unsupported_seniority_claims(summary: str) -> str:
    cleaned = re.sub(r"\b(?:senior|lead|principal|staff)\b", "", summary, flags=re.IGNORECASE)
    cleaned = re.sub(r"\barchitected\b", "designed", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bmanaged\s+(?:cross-functional\s+)?teams?\b", "collaborated with teams", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bled\s+teams?\b", "collaborated with teams", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _clean_entry_bullets(
    entry,
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    seen_bullets: set[str],
    repair_counts: dict[str, int] | None = None,
    section_name: str = "entry",
    locked: LockedFields | None = None,
) -> bool:
    """
    Keep all bullets that pass ONLY structural/corruption checks.
    Source-connection and certification evidence are WARNINGS — never fatal.

    Also applies bullet quality validation: dangling endings, JD boilerplate,
    and missing action verbs are detected and repaired where possible.

    Examples:
    - "Responsible for database management" -> kept as NEEDS_REPAIR with a repair note.
    - "Built REST API using FastAPI" -> repaired with a conservative outcome suffix.
    - "Built REST API using FastAPI, handling 10k daily requests" -> kept.
    """
    valid: list[ResumeBullet] = []
    for bullet in entry.bullets:
        if bullet.status == BulletStatus.REJECTED:
            continue
        text = _clean_bullet_text(bullet.text)
        quality = validate_single_bullet(text)
        severity = _bullet_quality_severity(text, seen_bullets)

        if severity == "fatal" and not quality.has_banned_phrase and not quality.is_fixable:
            logger.debug("Dropped bullet (fatal): %s", text[:80])
            continue

        if any(issue.code == "jd_boilerplate" for issue in quality.issues):
            logger.debug("Warning: JD boilerplate detected but kept for ATS coverage: %s", text[:80])
            # We NO LONGER drop bullets for JD boilerplate, preserving them for ATS keywords
        if quality.repaired and quality.text:
            text = quality.text
        status = bullet.status
        repair_note = bullet.repair_note
        if quality.has_banned_phrase:
            logger.debug("Bullet has banned phrase — marking NEEDS_REPAIR: %s", text[:80])
            status = BulletStatus.NEEDS_REPAIR
            repair_note = "Contains banned phrase. Rewrite required."
            if repair_counts is not None:
                repair_counts[section_name] = repair_counts.get(section_name, 0) + 1
        elif not quality.has_outcome and quality.is_fixable:
            logger.debug("Bullet missing outcome — attempting repair: %s", text[:80])
            repaired_text = repair_incomplete_bullet(text)
            if repaired_text and repaired_text != text:
                text = repaired_text
                quality = validate_single_bullet(text)
        elif not quality.is_valid and quality.is_fixable:
            status = BulletStatus.NEEDS_REPAIR
            repair_note = f"STAR score: {quality.star_score}. Missing: {', '.join(quality.missing)}"
            if repair_counts is not None:
                repair_counts[section_name] = repair_counts.get(section_name, 0) + 1

        text = guard_bullet_company_references(text, locked)
        seen_bullets.add(_dedupe_key(text))
        valid.append(bullet.model_copy(update={
            "text": text,
            "original_text": bullet.original_text or text,
            "status": status,
            "repair_note": repair_note,
            "star_score": max(0.0, min(100.0, float(quality.star_score))),
        }))
    entry.bullets = valid
    return bool(valid)


def _bullet_quality_severity(text: str, seen_bullets: set[str]) -> str:
    """
    Only truly corrupted, duplicate, or literally impossible text is fatal.
    Evidence / source-connection checks are REMOVED — trust the AI composer.
    """
    if not _valid_bullet_text(text):
        return "fatal"
    if _dedupe_key(text) in seen_bullets:
        return "fatal"
    if _contains_literal_fake_terms(text):
        return "fatal"
    return "keep"


def _contains_literal_fake_terms(text: str) -> bool:
    """Only block bullets containing exact impossible-fabrication strings."""
    lowered = text.casefold()
    return any(term in lowered for term in _FATAL_FAKE_TERMS)


def _valid_bullet_text(text: str) -> bool:
    if len(text) < MIN_BULLET_LENGTH:
        return False
    if text.startswith("-") or text in {".", "â€¢"}:
        return False
    if _CORRUPTED_TEXT_RE.search(text):
        return False
    if _is_filler_text(text):
        return False
    if _looks_like_keyword_stuffing(text):
        return False
    if _UNREADABLE_RE.search(text):
        return False
    return bool(re.search(r"[A-Za-z0-9]", text))


def _clean_bullet_text(text: str | None) -> str:
    cleaned = _clean_text(text)
    cleaned = re.sub(r"^[\-*â€¢\s]+", "", cleaned)
    cleaned = _strip_generic_filler(cleaned)
    return cleaned.strip(" .;:-\t")


def _strip_generic_filler(text: str) -> str:
    """
    Strip generic AI filler endings only when they appear after a comma with no
    nearby metric. A phrase like "reducing manual effort by 60%" is preserved.
    """
    for phrase in _GENERIC_FILLER_PHRASES:
        pattern = re.compile(rf",\s*{re.escape(phrase)}\s*$", re.IGNORECASE)
        match = pattern.search(text)
        if not match:
            continue
        context_before = text[max(0, match.start() - 30):match.start()]
        if not re.search(r"\d+", context_before):
            text = pattern.sub("", text).strip()
    return text


def _is_filler_text(text: str) -> bool:
    if _FOCUSED_ON_FILLER_RE.fullmatch(text):
        return True
    return any(pattern.search(text) for pattern in _FILLER_PATTERNS)


def _looks_like_keyword_stuffing(text: str) -> bool:
    tokens = [token.casefold() for token in _TOKEN_RE.findall(text)]
    counts = Counter(tokens)
    if any(count > 2 and len(token) > 3 for token, count in counts.items()):
        return True
    return len(re.findall(r"\b[A-Z0-9/+#.-]{2,}\b", text)) >= 12


def _clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dedupe_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(str(value or ""))
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _build_jd_priority(parsed_jd: ParsedJD) -> list[str]:
    """
    Build a flat priority list of all JD skill/technology terms for the
    ALWAYS-POPULATE safety net in build_skill_taxonomy.

    Returns deduplicated terms ordered by: required skills first, then
    programming languages, frameworks, tools, databases, cloud tools,
    and domain terms — so the most important terms appear first.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(values: list[str]) -> None:
        for v in values:
            cleaned = v.strip()
            if cleaned and cleaned.casefold() not in seen:
                seen.add(cleaned.casefold())
                result.append(cleaned)

    _add(parsed_jd.required_skills)
    _add(parsed_jd.programming_languages)
    _add(parsed_jd.frameworks)
    _add(parsed_jd.tools_platforms)
    _add(parsed_jd.databases)
    _add(parsed_jd.cloud_devops_tools)
    _add(parsed_jd.preferred_skills)
    _add(parsed_jd.domain_platform_terms)
    _add(parsed_jd.deployment_environment_terms)
    _add(parsed_jd.mobile_platform_terms)

    # Add high-priority keywords
    for kw in parsed_jd.keywords:
        if kw.importance in {"critical", "high"}:
            _add([kw.keyword])

    # Add requirement texts that look like skills (short, technical)
    for req in parsed_jd.requirements:
        text = req.text.strip()
        if text and len(text.split()) <= 4 and text.casefold() not in seen:
            seen.add(text.casefold())
            result.append(text)

    return result


def _is_allowed_skill(value: str) -> bool:
    """Filter out non-skill terms from the ALWAYS-POPULATE safety net."""
    if not value or len(value) < 2:
        return False
    lowered = value.casefold()
    banned = {
        "we are seeking", "ideal candidate", "responsibilities include",
        "equal opportunity", "apply now", "job description", "about us",
        "ats keywords", "metadata", "job id", "fresh graduate",
    }
    if any(term in lowered for term in banned):
        return False
    if re.search(r"(?:\\u00c3|\\u00c2|\\ufffd)", value):
        return False
    return bool(re.search(r"[A-Za-z0-9]", value))


def _is_allowed_jd_skill(value: str, required_skills: list[str] | set[str] | tuple[str, ...]) -> bool:
    required = {str(skill or "").casefold().strip() for skill in required_skills}
    if str(value or "").casefold().strip() in required:
        return True
    return _is_allowed_skill(value)
