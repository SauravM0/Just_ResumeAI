from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import ResumeRecommendation
from app.schemas.scoring import ATSScore
from app.services.bullet_quality_service import has_jd_boilerplate

logger = logging.getLogger(__name__)


class RecruiterReview(BaseModel):
    passed: bool = True
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    summary: str = ""
    overall_impression: float = Field(default=7.0, ge=0.0, le=10.0)
    summary_assessment: str = ""
    weak_bullet_ids: list[str] = Field(default_factory=list)
    strong_bullet_examples: list[str] = Field(default_factory=list)
    cliche_count: int = 0
    hr_flags: list[str] = Field(default_factory=list)
    recommended_for_shortlist: bool = True


class RecruiterReviewAgent:
    def run(
        self,
        recommendation: ResumeRecommendation,
        ats_score: ATSScore | None = None,
        parsed_jd: ParsedJD | None = None,
        profile: MasterProfile | None = None,
    ) -> RecruiterReview:
        logger.info("resume_agent.recruiter_review_agent.started")
        issues: list[str] = []
        warnings: list[str] = []
        bullet_items = [
            (bullet.id, bullet.text)
            for entry in [*recommendation.experience, *recommendation.projects]
            for bullet in entry.bullets
        ]
        bullets = [text for _, text in bullet_items]
        if any(has_jd_boilerplate(text) for text in bullets):
            issues.append("Resume bullets include job-description boilerplate.")
        if ats_score and _has_blocking_keyword_stuffing(recommendation, ats_score):
            issues.append("Resume text reads like keyword stuffing.")
        if ats_score and ats_score.stuffing_warnings:
            warnings.extend(ats_score.stuffing_warnings[:3])
        if ats_score and ats_score.readability_score.issues:
            warnings.extend(ats_score.readability_score.issues[:6])
        if ats_score and ats_score.anti_stuffing_score < 70:
            warnings.append("Keyword repetition is high enough to reduce recruiter readability.")
        if recommendation.summary and len(recommendation.summary.split()) > 130:
            warnings.append("Summary is long for a recruiter first pass.")
        if len(bullets) and sum(len(text.split()) for text in bullets) / len(bullets) > 38:
            warnings.append("Average bullet length is high for a quick recruiter scan.")
        weak_bullet_ids = [
            bullet_id
            for bullet_id, text in bullet_items
            if _looks_weak_to_recruiter(text)
        ][:8]
        cliche_count = sum(_cliche_count(text) for text in [recommendation.summary or "", *bullets])
        if cliche_count:
            warnings.append(f"{cliche_count} recruiter cliche phrases detected.")
        strong_examples = [
            text for text in bullets
            if _looks_strong_to_recruiter(text)
        ][:3]
        if len(weak_bullet_ids) >= 3:
            warnings.append("Several bullets are too vague for a recruiter first pass.")
        passed = not issues
        overall_impression = _overall_impression(
            ats_score=ats_score,
            issues=issues,
            warnings=warnings,
            weak_bullet_ids=weak_bullet_ids,
            cliche_count=cliche_count,
        )
        summary = (
            "Recruiter review passed with no blocking readability or truthfulness flags."
            if passed
            else "Recruiter review found blocking resume quality flags."
        )
        summary_assessment = _summary_assessment(overall_impression, weak_bullet_ids, cliche_count)
        hr_flags = _dedupe([*issues, *warnings])[:8]
        logger.info(
            "resume_agent.recruiter_review_agent.completed passed=%s impression=%.1f issues=%s warnings=%s weak_bullets=%s",
            passed,
            overall_impression,
            len(issues),
            len(warnings),
            len(weak_bullet_ids),
        )
        return RecruiterReview(
            passed=passed,
            issues=_dedupe(issues),
            warnings=_dedupe(warnings),
            summary=summary,
            overall_impression=overall_impression,
            summary_assessment=summary_assessment,
            weak_bullet_ids=weak_bullet_ids,
            strong_bullet_examples=strong_examples,
            cliche_count=cliche_count,
            hr_flags=hr_flags,
            recommended_for_shortlist=overall_impression >= 7.0 and passed,
        )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


recruiter_review_agent = RecruiterReviewAgent()


_COMMA_KEYWORD_BLOCK_RE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+#./-]+(?:\s*,\s*|\s*,\s*and\s*)){4,}",
    re.IGNORECASE,
)


def _has_blocking_keyword_stuffing(recommendation: ResumeRecommendation, ats_score: ATSScore) -> bool:
    """Block only visible keyword dumps; repetition-only scoring stays a warning."""
    if _COMMA_KEYWORD_BLOCK_RE.search(recommendation.summary or ""):
        return True

    bullets = [
        bullet.text or ""
        for entry in [*recommendation.experience, *recommendation.projects]
        for bullet in entry.bullets
    ]
    if any(_looks_like_keyword_list(text) for text in bullets):
        return True

    severe_fragments = (
        "comma-separated keyword block detected in summary",
        "summary contains",
    )
    has_summary_dump_warning = any(
        any(fragment in warning.casefold() for fragment in severe_fragments)
        for warning in ats_score.stuffing_warnings
    )
    return has_summary_dump_warning and _COMMA_KEYWORD_BLOCK_RE.search(recommendation.summary or "") is not None


def _looks_like_keyword_list(text: str) -> bool:
    words = re.findall(r"[a-z0-9][a-z0-9+#./-]*", text or "", re.IGNORECASE)
    if len(words) < 5:
        return False
    comma_count = (text or "").count(",")
    return comma_count >= 4 and len(words) <= comma_count + 6


_CLICHE_RE = re.compile(
    r"\b(?:responsible for|worked on|hard[- ]working|team player|"
    r"detail[- ]oriented|go[- ]getter|fast learner|self[- ]motivated)\b",
    re.IGNORECASE,
)


def _cliche_count(text: str) -> int:
    return len(_CLICHE_RE.findall(text or ""))


def _looks_weak_to_recruiter(text: str) -> bool:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return True
    if len(cleaned.split()) < 8:
        return True
    if _CLICHE_RE.search(cleaned):
        return True
    has_action = bool(re.match(r"^[A-Z][a-z]+(?:ed|t)?\b", cleaned))
    has_outcome = bool(re.search(r"\b(?:improved|reduced|increased|delivered|enabled|supporting|handling|resulting|by \d+|\d+%)\b", cleaned, re.IGNORECASE))
    return not (has_action and has_outcome)


def _looks_strong_to_recruiter(text: str) -> bool:
    cleaned = " ".join((text or "").split())
    return bool(
        len(cleaned.split()) >= 10
        and re.search(r"\b(?:built|developed|implemented|optimized|automated|delivered|engineered|designed)\b", cleaned, re.IGNORECASE)
        and re.search(r"\b(?:improved|reduced|increased|delivered|enabled|supporting|handling|by \d+|\d+%)\b", cleaned, re.IGNORECASE)
    )


def _overall_impression(
    *,
    ats_score: ATSScore | None,
    issues: list[str],
    warnings: list[str],
    weak_bullet_ids: list[str],
    cliche_count: int,
) -> float:
    base = 7.5
    if ats_score:
        base = max(4.0, min(9.0, ats_score.overall_score / 12.0))
    base -= len(issues) * 1.5
    base -= min(len(warnings), 5) * 0.2
    base -= min(len(weak_bullet_ids), 6) * 0.35
    base -= min(cliche_count, 5) * 0.25
    return round(max(0.0, min(10.0, base)), 1)


def _summary_assessment(overall_impression: float, weak_bullet_ids: list[str], cliche_count: int) -> str:
    if overall_impression >= 8:
        return "Strong recruiter first pass with clear role fit and credible impact."
    if overall_impression >= 6:
        return "Moderate recruiter first pass; polish weak bullets to improve shortlist confidence."
    if weak_bullet_ids or cliche_count:
        return "Recruiter impact is limited by vague or cliched bullets that need stronger outcomes."
    return "Recruiter impact is currently below shortlist quality and needs refinement."
