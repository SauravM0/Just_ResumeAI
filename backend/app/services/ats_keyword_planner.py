from __future__ import annotations

import re

from app.schemas.ats_planner import ATSKeywordPlannerOutput, PlannedRequirement
from app.schemas.jd import ParsedJD, RequirementPlacement, RequirementPriority
from app.schemas.profile import MasterProfile, Project, WorkExperience
from app.schemas.resume import ResumeRecommendation
from app.services.jd_sanitization_service import sanitize_parsed_jd
from app.services.resume_strategy_service import build_resume_strategy
from app.services.skill_taxonomy_service import clean_keyword_terms
from app.services.candidate_timeline_service import choose_honest_target_title
from app.services.candidate_evidence_service import build_candidate_evidence
from app.services.synonym_service import get_all_forms


def build_ats_keyword_plan(
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    emphasis: str | None = None,
    target_pages: int = 1,
    current_draft: ResumeRecommendation | None = None,
) -> ATSKeywordPlannerOutput:
    """
    Create a keyword alignment plan from JD signals and profile content.

    All JD keywords are passed forward to the AI. ``is_supported`` is metadata
    for labeling prompt terms as confirmed or aspirational, not a filter for
    whether the term gets planned.
    """
    parsed_jd = sanitize_parsed_jd(parsed_jd)
    strategy = build_resume_strategy(parsed_jd, profile)
    evidence = build_candidate_evidence(profile, recommendation=current_draft)
    
    title_decision = choose_honest_target_title(
        parsed_jd,
        profile,
        requested_title=_clean_title(parsed_jd.job_title) or _fallback_title(profile),
    )
    
    # ── Requirement Planning ────────────────────────────────────────────
    requirement_plan: list[PlannedRequirement] = []
    must_include_skills: list[str] = []
    must_include_tools: list[str] = []
    must_include_resps: list[str] = []

    for req in parsed_jd.requirements:
        is_supported = evidence.supports(req.text) or any(evidence.supports(s) for s in req.synonyms)
        
        # Default placements based on category if LLM didn't provide them
        placements = req.suggested_placement
        if not placements:
            if req.category == "technical_skill":
                placements = [RequirementPlacement.SKILLS, RequirementPlacement.EXPERIENCE]
            elif req.category == "soft_skill":
                placements = [RequirementPlacement.SUMMARY, RequirementPlacement.EXPERIENCE]
            elif req.category == "experience":
                placements = [RequirementPlacement.EXPERIENCE]
            elif req.category == "education":
                placements = [RequirementPlacement.EDUCATION]
            else:
                placements = [RequirementPlacement.EXPERIENCE]

        planned = PlannedRequirement(
            text=req.text,
            priority=req.priority,
            placement=placements,
            is_supported=is_supported,
            synonyms=req.synonyms,
        )
        requirement_plan.append(planned)

        # Populate legacy fields for backward compatibility. Support status is
        # metadata only; unsupported/adjacent terms are labeled later.
        if req.category == "technical_skill":
            must_include_skills.append(req.text)
        elif req.category == "tooling":
            must_include_tools.append(req.text)
        elif req.category == "responsibility":
            must_include_resps.append(req.text)

    # ── Legacy Keyword Fallbacks ────────────────────────────────────────
    priority_keywords = _priority_keywords(parsed_jd, emphasis, title_decision.title)
    
    must_include_skills = clean_keyword_terms(list(parsed_jd.required_skills))[:35]
    must_include_tools = clean_keyword_terms(list(parsed_jd.tools_platforms))[:30]
    must_include_resps = _dedupe(list(parsed_jd.responsibilities[:10]))

    missing = _missing_from_draft(priority_keywords, current_draft) if current_draft else []

    return ATSKeywordPlannerOutput(
        target_resume_title=title_decision.title,
        candidate_seniority=title_decision.timeline.candidate_seniority.value,
        seniority_adjusted=title_decision.adjusted,
        seniority_warnings=title_decision.warnings,
        priority_keywords=priority_keywords,
        must_include_skills=_dedupe(must_include_skills),
        must_include_tools_platforms=_dedupe(must_include_tools),
        must_include_responsibilities=_dedupe(must_include_resps),
        requirement_plan=requirement_plan,
        suggested_section_ordering=strategy.section_order or _section_order(profile, target_pages),
        suggested_summary_themes=_summary_themes(parsed_jd, priority_keywords, title_decision.title, requirement_plan),
        suggested_project_emphasis=_project_emphasis(profile.projects, priority_keywords, must_include_resps),
        missing_jd_keywords_from_current_draft=missing,
        resume_style_guidance=_style_guidance(target_pages),
    )


def _priority_keywords(parsed_jd: ParsedJD, emphasis: str | None, target_title: str) -> list[str]:
    skill_terms = clean_keyword_terms(
        [
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
    )
    values: list[str] = [
        target_title,
        *skill_terms,
        *parsed_jd.responsibilities,
        *[req.text for req in parsed_jd.requirements if req.priority == RequirementPriority.MUST_HAVE],
        *[keyword.keyword for keyword in parsed_jd.keywords if keyword.importance in {"critical", "high"}],
        *parsed_jd.important_exact_phrases,
    ]
    if emphasis:
        values.append(emphasis)
    return _dedupe(value for value in values if value)[:60]


def _summary_themes(parsed_jd: ParsedJD, priority_keywords: list[str], target_title: str, plan: list[PlannedRequirement]) -> list[str]:
    themes = [
        f"Lead with the target title {target_title}.",
        "Mention the highest-priority supported JD skills early in the summary.",
    ]
    
    supported_must_haves = [r.text for r in plan if r.priority == RequirementPriority.MUST_HAVE and r.is_supported]
    if supported_must_haves:
        themes.append(f"Highlight expertise in {', '.join(supported_must_haves[:3])} to demonstrate core alignment.")

    if target_title != parsed_jd.job_title:
        themes.append("Use the credibility-adjusted target title without restoring unsupported seniority.")
    if parsed_jd.domain_platform_terms:
        themes.append(f"Use domain terms such as {', '.join(parsed_jd.domain_platform_terms[:4])}.")
    if parsed_jd.cloud_devops_tools:
        themes.append(f"Include DevOps/tooling terms such as {', '.join(parsed_jd.cloud_devops_tools[:4])}.")
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
    return any(_contains_keyword_exact(form, normalized_corpus) for form in get_all_forms(keyword))


def _contains_keyword_exact(keyword: str, normalized_corpus: str) -> bool:
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
