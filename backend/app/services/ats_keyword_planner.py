from __future__ import annotations

import re

from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile, Project, WorkExperience
from app.schemas.resume import ResumeRecommendation
from app.services.resume_strategy_service import build_resume_strategy


def build_ats_keyword_plan(
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    emphasis: str | None = None,
    target_pages: int = 1,
    current_draft: ResumeRecommendation | None = None,
) -> ATSKeywordPlannerOutput:
    """Create an ATS optimization plan from JD signals and profile content."""
    strategy = build_resume_strategy(parsed_jd, profile)
    priority_keywords = _priority_keywords(parsed_jd, emphasis)
    must_include_skills = _dedupe(
        [
            *parsed_jd.required_skills,
            *parsed_jd.programming_languages,
            *parsed_jd.frameworks,
            *parsed_jd.databases,
            *parsed_jd.cloud_devops_tools,
            *parsed_jd.domain_platform_terms,
            *parsed_jd.mobile_platform_terms,
            *parsed_jd.preferred_skills,
        ]
    )[:35]
    must_include_tools = _dedupe(
        [
            *parsed_jd.tools_platforms,
            *parsed_jd.cloud_devops_tools,
            *parsed_jd.databases,
            *parsed_jd.deployment_environment_terms,
            *parsed_jd.domain_platform_terms,
        ]
    )[:30]
    must_include_responsibilities = _dedupe(
        [*parsed_jd.responsibilities, *[req.text for req in parsed_jd.requirements]]
    )[:25]
    missing = _missing_from_draft(priority_keywords, current_draft) if current_draft else []

    return ATSKeywordPlannerOutput(
        target_resume_title=_clean_title(parsed_jd.job_title) or _fallback_title(profile),
        priority_keywords=priority_keywords,
        must_include_skills=must_include_skills,
        must_include_tools_platforms=must_include_tools,
        must_include_responsibilities=must_include_responsibilities,
        suggested_section_ordering=strategy.section_order or _section_order(profile, target_pages),
        suggested_summary_themes=_summary_themes(parsed_jd, priority_keywords),
        suggested_project_emphasis=_project_emphasis(profile.projects, priority_keywords, must_include_responsibilities),
        missing_jd_keywords_from_current_draft=missing,
        resume_style_guidance=_style_guidance(target_pages),
    )


def _priority_keywords(parsed_jd: ParsedJD, emphasis: str | None) -> list[str]:
    values: list[str] = [
        parsed_jd.job_title,
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.tools_platforms,
        *parsed_jd.domain_platform_terms,
        *parsed_jd.deployment_environment_terms,
        *parsed_jd.mobile_platform_terms,
        *parsed_jd.responsibilities,
        *[req.text for req in parsed_jd.requirements if req.is_required],
        *[keyword.keyword for keyword in parsed_jd.keywords if keyword.importance in {"critical", "high"}],
        *parsed_jd.preferred_skills,
        *parsed_jd.important_exact_phrases,
    ]
    if emphasis:
        values.append(emphasis)
    return _dedupe(value for value in values if value)[:60]


def _summary_themes(parsed_jd: ParsedJD, priority_keywords: list[str]) -> list[str]:
    themes = [
        f"Lead with the target title {parsed_jd.job_title}.",
        "Mention the highest-priority JD skills early in the summary.",
    ]
    if parsed_jd.domain_platform_terms:
        themes.append(f"Use domain terms such as {', '.join(parsed_jd.domain_platform_terms[:4])}.")
    if parsed_jd.cloud_devops_tools:
        themes.append(f"Include DevOps/tooling terms such as {', '.join(parsed_jd.cloud_devops_tools[:4])}.")
    if parsed_jd.mobile_platform_terms:
        themes.append(f"Include mobile/platform terms such as {', '.join(parsed_jd.mobile_platform_terms[:4])}.")
    if priority_keywords:
        themes.append(f"Prioritize exact phrases: {', '.join(priority_keywords[:8])}.")
    return themes[:8]


def _project_emphasis(
    projects: list[Project],
    priority_keywords: list[str],
    responsibilities: list[str],
) -> list[str]:
    suggestions = [
        "Order projects by JD keyword overlap and place the strongest technical project first.",
        "Rewrite project bullets around JD responsibilities and exact ATS terms.",
    ]
    if projects:
        ranked = sorted(projects, key=lambda project: -_overlap_score(_project_text(project), priority_keywords))
        suggestions.append(f"Favor project '{ranked[0].name}' if it can carry the JD keyword theme.")
    if responsibilities:
        suggestions.append(f"Turn responsibilities into bullet themes: {', '.join(responsibilities[:5])}.")
    return suggestions[:6]


def _section_order(profile: MasterProfile, target_pages: int) -> list[str]:
    order = ["contact", "summary", "technical_skills", "experience"]
    if profile.projects:
        order.append("projects")
    if profile.education:
        order.append("education")
    if target_pages > 1 and profile.certifications:
        order.append("certifications")
    return order


def _style_guidance(target_pages: int) -> list[str]:
    page_note = "one-page" if target_pages <= 1 else "one-to-two-page"
    return [
        f"Create a dense, ATS-friendly {page_note} resume with simple section labels.",
        "Use exact JD wording in the headline, summary, technical skills, and strongest bullets.",
        "Keep bullets accomplishment-oriented while weaving in priority JD responsibilities.",
        "Group technical skills so required JD skills appear before lower-priority profile skills.",
    ]


def _missing_from_draft(priority_keywords: list[str], draft: ResumeRecommendation) -> list[str]:
    corpus = _normalize(
        " ".join(
            [
                draft.target_title or "",
                draft.summary or "",
                " ".join(skill for group in draft.skills for skill in group.skills),
                " ".join(exp.title for exp in draft.experience),
                " ".join(bullet.text for exp in draft.experience for bullet in exp.bullets),
                " ".join(project.name for project in draft.projects),
                " ".join(technology for project in draft.projects for technology in project.technologies),
                " ".join(bullet.text for project in draft.projects for bullet in project.bullets),
            ]
        )
    )
    return [keyword for keyword in priority_keywords if not _contains_keyword(keyword, corpus)][:20]


def _contains_keyword(keyword: str, normalized_corpus: str) -> bool:
    normalized = _normalize(keyword)
    if not normalized:
        return False
    if " " in normalized or "/" in normalized:
        return normalized in normalized_corpus
    return re.search(rf"\b{re.escape(normalized)}\b", normalized_corpus) is not None


def _overlap_score(text: str, keywords: list[str]) -> int:
    normalized = _normalize(text)
    return sum(1 for keyword in keywords if _contains_keyword(keyword, normalized))


def _project_text(project: Project) -> str:
    return " ".join([project.name, project.description or "", " ".join(project.technologies), " ".join(project.bullets)])


def _fallback_title(profile: MasterProfile) -> str:
    if profile.work_experience:
        return profile.work_experience[0].title
    if profile.projects:
        return f"{profile.projects[0].name} Contributor"
    return "Resume Candidate"


def _clean_title(title: str | None) -> str:
    cleaned = (title or "").strip()
    cleaned = re.sub(r"^\s*(designation|job title|title|role)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" :-\t")


def _normalize(text: str | None) -> str:
    lowered = (text or "").lower()
    lowered = re.sub(r"[^\w\s.+#/-]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped
