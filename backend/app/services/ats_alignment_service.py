from __future__ import annotations

import re
from collections import OrderedDict

from app.schemas.alignment import ATSAlignmentReport
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.resume import ResumeRecommendation, BulletStatus
from app.services.keyword_placement_service import analyze_keyword_placement
from app.services.synonym_service import get_all_forms


def build_ats_alignment_report(
    parsed_jd: ParsedJD,
    recommendation: ResumeRecommendation,
    formatting_score: float | None = None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> ATSAlignmentReport:
    """Compare parsed JD terms with the generated resume to guide ATS optimization."""
    important_keywords = _important_keywords(parsed_jd)
    resume_corpus = _resume_corpus(recommendation)

    included: list[str] = []
    missing: list[str] = []
    for keyword in important_keywords:
        if _contains_keyword(resume_corpus, keyword):
            included.append(keyword)
        else:
            missing.append(keyword)

    keyword_coverage = (len(included) / len(important_keywords) * 100) if important_keywords else 100.0
    section_score = _section_completeness_score(recommendation)
    format_score = 100.0 if formatting_score is None else formatting_score
    responsibility_score = _responsibility_coverage(parsed_jd.responsibilities, resume_corpus)
    placement_report = analyze_keyword_placement(recommendation, parsed_jd, ats_plan)

    # Keep this aligned with external ATS behavior: keyword/title gaps should
    # dominate the report instead of being hidden by good section completeness.
    overall = (
        keyword_coverage * 0.72
        + responsibility_score * 0.12
        + format_score * 0.08
        + section_score * 0.08
    )
    if keyword_coverage < 50:
        overall -= (50 - keyword_coverage) * 0.30
    elif keyword_coverage < 65:
        overall -= (65 - keyword_coverage) * 0.15
    overall = _clamp_percent(overall)

    return ATSAlignmentReport(
        overall_alignment_percent=round(overall, 1),
        keyword_coverage_percent=round(keyword_coverage, 1),
        formatting_score=round(format_score, 1),
        section_completeness_score=round(section_score, 1),
        jd_title_detected=parsed_jd.job_title or "",
        required_skills=list(parsed_jd.required_skills),
        preferred_skills=list(parsed_jd.preferred_skills),
        role_responsibilities=list(parsed_jd.responsibilities),
        important_ats_keywords=important_keywords,
        keywords_included=included,
        keywords_missing=missing,
        keyword_placement=placement_report,
        suggestions=_suggestions(parsed_jd, missing, recommendation, placement_report),
        resume_rewrite_strategy=_rewrite_strategy(parsed_jd, missing, placement_report),
    )


def _important_keywords(parsed_jd: ParsedJD) -> list[str]:
    values: list[str] = []
    values.append(parsed_jd.job_title or "")
    values.extend(parsed_jd.required_skills)
    values.extend(parsed_jd.preferred_skills)
    values.extend(req.text for req in parsed_jd.requirements)
    values.extend(parsed_jd.responsibilities)
    values.extend(
        keyword.keyword
        for keyword in parsed_jd.keywords
        if keyword.importance in {"critical", "high", "medium"}
    )

    deduped: OrderedDict[str, str] = OrderedDict()
    for value in values:
        cleaned = str(value).strip()
        key = _normalize(cleaned)
        if not key or key in _TRIVIAL_TERMS:
            continue
        if len(key) <= 2 and " " not in key:
            continue
        deduped.setdefault(key, cleaned)
    return list(deduped.values())


def _resume_corpus(recommendation: ResumeRecommendation) -> str:
    parts: list[str] = [
        recommendation.target_title or "",
        recommendation.summary or "",
    ]
    for group in recommendation.skills:
        parts.append(group.category)
        parts.extend(group.skills)
    for exp in recommendation.experience:
        if not exp.included:
            continue
        parts.extend([exp.title, exp.company])
        parts.extend(bullet.text for bullet in exp.bullets if bullet.status != BulletStatus.REJECTED)
    for project in recommendation.projects:
        if not project.included:
            continue
        parts.extend([project.name, project.description or ""])
        parts.extend(project.technologies)
        parts.extend(bullet.text for bullet in project.bullets if bullet.status != BulletStatus.REJECTED)
    for cert in recommendation.certifications:
        if cert.included:
            parts.extend([cert.name, cert.issuing_org or ""])
    for achievement in [*recommendation.achievements, *recommendation.awards]:
        if achievement.included:
            parts.extend([achievement.title, achievement.issuer or "", achievement.description or ""])
    return _normalize(" ".join(parts))


def _contains_keyword(corpus: str, keyword: str) -> bool:
    return any(_contains_keyword_exact(corpus, form) for form in get_all_forms(keyword))


def _contains_keyword_exact(corpus: str, keyword: str) -> bool:
    normalized = _normalize(keyword)
    if not normalized:
        return False
    variants = {
        normalized,
        normalized.replace("/", " "),
        normalized.replace("/", ""),
        normalized.replace("-", " "),
    }
    return any(re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", corpus) for variant in variants if variant)


def _responsibility_coverage(responsibilities: list[str], corpus: str) -> float:
    if not responsibilities:
        return 100.0
    covered = sum(1 for responsibility in responsibilities if _contains_keyword(corpus, responsibility))
    return covered / len(responsibilities) * 100


def _section_completeness_score(recommendation: ResumeRecommendation) -> float:
    checks = [
        bool(recommendation.target_title.strip()),
        bool(recommendation.summary and recommendation.summary.strip()),
        bool(recommendation.experience),
        any(exp.bullets for exp in recommendation.experience if exp.included),
        any(group.skills for group in recommendation.skills),
        bool(recommendation.education),
    ]
    if recommendation.projects:
        checks.append(any(project.bullets or project.technologies for project in recommendation.projects if project.included))
    if recommendation.certifications:
        checks.append(any(cert.included for cert in recommendation.certifications))
    return sum(1 for check in checks if check) / len(checks) * 100


def _suggestions(parsed_jd: ParsedJD, missing: list[str], recommendation: ResumeRecommendation, placement_report) -> list[str]:
    suggestions: list[str] = []
    if parsed_jd.job_title and not _contains_keyword(_normalize(recommendation.target_title), parsed_jd.job_title):
        suggestions.append(f"Use the JD title '{parsed_jd.job_title}' in the resume headline.")
    if placement_report.missing_high_priority_keywords:
        suggestions.append("Add missing important keywords naturally to the title, summary, skills, or strongest bullets.")
    if placement_report.weakly_placed_keywords:
        suggestions.append("Move weakly placed important keywords into the summary, skills, or first experience bullets.")
    if missing:
        suggestions.append("Add missing JD keywords to the summary, skills, and the most relevant experience bullets.")
        suggestions.append("Mirror the JD's responsibility verbs in bullets where they fit the role narrative.")
        suggestions.append("Group required tools and platforms into a dedicated technical skills line for ATS parsing.")
    if not recommendation.summary:
        suggestions.append("Add a concise summary that includes the JD title and top required skills.")
    return suggestions[:6]


def _rewrite_strategy(parsed_jd: ParsedJD, missing: list[str], placement_report) -> str:
    placement_terms = [
        *placement_report.missing_high_priority_keywords,
        *placement_report.weakly_placed_keywords,
    ]
    top_terms = ", ".join(_dedupe_strings(placement_terms + missing)[:8]) if (placement_terms or missing) else "the strongest JD keywords already present"
    title = parsed_jd.job_title or "the target role"
    return (
        f"Position the resume directly for {title}; prioritize required skills and responsibilities, "
        f"then weave {top_terms} into the headline, summary, skills, and high-impact bullets."
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = value.strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _clamp_percent(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 100.0:
        return 100.0
    return value


def _normalize(value: str | None) -> str:
    text = (value or "").lower()
    text = text.replace("react.js", "react").replace("node.js", "node")
    text = re.sub(r"[^a-z0-9+#/.\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_TRIVIAL_TERMS = {
    "and", "the", "for", "with", "our", "your", "you", "will", "role", "team", "job",
    "work", "using", "experience", "skills", "skill", "required", "preferred",
}
