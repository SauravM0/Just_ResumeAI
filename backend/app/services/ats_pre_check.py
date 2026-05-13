"""Post-generation ATS readiness checks before LaTeX/PDF output."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import string

from app.domain.rules import ACTION_VERBS
from app.schemas.jd import ParsedJD
from app.schemas.resume import ResumeRecommendation


@dataclass
class ATSPreCheckResult:
    overall_estimated_ats_score: float = 0.0
    critical_gaps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)


_TOKEN_RE = re.compile(r"[a-z0-9+#./-]+", re.IGNORECASE)
_ACTION_VERBS = {verb.casefold() for verb in ACTION_VERBS}


def validate_ats_readiness(rec: ResumeRecommendation, parsed_jd: ParsedJD) -> ATSPreCheckResult:
    """Return structured ATS risks so the API can surface fixable quality issues."""
    result = ATSPreCheckResult()
    resume_text = _resume_text(rec)
    normalized_resume = _normalize(resume_text)

    jd_keywords = _critical_keywords(parsed_jd)
    missing = [keyword for keyword in jd_keywords if not _keyword_present(keyword, normalized_resume)]
    if missing:
        result.critical_gaps.append(f"Missing critical JD keywords: {', '.join(missing[:8])}")
    else:
        result.passed_checks.append("All critical JD keywords appear in the resume text.")

    skill_text = _normalize(" ".join(skill for group in rec.skills for skill in group.skills))
    missing_skills = [keyword for keyword in jd_keywords if not _keyword_present(keyword, skill_text)]
    if missing_skills:
        result.warnings.append(f"Technical Skills missing priority terms: {', '.join(missing_skills[:8])}")
    else:
        result.passed_checks.append("Technical Skills covers the priority JD terms.")

    summary_words = len((rec.summary or "").split())
    if summary_words < 60:
        result.warnings.append(f"Summary is only {summary_words} words; target 70-120 for ATS keyword density.")
    else:
        result.passed_checks.append("Summary length supports keyword density.")

    bullets = [bullet.text for exp in rec.experience for bullet in exp.bullets]
    bullets.extend(bullet.text for project in rec.projects for bullet in project.bullets)
    if bullets:
        compliant = sum(1 for bullet in bullets if _starts_with_action_verb(bullet))
        ratio = compliant / len(bullets)
        if ratio < 0.70:
            result.warnings.append(f"Only {ratio:.0%} of bullets start with action verbs; target is at least 70%.")
        else:
            result.passed_checks.append("Most bullets start with strong action verbs.")

    for exp in rec.experience:
        if len(exp.bullets) < 3:
            result.warnings.append(f"Experience '{exp.title}' has only {len(exp.bullets)} bullets; target 3+.")
    for project in rec.projects:
        if len(project.bullets) < 3:
            result.warnings.append(f"Project '{project.name}' has only {len(project.bullets)} bullets; target 3+.")

    soft_skill_hits = [
        skill for group in rec.skills for skill in group.skills
        if any(phrase in skill.casefold() for phrase in ("basic technical knowledge", "analytical skills", "accountability", "collaboration"))
    ]
    if soft_skill_hits:
        result.critical_gaps.append(f"Soft-skill phrases found in Technical Skills: {', '.join(soft_skill_hits[:5])}")
    else:
        result.passed_checks.append("Technical Skills contains no blocked soft-skill phrases.")

    if rec.achievements or rec.awards:
        result.passed_checks.append("Achievements or awards are present.")
    else:
        result.warnings.append("No achievements or awards are present.")

    penalty = 0.16 * len(result.critical_gaps) + 0.05 * len(result.warnings)
    result.overall_estimated_ats_score = max(0.0, min(1.0, 1.0 - penalty))
    return result


def _critical_keywords(parsed_jd: ParsedJD) -> list[str]:
    values = [
        parsed_jd.job_title,
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.tools_platforms,
        *[keyword.keyword for keyword in parsed_jd.keywords if keyword.importance in {"critical", "high"}],
    ]
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result[:24]


def _normalize(text: str) -> str:
    lowered = text.casefold().translate(str.maketrans({char: " " for char in string.punctuation if char not in "+#"}))
    normalized = " ".join(_TOKEN_RE.findall(lowered))
    # REST and RESTful commonly alternate in resumes/JDs; keep both normalized forms searchable.
    normalized = normalized.replace("restful apis", "rest apis restful apis")
    return f" {normalized} "


def _keyword_present(keyword: str, normalized_resume: str) -> bool:
    normalized_keyword = _normalize(keyword).strip()
    return not normalized_keyword or f" {normalized_keyword} " in normalized_resume


def _starts_with_action_verb(bullet: str) -> bool:
    first = re.sub(r"[^a-zA-Z-]", "", (bullet or "").split(" ", 1)[0]).casefold()
    return first in _ACTION_VERBS


def _resume_text(rec: ResumeRecommendation) -> str:
    parts = [
        rec.target_title,
        rec.summary or "",
        " ".join(skill for group in rec.skills for skill in [group.category, *group.skills]),
        " ".join(bullet.text for exp in rec.experience for bullet in exp.bullets),
        " ".join(bullet.text for project in rec.projects for bullet in project.bullets),
        " ".join(f"{item.title} {item.description or ''}" for item in [*rec.achievements, *rec.awards]),
    ]
    return "\n".join(parts)
