"""
Scoring service — deterministic ATS score computation.

This runs AFTER human review to give the user quality feedback.
No AI involved — pure rule-based scoring.
"""

from __future__ import annotations

import re
import logging

from app.domain.rules import (
    SCORE_WEIGHT_KEYWORD,
    SCORE_WEIGHT_READABILITY,
    SCORE_WEIGHT_FORMAT,
    MIN_KEYWORD_COVERAGE_PERCENT,
    ACTION_VERBS,
    MIN_BULLET_LENGTH,
    MAX_BULLET_LENGTH,
)
from app.schemas.jd import ParsedJD
from app.schemas.resume import ResumeRecommendation, BulletStatus
from app.schemas.scoring import (
    ATSScore,
    KeywordScore,
    KeywordMatch,
    ReadabilityScore,
)

logger = logging.getLogger(__name__)


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

    # Format is always 100 because we use a fixed ATS-friendly template
    format_score = 100.0

    overall = (
        keyword_score.coverage_percent * SCORE_WEIGHT_KEYWORD
        + readability.score * SCORE_WEIGHT_READABILITY
        + format_score * SCORE_WEIGHT_FORMAT
    )

    warnings = []
    recommendations_list = []

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

    return ATSScore(
        overall_score=round(overall, 1),
        keyword_score=keyword_score,
        readability_score=readability,
        format_score=format_score,
        warnings=warnings,
        recommendations=recommendations_list,
    )


def _compute_keyword_score(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
) -> KeywordScore:
    """Check how many JD keywords appear in the resume content."""
    # Collect all resume text
    resume_text = _collect_resume_text(recommendation).lower()

    details = []
    matched = 0
    critical_missing = []

    for jd_kw in parsed_jd.keywords:
        kw_lower = jd_kw.keyword.lower()
        found = kw_lower in resume_text

        location = ""
        if found:
            matched += 1
            # Determine where it was found (approximate)
            if kw_lower in (recommendation.summary or "").lower():
                location = "summary"
            else:
                location = "body"
        elif jd_kw.importance in ("critical", "high"):
            critical_missing.append(jd_kw.keyword)

        details.append(KeywordMatch(keyword=jd_kw.keyword, found=found, location=location))

    total = len(parsed_jd.keywords) or 1  # avoid division by zero
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
    all_bullets = []
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

    issues = []
    total_len = 0
    good_bullets = 0

    for text in all_bullets:
        total_len += len(text)

        # Check action verb
        first_word = text.split()[0].lower().rstrip(",.:;") if text.split() else ""
        starts_with_action = first_word in ACTION_VERBS

        # Check length
        good_length = MIN_BULLET_LENGTH <= len(text) <= MAX_BULLET_LENGTH

        # Check passive voice (simple heuristic)
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
        issues=issues[:15],  # Cap for readability
    )


def _collect_resume_text(recommendation: ResumeRecommendation) -> str:
    """Collect all text content from the resume for keyword analysis."""
    parts = []
    if recommendation.summary:
        parts.append(recommendation.summary)
    if recommendation.target_title:
        parts.append(recommendation.target_title)

    for exp in recommendation.experience:
        parts.append(exp.title)
        parts.append(exp.company)
        for b in exp.bullets:
            if b.status != BulletStatus.REJECTED:
                parts.append(b.text)

    for proj in recommendation.projects:
        parts.append(proj.name)
        for b in proj.bullets:
            if b.status != BulletStatus.REJECTED:
                parts.append(b.text)

    for sg in recommendation.skills:
        parts.append(sg.category)
        parts.extend(sg.skills)

    for cert in recommendation.certifications:
        parts.append(cert.name)
        if cert.issuing_org:
            parts.append(cert.issuing_org)

    return " ".join(parts)
