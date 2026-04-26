"""
Scoring service — deterministic ATS score computation.

This runs AFTER human review to give the user quality feedback.
No AI involved — pure rule-based scoring.
"""

from __future__ import annotations

import logging
import re

from app.domain.rules import (
    ACTION_VERBS,
    MAX_BULLET_LENGTH,
    MIN_BULLET_LENGTH,
    MIN_KEYWORD_COVERAGE_PERCENT,
    SCORE_WEIGHT_FORMAT,
    SCORE_WEIGHT_KEYWORD,
    SCORE_WEIGHT_READABILITY,
)
from app.schemas.jd import ParsedJD
from app.schemas.resume import ResumeRecommendation, BulletStatus
from app.schemas.scoring import ATSScore, KeywordMatch, KeywordScore, ReadabilityScore

logger = logging.getLogger(__name__)

_TRIVIAL_KEYWORDS = {
    "and", "the", "for", "with", "our", "your", "you", "will", "role", "team", "job",
    "work", "using", "experience", "skills", "skill", "required", "preferred",
}


def compute_ats_score(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
) -> ATSScore:
    """
    Compute the composite ATS score for a resume recommendation.
    Called after the user finishes reviewing.
    """
    keyword_score = _compute_keyword_score(recommendation, parsed_jd)
    readability = _compute_readability_score(recommendation)
    format_score, format_issues = _compute_format_score(recommendation)

    overall = (
        keyword_score.coverage_percent * SCORE_WEIGHT_KEYWORD
        + readability.score * SCORE_WEIGHT_READABILITY
        + format_score * SCORE_WEIGHT_FORMAT
    )

    warnings: list[str] = []
    recommendations_list: list[str] = []

    if keyword_score.coverage_percent < MIN_KEYWORD_COVERAGE_PERCENT:
        warnings.append(
            f"Keyword coverage is {keyword_score.coverage_percent:.0f}% — "
            f"below the {MIN_KEYWORD_COVERAGE_PERCENT}% threshold."
        )
    if keyword_score.critical_missing:
        warnings.append(
            f"Missing critical keywords: {', '.join(keyword_score.critical_missing[:5])}"
        )
        recommendations_list.append(
            "Add the missing critical keywords to your experience bullets or skills section."
        )
    if readability.score < 70:
        recommendations_list.append(
            "Improve bullet readability: start with action verbs and keep bullets concise."
        )
    if format_score < 100:
        warnings.extend(format_issues[:3])
        recommendations_list.append(
            "Tighten formatting quality by filling key sections, trimming long summaries, and fixing sparse or inconsistent entries."
        )

    return ATSScore(
        overall_score=round(overall, 1),
        keyword_score=keyword_score,
        readability_score=readability,
        format_score=round(format_score, 1),
        warnings=warnings,
        recommendations=recommendations_list,
    )


def _compute_keyword_score(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
) -> KeywordScore:
    """Check how many distinct JD keywords appear in the resume content."""
    corpus = _build_resume_corpus(recommendation)
    normalized_keywords = _dedupe_jd_keywords(parsed_jd)
    critical_candidates = _critical_keywords(parsed_jd)

    details: list[KeywordMatch] = []
    matched = 0
    missing_keyword_keys: set[str] = set()

    for keyword in normalized_keywords:
        found, location = _match_keyword(keyword, corpus)
        if found:
            matched += 1
        else:
            missing_keyword_keys.add(_normalize_keyword(keyword))

        details.append(KeywordMatch(keyword=keyword, found=found, location=location))

    critical_missing = [
        keyword for keyword in critical_candidates
        if _normalize_keyword(keyword) in missing_keyword_keys
    ]

    total = len(normalized_keywords) or 1
    coverage = (matched / total) * 100

    return KeywordScore(
        total_keywords=total,
        matched_keywords=matched,
        coverage_percent=round(coverage, 1),
        critical_missing=critical_missing[:10],
        details=details,
    )


def _compute_readability_score(recommendation: ResumeRecommendation) -> ReadabilityScore:
    """Score bullet quality: action verbs, length, passive voice."""
    all_bullets: list[str] = []
    for exp in recommendation.experience:
        for b in exp.bullets:
            if b.status != BulletStatus.REJECTED:
                all_bullets.append(b.text)
    for proj in recommendation.projects:
        for b in proj.bullets:
            if b.status != BulletStatus.REJECTED:
                all_bullets.append(b.text)

    if not all_bullets:
        return ReadabilityScore(score=0.0, avg_bullet_length=0.0, issues=["No bullets found"])

    issues: list[str] = []
    total_len = 0
    good_bullets = 0

    for text in all_bullets:
        total_len += len(text)

        first_word = text.split()[0].lower().rstrip(",.:;") if text.split() else ""
        starts_with_action = first_word in ACTION_VERBS
        good_length = MIN_BULLET_LENGTH <= len(text) <= MAX_BULLET_LENGTH
        passive = bool(re.search(r"\b(was|were|been|being|is|are)\s+\w+ed\b", text, re.IGNORECASE))

        if starts_with_action and good_length and not passive:
            good_bullets += 1
        else:
            if not starts_with_action:
                issues.append(f"Bullet doesn't start with action verb: '{text[:50]}...'")
            if not good_length:
                issues.append(f"Bullet length ({len(text)} chars) outside range: '{text[:40]}...'")
            if passive:
                issues.append(f"Passive voice detected: '{text[:50]}...'")

    avg_len = total_len / len(all_bullets)
    score = (good_bullets / len(all_bullets)) * 100

    return ReadabilityScore(
        score=round(score, 1),
        avg_bullet_length=round(avg_len, 1),
        issues=issues[:15],
    )


def _compute_format_score(recommendation: ResumeRecommendation) -> tuple[float, list[str]]:
    """Compute a conservative format score from visible resume quality signals."""
    penalties = 0.0
    issues: list[str] = []

    if not recommendation.contact.full_name.strip():
        penalties += 15
        issues.append("Contact name is missing.")
    if not recommendation.contact.email.strip():
        penalties += 15
        issues.append("Contact email is missing.")
    if not any(
        [
            recommendation.contact.phone,
            recommendation.contact.linkedin_url,
            recommendation.contact.github_url,
            recommendation.contact.portfolio_url,
        ]
    ):
        penalties += 5
        issues.append("Contact details are sparse beyond the email address.")

    if not recommendation.summary:
        penalties += 10
        issues.append("Professional summary is missing.")
    elif len(recommendation.summary.split()) > 70:
        penalties += 8
        issues.append("Professional summary is too long for a one-page ATS resume.")

    included_experience = [exp for exp in recommendation.experience if exp.included]
    included_projects = [proj for proj in recommendation.projects if proj.included]
    included_skills = [group for group in recommendation.skills if group.skills]

    if not included_experience:
        penalties += 20
        issues.append("No included work experience entries were found.")
    if not included_skills:
        penalties += 15
        issues.append("Skills section is empty.")

    for exp in included_experience:
        if not exp.start_date:
            penalties += 4
            issues.append(f"Experience entry '{exp.title}' is missing a start date.")
        if not exp.is_current and not exp.end_date:
            penalties += 4
            issues.append(f"Experience entry '{exp.title}' is missing an end date.")
        if len(exp.bullets) > 5:
            penalties += 5
            issues.append(f"Experience entry '{exp.title}' has too many bullets.")
        if not exp.bullets:
            penalties += 6
            issues.append(f"Experience entry '{exp.title}' has no bullets.")

    for proj in included_projects:
        if len(proj.bullets) > 5:
            penalties += 4
            issues.append(f"Project '{proj.name}' has too many bullets.")
        if not proj.bullets:
            penalties += 4
            issues.append(f"Project '{proj.name}' has no bullets.")

    for warning in recommendation.warnings:
        lower = warning.lower()
        if "latex" in lower or "format" in lower or "missing" in lower:
            penalties += 5
            issues.append(f"Recommendation warning affects formatting quality: {warning}")

    format_score = max(0.0, 100.0 - penalties)
    return format_score, _dedupe_strings(issues)


def _normalize_keyword(keyword: str) -> str:
    normalized = re.sub(r"\s+", " ", keyword.strip().lower())
    normalized = re.sub(r"[^\w\s.+#/-]", "", normalized)
    return normalized.strip()


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^\w\s.+#/-]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _build_resume_corpus(recommendation: ResumeRecommendation) -> dict[str, str]:
    """Build normalized section text used for keyword matching."""
    experience_parts: list[str] = []
    project_parts: list[str] = []
    skills_parts: list[str] = []
    cert_parts: list[str] = []

    for exp in recommendation.experience:
        if not exp.included:
            continue
        experience_parts.extend([exp.title, exp.company])
        experience_parts.extend(
            bullet.text for bullet in exp.bullets if bullet.status != BulletStatus.REJECTED
        )

    for proj in recommendation.projects:
        if not proj.included:
            continue
        project_parts.append(proj.name)
        project_parts.extend(
            bullet.text for bullet in proj.bullets if bullet.status != BulletStatus.REJECTED
        )
        project_parts.extend(proj.technologies)

    for group in recommendation.skills:
        skills_parts.append(group.category)
        skills_parts.extend(group.skills)

    for cert in recommendation.certifications:
        if not cert.included:
            continue
        cert_parts.append(cert.name)
        if cert.issuing_org:
            cert_parts.append(cert.issuing_org)

    return {
        "target_title": _normalize_text(recommendation.target_title or ""),
        "summary": _normalize_text(recommendation.summary or ""),
        "skills": _normalize_text(" ".join(skills_parts)),
        "experience": _normalize_text(" ".join(experience_parts)),
        "projects": _normalize_text(" ".join(project_parts)),
        "certifications": _normalize_text(" ".join(cert_parts)),
        "body": _normalize_text(
            " ".join(
                [
                    recommendation.target_title or "",
                    recommendation.summary or "",
                    " ".join(experience_parts),
                    " ".join(project_parts),
                    " ".join(skills_parts),
                    " ".join(cert_parts),
                ]
            )
        ),
    }


def _match_keyword(keyword: str, corpus: dict[str, str]) -> tuple[bool, str]:
    """Match a keyword against the normalized corpus using phrase-aware rules."""
    normalized_keyword = _normalize_keyword(keyword)
    if not normalized_keyword:
        return False, ""

    is_phrase = " " in normalized_keyword
    pattern = (
        re.compile(rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)")
        if is_phrase
        else re.compile(rf"\b{re.escape(normalized_keyword)}\b")
    )

    section_order = ["target_title", "summary", "skills", "experience", "projects", "certifications", "body"]
    for section in section_order:
        if pattern.search(corpus[section]):
            return True, section
    return False, ""


def _dedupe_jd_keywords(parsed_jd: ParsedJD) -> list[str]:
    """Normalize and dedupe JD keywords, preserving phrases and input order."""
    deduped: list[str] = []
    seen: set[str] = set()

    for keyword in parsed_jd.keywords:
        normalized = _normalize_keyword(keyword.keyword)
        if not normalized or normalized in seen:
            continue
        if normalized in _TRIVIAL_KEYWORDS:
            continue
        if len(normalized) <= 2 and " " not in normalized:
            continue
        seen.add(normalized)
        deduped.append(keyword.keyword.strip())

    return deduped


def _critical_keywords(parsed_jd: ParsedJD) -> list[str]:
    """Critical missing keywords come from required skills and high-importance JD keywords."""
    candidates: list[str] = []
    seen: set[str] = set()

    for skill in parsed_jd.required_skills:
        normalized = _normalize_keyword(skill)
        if normalized and normalized not in seen:
            seen.add(normalized)
            candidates.append(skill.strip())

    for keyword in parsed_jd.keywords:
        if keyword.importance not in ("critical", "high"):
            continue
        normalized = _normalize_keyword(keyword.keyword)
        if not normalized or normalized in seen or normalized in _TRIVIAL_KEYWORDS:
            continue
        seen.add(normalized)
        candidates.append(keyword.keyword.strip())

    return candidates


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
