"""
Scoring service — deterministic ATS score computation.

This runs AFTER human review to give the user quality feedback.
No AI involved — pure rule-based scoring.

Measures resume-to-JD alignment, not truthfulness or evidence.
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
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.resume import ResumeRecommendation, BulletStatus
from app.schemas.scoring import (
    ATSScore,
    KeywordMatch,
    KeywordScore,
    ReadabilityScore,
    SkillScore,
    SectionScore,
)

logger = logging.getLogger(__name__)

_TRIVIAL_KEYWORDS = {
    "and", "the", "for", "with", "our", "your", "you", "will", "role", "team", "job",
    "work", "using", "experience", "skills", "skill", "required", "preferred",
}


def compute_ats_score(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> ATSScore:
    """
    Compute the composite ATS score for a resume recommendation.
    Called after the user finishes reviewing.

    Measures resume-to-JD alignment only - no truthfulness or evidence validation.
    """
    keyword_score = _compute_keyword_score(recommendation, parsed_jd, ats_plan)
    skill_score = _compute_skill_score(recommendation, parsed_jd, ats_plan)
    readability = _compute_readability_score(recommendation)
    format_score, format_issues = _compute_format_score(recommendation)
    section_score = _compute_section_score(recommendation)
    responsibility_score = _compute_responsibility_score(recommendation, parsed_jd)
    title_alignment_score = _compute_title_alignment_score(recommendation, parsed_jd)

    overall = (
        keyword_score.coverage_percent * 0.30
        + skill_score.required_coverage_percent * 0.20
        + skill_score.preferred_coverage_percent * 0.10
        + responsibility_score * 0.10
        + title_alignment_score * 0.10
        + format_score * 0.10
        + section_score.score * 0.10
    )

    missing_keywords = list(keyword_score.critical_missing)

    warnings: list[str] = []
    recommendations_list: list[str] = []

    if keyword_score.coverage_percent < MIN_KEYWORD_COVERAGE_PERCENT:
        warnings.append(
            f"Keyword coverage is {keyword_score.coverage_percent:.0f}% — "
            f"below the {MIN_KEYWORD_COVERAGE_PERCENT}% threshold."
        )
    if keyword_score.critical_missing:
        warnings.append(
            f"Missing keywords: {', '.join(keyword_score.critical_missing[:5])}"
        )
    if section_score.missing_sections:
        recommendations_list.append(
            f"Fill missing sections: {', '.join(section_score.missing_sections[:3])}"
        )
    if format_score < 100:
        recommendations_list.extend(format_issues[:2])
    if readability.score < 70:
        recommendations_list.append(
            "Improve bullet readability: start with action verbs and keep bullets concise."
        )

    return ATSScore(
        overall_score=round(overall, 1),
        keyword_score=keyword_score,
        skill_score=skill_score,
        readability_score=readability,
        format_score=round(format_score, 1),
        section_score=section_score,
        responsibility_score=round(responsibility_score, 1),
        title_alignment_score=round(title_alignment_score, 1),
        missing_keywords=missing_keywords,
        warnings=warnings,
        recommendations=recommendations_list,
    )


def _compute_keyword_score(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> KeywordScore:
    """Check how many distinct JD keywords appear in the resume content."""
    corpus = _build_resume_corpus(recommendation)
    normalized_keywords = _dedupe_jd_keywords(parsed_jd, ats_plan)
    critical_candidates = _critical_keywords(parsed_jd, ats_plan)

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


def _compute_skill_score(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> SkillScore:
    """Compute required and preferred skills coverage."""
    corpus = _build_resume_corpus(recommendation)

    required_skills = list(parsed_jd.required_skills)
    if ats_plan:
        required_skills.extend(ats_plan.must_include_skills)

    required_matched = 0
    for skill in required_skills:
        if _keyword_in_text(skill, corpus["body"]):
            required_matched += 1

    preferred_skills = list(parsed_jd.preferred_skills or [])
    preferred_matched = 0
    for skill in preferred_skills:
        if _keyword_in_text(skill, corpus["body"]):
            preferred_matched += 1

    return SkillScore(
        required_total=len(required_skills) or 1,
        required_matched=required_matched,
        required_coverage_percent=round((required_matched / max(len(required_skills), 1)) * 100, 1),
        preferred_total=len(preferred_skills) or 1,
        preferred_matched=preferred_matched,
        preferred_coverage_percent=round((preferred_matched / max(len(preferred_skills), 1)) * 100, 1) if preferred_skills else 100.0,
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
    """Compute formatting/parseability score - penalize only structural issues."""
    penalties = 0.0
    issues: list[str] = []

    if not recommendation.contact.full_name.strip():
        penalties += 15
        issues.append("Contact name is missing.")
    if not recommendation.contact.email.strip():
        penalties += 15
        issues.append("Contact email is missing.")

    if not recommendation.summary:
        penalties += 10
        issues.append("Professional summary is missing.")
    elif len(recommendation.summary.split()) > 70:
        penalties += 8
        issues.append("Professional summary is too long for a one-page ATS resume.")

    included_experience = [exp for exp in recommendation.experience if exp.included]
    included_projects = [proj for proj in recommendation.projects if proj.included]

    for exp in included_experience:
        if len(exp.bullets) > 5:
            penalties += 3
            issues.append(f"Experience '{exp.title}' has too many bullets.")
        if not exp.bullets:
            penalties += 5
            issues.append(f"Experience '{exp.title}' has no bullets.")

    for proj in included_projects:
        if len(proj.bullets) > 5:
            penalties += 2
            issues.append(f"Project '{proj.name}' has too many bullets.")
        if not proj.bullets:
            penalties += 3
            issues.append(f"Project '{proj.name}' has no bullets.")

    has_corrupted = _has_corrupted_chars(recommendation)
    if has_corrupted:
        penalties += 20
        issues.append("Resume contains corrupted/non-ASCII characters that may break ATS parsing.")

    format_score = max(0.0, 100.0 - penalties)
    return format_score, _dedupe_strings(issues)


def _has_corrupted_chars(recommendation: ResumeRecommendation) -> bool:
    """Check for corrupted or unusual characters that break ATS."""
    text = _get_raw_resume_text(recommendation)
    corrupted_patterns = [
        r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
        r"[Â¤Â®Â©Â™Â£Â¥Â€Â§Â¶Â©Â®Â°Â±Â²Â³ÂµÂ¹ÂºÂ»Â¼Â½Â¾Â¿]",
    ]
    for pattern in corrupted_patterns:
        if re.search(pattern, text):
            return True
    if re.search(r"[^\x00-\x7F]", text):
        return True
    return False


def _get_raw_resume_text(recommendation: ResumeRecommendation) -> str:
    """Get raw text from resume without normalization."""
    parts = [
        recommendation.target_title or "",
        recommendation.summary or "",
    ]
    for exp in recommendation.experience:
        if not exp.included:
            continue
        parts.extend([exp.title, exp.company])
        for bullet in exp.bullets:
            if bullet.status != BulletStatus.REJECTED:
                parts.append(bullet.text)
    for proj in recommendation.projects:
        if not proj.included:
            continue
        parts.append(proj.name)
        for bullet in proj.bullets:
            if bullet.status != BulletStatus.REJECTED:
                parts.append(bullet.text)
        parts.extend(proj.technologies)
    for group in recommendation.skills:
        parts.append(group.category)
        parts.extend(group.skills)
    return " ".join(parts)


def _compute_section_score(recommendation: ResumeRecommendation) -> SectionScore:
    """Compute section completeness score."""
    missing_sections = []

    has_contact = bool(recommendation.contact.full_name.strip() and recommendation.contact.email.strip())
    if not has_contact:
        missing_sections.append("Contact")

    has_summary = bool(recommendation.summary and recommendation.summary.strip())
    if not has_summary:
        missing_sections.append("Summary")

    has_experience = any(exp.bullets for exp in recommendation.experience if exp.included)
    if not has_experience:
        missing_sections.append("Experience")

    has_skills = any(group.skills for group in recommendation.skills)
    if not has_skills:
        missing_sections.append("Skills")

    has_education = bool(recommendation.education)
    if not has_education:
        missing_sections.append("Education")

    checks = [has_contact, has_summary, has_experience, has_skills, has_education]
    score = sum(1 for check in checks if check) / len(checks) * 100

    return SectionScore(
        score=round(score, 1),
        missing_sections=missing_sections,
        has_contact=has_contact,
        has_summary=has_summary,
        has_experience=has_experience,
        has_skills=has_skills,
        has_education=has_education,
    )


def _compute_responsibility_score(recommendation: ResumeRecommendation, parsed_jd: ParsedJD) -> float:
    """Compute responsibility coverage score."""
    if not parsed_jd.responsibilities:
        return 100.0
    corpus = _build_resume_corpus(recommendation)["body"]
    matched = sum(1 for responsibility in parsed_jd.responsibilities if _keyword_in_text(responsibility, corpus))
    return round((matched / len(parsed_jd.responsibilities)) * 100, 1)


def _compute_title_alignment_score(recommendation: ResumeRecommendation, parsed_jd: ParsedJD) -> float:
    """Compute job title alignment score."""
    if not parsed_jd.job_title:
        return 100.0

    resume_title = (recommendation.target_title or "").lower()
    jd_title = parsed_jd.job_title.lower()

    if jd_title in resume_title:
        return 100.0

    resume_words = set(re.sub(r"[^\w\s]", " ", resume_title).split())
    jd_words = set(re.sub(r"[^\w\s]", " ", jd_title).split())
    jd_words = {w for w in jd_words if len(w) > 2}

    if not jd_words:
        return 100.0

    matches = len(resume_words & jd_words)
    return round((matches / len(jd_words)) * 100, 1)


def _keyword_in_text(keyword: str, text: str) -> bool:
    normalized_keyword = _normalize_keyword(keyword)
    if not normalized_keyword:
        return False
    pattern = (
        re.compile(rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)")
        if " " in normalized_keyword
        else re.compile(rf"\b{re.escape(normalized_keyword)}\b")
    )
    return bool(pattern.search(text))


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


def _dedupe_jd_keywords(
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> list[str]:
    """Normalize and dedupe JD keywords, preserving phrases and input order."""
    deduped: list[str] = []
    seen: set[str] = set()

    planner_values = [
        *(
            [
                *ats_plan.priority_keywords,
                *ats_plan.must_include_skills,
                *ats_plan.must_include_tools_platforms,
                *ats_plan.must_include_responsibilities,
            ]
            if ats_plan
            else []
        ),
        *[keyword.keyword for keyword in parsed_jd.keywords],
    ]

    for keyword in planner_values:
        normalized = _normalize_keyword(keyword)
        if not normalized or normalized in seen:
            continue
        if normalized in _TRIVIAL_KEYWORDS:
            continue
        if len(normalized) <= 2 and " " not in normalized:
            continue
        seen.add(normalized)
        deduped.append(keyword.strip())

    return deduped


def _critical_keywords(
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> list[str]:
    """Critical missing keywords come from required skills and high-importance JD keywords."""
    candidates: list[str] = []
    seen: set[str] = set()

    for skill in ([*ats_plan.must_include_skills, *ats_plan.priority_keywords] if ats_plan else parsed_jd.required_skills):
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