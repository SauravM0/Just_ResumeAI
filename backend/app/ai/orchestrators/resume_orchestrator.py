"""
Resume Orchestrator — manages the multi-step resume generation AI pipeline.

Pipeline steps (each is a separate Gemini call):
  1. Profile Normalizer: standardize profile data for matching
  2. Relevance Matcher: score profile items against parsed JD
  3. Resume Composer: generate tailored bullets and select content

The orchestrator enforces deterministic rules AFTER each AI step.
"""

from __future__ import annotations

import logging
from app.ai.gemini_client import get_gemini_client, GeminiClientError
from app.domain.rules import (
    MAX_EXPERIENCES,
    MAX_PROJECTS,
    MAX_BULLETS_PER_EXPERIENCE,
    MIN_BULLETS_PER_EXPERIENCE,
    MAX_SUMMARY_WORDS,
    ACTION_VERBS,
    MIN_BULLET_LENGTH,
    MAX_BULLET_LENGTH,
)
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.resume import (
    ResumeRecommendation,
    ResumeContactInfo,
    ResumeExperienceEntry,
    ResumeProjectEntry,
    ResumeEducationEntry,
    ResumeSkillGroup,
    ResumeCertEntry,
    ResumeBullet,
    BulletStatus,
)

logger = logging.getLogger(__name__)


# ─── Pydantic models for intermediate AI outputs ────────────────────────────

from pydantic import BaseModel, Field
from typing import Optional


class _RelevanceItem(BaseModel):
    """AI output: relevance score for a single profile item."""
    source_id: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    matched_keywords: list[str] = Field(default_factory=list)
    reasoning: str = ""


class _RelevanceResult(BaseModel):
    """AI output: relevance scores for all profile items."""
    experience_scores: list[_RelevanceItem] = Field(default_factory=list)
    project_scores: list[_RelevanceItem] = Field(default_factory=list)
    education_relevant: bool = True
    profile_strength: str = Field(default="moderate", description="'strong', 'moderate', 'weak'")
    profile_warnings: list[str] = Field(default_factory=list)


class _ComposedBullet(BaseModel):
    """AI output: a single generated bullet."""
    text: str
    matched_keywords: list[str] = Field(default_factory=list)


class _ComposedExperience(BaseModel):
    """AI output: composed experience entry."""
    source_id: str
    tailored_title: Optional[str] = None
    bullets: list[_ComposedBullet] = Field(default_factory=list)


class _ComposedProject(BaseModel):
    """AI output: composed project entry."""
    source_id: str
    bullets: list[_ComposedBullet] = Field(default_factory=list)


class _ComposedResume(BaseModel):
    """AI output: the full composed resume content."""
    target_title: str
    summary: Optional[str] = None
    experiences: list[_ComposedExperience] = Field(default_factory=list)
    projects: list[_ComposedProject] = Field(default_factory=list)
    skill_groups: list[ResumeSkillGroup] = Field(default_factory=list)


RELEVANCE_SYSTEM_PROMPT = """You are a resume relevance scoring engine.
Given a master profile and a parsed job description, score how relevant each
work experience and project is to this specific job.

RULES:
1. Score each item from 0.0 (irrelevant) to 1.0 (perfect match).
2. List which JD keywords each item matches.
3. Provide brief reasoning for each score.
4. Assess overall profile strength ('strong', 'moderate', 'weak').
5. If weak, provide specific warnings about gaps.
6. Return ONLY valid JSON matching the schema."""

COMPOSER_SYSTEM_PROMPT = """You are an expert resume writer creating highly JD-aligned ATS-optimized resume content.

RULES:
1. Every bullet MUST start with a strong action verb from the allowed list.
2. Include quantifiable metrics where possible (%, $, time saved, scale).
3. Naturally weave in relevant JD keywords without keyword stuffing or repetition.
4. Each bullet must be {min_len}-{max_len} characters.
5. Generate {min_bullets}-{max_bullets} bullets per experience. If you cannot generate at least 2 meaningful bullets for an entry, omit that entry entirely.
6. The professional summary must be under {max_summary} words and MUST include:
   - The target JD title (or a very close variation)
   - 5-8 priority JD keywords woven in naturally
7. Write for a {seniority} level position.
8. Use the ATS keyword planner as the main guide for all content.
9. Technical Skills section must include all JD-required skills grouped cleanly by category.
10. Experience bullets must be rewritten to reflect JD responsibilities, not just copy original profile bullets.
11. Projects must be selected and rewritten to match JD relevance.
12. AVOID:
    - Awkward copy-paste wording from the JD
    - Grammar errors like "Results-driven Application" (never start with "Results-driven" as an adjective before a noun)
    - Repeating the same keyword multiple times unnaturally
    - Copying labels like "Designation:" into the resume
    - Any content that could be flagged as fake or invented (companies, dates, employers, certifications)
13. Keep output ATS-friendly: simple section names, clean bullets, no graphics-dependent content.
14. If the JD mentions specialized platforms (e.g., OBDX), create relevant skill groupings or sections for them.
15. If exact experience is not available, still optimize wording around related development, deployment, troubleshooting, microservices, UI, DevOps, and mobile skills.
16. Return ONLY valid JSON matching the schema."""


async def generate_recommendation(
    profile: MasterProfile,
    parsed_jd: ParsedJD,
    session_id: str,
    emphasis: str | None = None,
    rejected_ids: list[str] | None = None,
    locked_bullets: dict[str, str] | None = None,
    target_pages: int = 1,
    additional_alignment_text: str | None = None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> ResumeRecommendation:
    """
    Run the full resume generation pipeline:
    1. Score relevance of profile items to JD
    2. Compose tailored resume content
    3. Enforce deterministic rules
    4. Return recommendation for human review

    Args:
        profile: User's master profile.
        parsed_jd: Structured JD from the analyzer.
        session_id: Session identifier for this flow.
        emphasis: Optional user emphasis (e.g. "leadership", "backend").
        rejected_ids: IDs to exclude from recommendations.
        locked_bullets: Bullet ID → text pairs to preserve exactly.

    Returns:
        ResumeRecommendation ready for human review.
    """
    rejected_ids = rejected_ids or []
    locked_bullets = locked_bullets or {}
    strategy = None
    budget = None
    client = get_gemini_client()

    # ── Step 1: Relevance Matching ───────────────────────────────────────
    logger.info(f"[{session_id}] Step 1: Relevance matching")

    # Filter out rejected items before sending to AI
    filtered_experience = [e for e in profile.work_experience if e.id not in rejected_ids]
    filtered_projects = [p for p in profile.projects if p.id not in rejected_ids]

    relevance_prompt = _build_relevance_prompt(
        filtered_experience, 
        filtered_projects, 
        profile.skills,   # Pass skills here
        parsed_jd, 
        emphasis,
        ats_plan,
    )
    relevance = await client.generate_structured(
        prompt=relevance_prompt,
        response_model=_RelevanceResult,
        system_instruction=RELEVANCE_SYSTEM_PROMPT,
    )

    # ── Step 2: Resume Composition ───────────────────────────────────────
    logger.info(f"[{session_id}] Step 2: Resume composition")

    # Select top items by relevance score
    top_exp_ids = _select_top_items(relevance.experience_scores, MAX_EXPERIENCES)
    top_proj_ids = _select_top_items(relevance.project_scores, MAX_PROJECTS)

    selected_experience = [e for e in filtered_experience if e.id in top_exp_ids]
    selected_projects = [p for p in filtered_projects if p.id in top_proj_ids]

    composer_system = COMPOSER_SYSTEM_PROMPT.format(
        min_len=MIN_BULLET_LENGTH,
        max_len=MAX_BULLET_LENGTH,
        min_bullets=MIN_BULLETS_PER_EXPERIENCE,
        max_bullets=MAX_BULLETS_PER_EXPERIENCE,
        max_summary=MAX_SUMMARY_WORDS,
        seniority=parsed_jd.seniority.value,
    )

    composer_prompt = _build_composer_prompt(
        profile,
        selected_experience,
        selected_projects,
        parsed_jd,
        emphasis,
        strategy,
        budget,
        additional_alignment_text,
        ats_plan,
    )

    composed = await client.generate_structured(
        prompt=composer_prompt,
        response_model=_ComposedResume,
        system_instruction=composer_system,
    )
    _clean_composed_resume(
        composed,
        parsed_jd,
        strategy,
        budget,
        profile,
        selected_experience,
        selected_projects,
        ats_plan,
    )

    # ── Step 3: Assemble and enforce rules ───────────────────────────────
    logger.info(f"[{session_id}] Step 3: Assembling recommendation")

    recommendation = _assemble_recommendation(
        session_id=session_id,
        profile=profile,
        parsed_jd=parsed_jd,
        relevance=relevance,
        composed=composed,
        selected_experience=selected_experience,
        selected_projects=selected_projects,
        locked_bullets=locked_bullets,
        emphasis=emphasis,
    )

    return recommendation


# ─── Private helpers ─────────────────────────────────────────────────────────

def _build_relevance_prompt(
    experiences: list,
    projects: list,
    profile_skills: list,  # Added this arg
    parsed_jd: ParsedJD,
    emphasis: str | None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> str:
    """Build the prompt for the relevance matching step."""
    exp_text = "\n".join(
        f"- ID: {e.id} | {e.title} at {e.company} | Bullets: {'; '.join(e.bullets[:3])}"
        for e in experiences
    )
    proj_text = "\n".join(
        f"- ID: {p.id} | {p.name} | Tech: {', '.join(p.technologies[:5])}"
        for p in projects
    )
    # Added skills to relevance matching
    skills_text = ", ".join(s.name for s in profile_skills[:30])
    keywords = ", ".join(k.keyword for k in parsed_jd.keywords[:30])
    planner_keywords = ", ".join((ats_plan.priority_keywords if ats_plan else [])[:30])

    prompt = f"""Score the relevance of these profile items to the job description.

JOB: {parsed_jd.job_title} at {parsed_jd.company or 'Unknown Company'}
SENIORITY: {parsed_jd.seniority.value}
KEY REQUIREMENTS: {', '.join(parsed_jd.required_skills[:15])}
JD KEYWORDS: {keywords}
ATS PLANNER PRIORITY TERMS: {planner_keywords or '(none)'}

CANDIDATE SKILLS: {skills_text}

EXPERIENCES:
{exp_text or '(none)'}

PROJECTS:
{proj_text or '(none)'}"""

    if emphasis:
        prompt += f"\n\nUSER EMPHASIS: Prioritize items related to '{emphasis}'."

    return prompt


def _build_composer_prompt(
    profile: MasterProfile,
    experiences: list,
    projects: list,
    parsed_jd: ParsedJD,
    emphasis: str | None,
    strategy,
    budget,
    additional_alignment_text: str | None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> str:
    """Build the prompt for the resume composition step."""
    exp_detail = "\n\n".join(
        f"ID: {e.id}\nTitle: {e.title}\nCompany: {e.company}\n"
        f"Dates: {e.start_date} - {e.end_date or 'Present'}\n"
        f"Original bullets:\n" + "\n".join(f"  • {b}" for b in e.bullets)
        for e in experiences
    )
    proj_detail = "\n\n".join(
        f"ID: {p.id}\nName: {p.name}\nTech: {', '.join(p.technologies)}\n"
        f"Original bullets:\n" + "\n".join(f"  • {b}" for b in p.bullets)
        for p in projects
    )
    skills = ", ".join(s.name for s in profile.skills[:30])
    keywords = ", ".join(k.keyword for k in parsed_jd.keywords[:20])
    planner_keywords = ", ".join((ats_plan.priority_keywords if ats_plan else [])[:35])
    planner_skills = ", ".join((ats_plan.must_include_skills if ats_plan else [])[:25])
    planner_tools = ", ".join((ats_plan.must_include_tools_platforms if ats_plan else [])[:20])
    planner_responsibilities = ", ".join((ats_plan.must_include_responsibilities if ats_plan else [])[:20])
    planner_themes = " ".join((ats_plan.suggested_summary_themes if ats_plan else [])[:5])
    style_guidance = " ".join((ats_plan.resume_style_guidance if ats_plan else [])[:5])
    priority_requirements = [
        *parsed_jd.required_skills,
        *[req.text for req in parsed_jd.requirements],
        *parsed_jd.responsibilities,
    ][:30]

    is_obdx_jd = "obdx" in (parsed_jd.job_title or "").lower() or any(
        "obdx" in (kw.keyword or "").lower() for kw in parsed_jd.keywords
    )

    obdx_guidance = ""
    if is_obdx_jd:
        obdx_guidance = """
OBDX-SPECIFIC GUIDANCE:
- Target title must include "OBDX Developer" or close variation (e.g., "OBDX Developer", "Oracle OBDX Developer")
- Summary must include: OBDX, PL/SQL, Java, Microservices, DevOps, UI/UX
- Technical Skills MUST include: PL/SQL, Java, Microservices, DevOps, Git, Jenkins, UI/UX
- Experience bullets should emphasize: OBDX installation/deployment, CEMLI development, troubleshooting, Extensibility
- If JD mentions mobile apps, include iOS/Android in skills and potentially create mobile section
- UK Open Banking terms should be included if space allows
- DO NOT copy "Designation:" or other JD labels directly into resume content
"""

    prompt = f"""Create tailored resume content for this job application.

TARGET JOB: {parsed_jd.job_title}
COMPANY: {parsed_jd.company or 'Unknown'}
KEY JD KEYWORDS TO INCLUDE: {keywords}
ATS PLANNER PRIORITY KEYWORDS: {planner_keywords or '(none)'}
MUST-INCLUDE SKILLS: {planner_skills or '(none)'}
MUST-INCLUDE TOOLS/PLATFORMS: {planner_tools or '(none)'}
MUST-INCLUDE RESPONSIBILITY THEMES: {planner_responsibilities or '(none)'}
SUMMARY THEMES: {planner_themes or '(none)'}
STYLE GUIDANCE: {style_guidance or 'Use a clean ATS-friendly format.'}
REQUIRED SKILLS: {', '.join(parsed_jd.required_skills[:15])}

CANDIDATE SKILLS: {skills}

ATS ALIGNMENT SIGNALS:
- Priority JD terms to add or emphasize: {', '.join(priority_requirements) if priority_requirements else '(none)'}
- Resume strategy note: Generate the strongest ATS-aligned resume for this JD.

USER EXTRA CONTEXT:
{additional_alignment_text or '(none provided)'}

EXPERIENCES TO TAILOR:
{exp_detail or '(none provided)'}

PROJECTS TO TAILOR:
{proj_detail or '(none provided)'}

ATS ALIGNMENT:
- Use the ATS keyword planner as the main guide for all content decisions.
- Use the exact JD title when it is the best ATS headline.
- Summary MUST include the target JD title and 5-8 priority keywords naturally.
- Technical Skills must include ALL JD-required skills grouped by category (e.g., "Languages", "Tools", "Platforms").
- Experience bullets MUST be rewritten to reflect JD responsibilities, not just copied from profile.
- Projects must be selected and rewritten to match JD relevance.
- Put the highest-priority ATS planner keywords into the summary and Technical Skills section.
{obdx_guidance}
AVOID:
- Copy-paste directly from JD (rework the meaning, not the words)
- Grammar errors like "Results-driven Application" (never use as adjective before noun)
- Repeating keywords unnaturally
- Copying labels like "Designation:" into resume content
- Creating fake employers, dates, degrees, or certifications
- Altering candidate identity/contact details

Generate:
1. A tailored job title/headline (clean, no labels like "Designation:")
2. A professional summary that includes the target title and 5-8 priority keywords
3. Tailored bullets for each experience (at least 2 bullets per entry, rewrite to highlight JD-relevant achievements)
4. Tailored bullets for each project (at least 2 bullets per entry)
5. Organized skill groups with all JD-required skills"""

    if emphasis:
        prompt += f"\n\nEMPHASIS: Lean towards '{emphasis}' in your phrasing."

    return prompt


def _select_top_items(scores: list[_RelevanceItem], max_count: int) -> set[str]:
    """Select the top N items by relevance score."""
    sorted_items = sorted(scores, key=lambda x: x.relevance_score, reverse=True)
    return {item.source_id for item in sorted_items[:max_count]}


def _clean_composed_resume(
    composed: _ComposedResume,
    parsed_jd: ParsedJD,
    strategy,
    budget,
    profile: MasterProfile,
    selected_experience: list,
    selected_projects: list,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> None:
    composed.target_title = (
        (ats_plan.target_resume_title if ats_plan else None)
        or composed.target_title
        or parsed_jd.job_title
        or ""
    ).strip()
    composed.target_title = _clean_resume_title(composed.target_title)

    if composed.summary:
        composed.summary = _clean_grammar_errors(composed.summary.strip())

    valid_experiences = []
    for exp in composed.experiences:
        valid_bullets = []
        for bullet in exp.bullets:
            cleaned_text = bullet.text.strip()
            cleaned_text = _clean_grammar_errors(cleaned_text)
            if cleaned_text:
                bullet.text = cleaned_text
                valid_bullets.append(bullet)
        if len(valid_bullets) >= 2:
            exp.bullets = valid_bullets
            valid_experiences.append(exp)
    composed.experiences = valid_experiences

    valid_projects = []
    for project in composed.projects:
        valid_bullets = []
        for bullet in project.bullets:
            cleaned_text = bullet.text.strip()
            cleaned_text = _clean_grammar_errors(cleaned_text)
            if cleaned_text:
                bullet.text = cleaned_text
                valid_bullets.append(bullet)
        if len(valid_bullets) >= 2:
            project.bullets = valid_bullets
            valid_projects.append(project)
    composed.projects = valid_projects

    for group in composed.skill_groups:
        group.skills = [skill.strip() for skill in group.skills if skill.strip()]


def _clean_resume_title(title: str) -> str:
    """Clean resume title by removing labels like 'Designation:'."""
    import re
    cleaned = re.sub(r"^\s*(designation|job\s*title|title|role)\s*:\s*", "", title, flags=re.IGNORECASE)
    return cleaned.strip(" :-\t")


def _clean_grammar_errors(text: str) -> str:
    """Fix common grammar errors like 'Results-driven Application'."""
    import re
    text = re.sub(r"\bResults-driven\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", r"\1", text)
    return text


def _assemble_recommendation(
    session_id: str,
    profile: MasterProfile,
    parsed_jd: ParsedJD,
    relevance: _RelevanceResult,
    composed: _ComposedResume,
    selected_experience: list,
    selected_projects: list,
    locked_bullets: dict[str, str],
    emphasis: str | None,
) -> ResumeRecommendation:
    """
    Assemble the final recommendation from AI outputs,
    enforcing deterministic rules.
    """
    rel_scores = {item.source_id: item for item in relevance.experience_scores}
    proj_rel_scores = {item.source_id: item for item in relevance.project_scores}

    composed_exp = {ce.source_id: ce for ce in composed.experiences}
    composed_proj = {cp.source_id: cp for cp in composed.projects}

    experience_entries = []
    for exp in selected_experience:
        ce = composed_exp.get(exp.id)
        rel = rel_scores.get(exp.id)
        bullets = _build_bullets(
            "experience",
            ce.bullets if ce else [],
            exp.id,
            locked_bullets,
        )
        if not bullets:
            continue
        entry = ResumeExperienceEntry(
            source_id=exp.id,
            company=exp.company,
            title=ce.tailored_title or exp.title if ce else exp.title,
            location=exp.location,
            start_date=exp.start_date,
            end_date=exp.end_date,
            is_current=exp.is_current,
            bullets=bullets,
            relevance_score=rel.relevance_score if rel else 0.0,
        )
        experience_entries.append(entry)

    project_entries = []
    for proj in selected_projects:
        cp = composed_proj.get(proj.id)
        rel = proj_rel_scores.get(proj.id)
        bullets = _build_bullets(
            "project",
            cp.bullets if cp else [],
            proj.id,
            locked_bullets,
        )
        if not bullets:
            continue
        entry = ResumeProjectEntry(
            source_id=proj.id,
            name=proj.name,
            description=proj.description,
            technologies=proj.technologies,
            bullets=bullets,
            relevance_score=rel.relevance_score if rel else 0.0,
        )
        project_entries.append(entry)

    # ── Education entries ────────────────────────────────────────────────
    education_entries = [
        ResumeEducationEntry(
            source_id=edu.id,
            institution=edu.institution,
            degree=edu.degree,
            field_of_study=edu.field_of_study,
            start_date=edu.start_date,
            end_date=edu.end_date,
            gpa=edu.gpa,
            honors=edu.honors,
            relevant_coursework=edu.relevant_coursework,
        )
        for edu in profile.education
    ]

    # ── Skills ───────────────────────────────────────────────────────────
    skill_groups = composed.skill_groups if composed.skill_groups else _default_skill_groups(profile)

    # ── Certifications ───────────────────────────────────────────────────
    cert_entries = [
        ResumeCertEntry(
            source_id=c.id,
            name=c.name,
            issuing_org=c.issuing_org,
            date=c.issue_date,
        )
        for c in profile.certifications
    ]

    # ── Warnings ─────────────────────────────────────────────────────────
    warnings = list(relevance.profile_warnings)
    if relevance.profile_strength == "weak":
        warnings.insert(0, "⚠️ Your profile is a weak match for this role. Consider adding more relevant experience.")
    if not experience_entries:
        warnings.append("⚠️ No work experience matched this job description.")

    # ── Contact Info ─────────────────────────────────────────────────────
    contact = ResumeContactInfo(
        full_name=profile.contact.full_name,
        email=profile.contact.email,
        phone=profile.contact.phone,
        location=profile.contact.location,
        linkedin_url=profile.contact.linkedin_url,
        github_url=profile.contact.github_url,
        portfolio_url=profile.contact.portfolio_url,
    )

    return ResumeRecommendation(
        session_id=session_id,
        target_title=composed.target_title,
        summary=composed.summary,
        contact=contact,
        experience=experience_entries,
        education=education_entries,
        skills=skill_groups,
        projects=project_entries,
        certifications=cert_entries,
        emphasis=emphasis,
        warnings=warnings,
    )


def _build_bullets(
    section_type: str,
    composed_bullets: list[_ComposedBullet],
    source_id: str,
    locked_bullets: dict[str, str],
) -> list[ResumeBullet]:
    """Convert AI-composed bullets to ResumeBullet objects, preserving locked bullets."""
    result = []
    composed_slots = composed_bullets[:MAX_BULLETS_PER_EXPERIENCE]
    locked_slots = _locked_bullet_slots(section_type, source_id, locked_bullets)
    slot_count = max(len(composed_slots), (max(locked_slots) + 1) if locked_slots else 0)

    for index in range(slot_count):
        bullet_id = _stable_bullet_id(section_type, source_id, index)
        cb = composed_slots[index] if index < len(composed_slots) else None

        if bullet_id in locked_bullets:
            result.append(ResumeBullet(
                id=bullet_id,
                text=locked_bullets[bullet_id],
                status=BulletStatus.LOCKED,
                matched_keywords=cb.matched_keywords if cb else [],
                source_id=source_id,
            ))
            continue

        if not cb:
            continue

        # Enforce bullet length rules
        text = cb.text.strip()
        if len(text) < MIN_BULLET_LENGTH:
            continue  # Skip too-short bullets
        if len(text) > MAX_BULLET_LENGTH:
            text = text[:MAX_BULLET_LENGTH - 3] + "..."

        result.append(ResumeBullet(
            id=bullet_id,
            text=text,
            original_text=text,
            status=BulletStatus.PENDING,
            matched_keywords=cb.matched_keywords,
            source_id=source_id,
        ))

    return result


def _stable_bullet_id(section_type: str, source_id: str, index: int) -> str:
    """Build a deterministic bullet ID stable across regeneration for the same slot."""
    return f"{section_type}:{source_id}:{index}"


def _locked_bullet_slots(
    section_type: str,
    source_id: str,
    locked_bullets: dict[str, str],
) -> set[int]:
    """Extract locked bullet indexes for a given source item."""
    prefix = f"{section_type}:{source_id}:"
    slots: set[int] = set()
    for bullet_id in locked_bullets:
        if not bullet_id.startswith(prefix):
            continue
        try:
            slots.add(int(bullet_id.rsplit(":", 1)[1]))
        except ValueError:
            continue
    return slots


def _default_skill_groups(profile: MasterProfile) -> list[ResumeSkillGroup]:
    """Fallback: group skills by their category field."""
    groups: dict[str, list[str]] = {}
    for skill in profile.skills:
        cat = skill.category or "Technical Skills"
        groups.setdefault(cat, []).append(skill.name)
    return [ResumeSkillGroup(category=cat, skills=skills) for cat, skills in groups.items()]
