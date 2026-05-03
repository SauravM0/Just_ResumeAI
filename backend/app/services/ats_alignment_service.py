from __future__ import annotations

import re
from collections import OrderedDict

from app.schemas.alignment import ATSAlignmentReport
from app.schemas.jd import ParsedJD
from app.schemas.resume import ResumeRecommendation, BulletStatus


def build_ats_alignment_report(
    parsed_jd: ParsedJD,
    recommendation: ResumeRecommendation,
    formatting_score: float | None = None,
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

    overall = (
        keyword_coverage * 0.55
        + section_score * 0.20
        + format_score * 0.15
        + responsibility_score * 0.10
    )

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
        suggestions=_suggestions(parsed_jd, missing, recommendation),
        resume_rewrite_strategy=_rewrite_strategy(parsed_jd, missing),
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
    return _normalize(" ".join(parts))


def _contains_keyword(corpus: str, keyword: str) -> bool:
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


def _suggestions(parsed_jd: ParsedJD, missing: list[str], recommendation: ResumeRecommendation) -> list[str]:
    suggestions: list[str] = []
    if parsed_jd.job_title and not _contains_keyword(_normalize(recommendation.target_title), parsed_jd.job_title):
        suggestions.append(f"Use the JD title '{parsed_jd.job_title}' in the resume headline.")
    if missing:
        suggestions.append("Add missing JD keywords to the summary, skills, and the most relevant experience bullets.")
        suggestions.append("Mirror the JD's responsibility verbs in bullets where they fit the role narrative.")
        suggestions.append("Group required tools and platforms into a dedicated technical skills line for ATS parsing.")
    if not recommendation.summary:
        suggestions.append("Add a concise summary that includes the JD title and top required skills.")
    return suggestions[:6]


def _rewrite_strategy(parsed_jd: ParsedJD, missing: list[str]) -> str:
    top_terms = ", ".join(missing[:8]) if missing else "the strongest JD keywords already present"
    title = parsed_jd.job_title or "the target role"
    return (
        f"Position the resume directly for {title}; prioritize required skills and responsibilities, "
        f"then weave {top_terms} into the headline, summary, skills, and high-impact bullets."
    )


def _normalize(value: str | None) -> str:
    text = (value or "").lower()
    text = text.replace("react.js", "react").replace("node.js", "node")
    text = re.sub(r"[^a-z0-9+#/.\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_TRIVIAL_TERMS = {
    "and", "the", "for", "with", "our", "your", "you", "will", "role", "team", "job",
    "work", "using", "experience", "skills", "skill", "required", "preferred",
}
