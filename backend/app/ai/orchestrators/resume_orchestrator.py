"""
Resume Orchestrator — manages the multi-step resume generation AI pipeline.

Pipeline steps (each is a separate Gemini call):
  1. Profile Normalizer: standardize profile data for matching
  2. Relevance Matcher: score profile items against parsed JD
  3. Resume Composer: generate tailored bullets and select content

The orchestrator enforces deterministic rules AFTER each AI step.
"""

from __future__ import annotations

import asyncio
import logging
import re
from app.config import get_settings
from app.ai.gemini_client import get_gemini_client, GeminiClientError
from app.domain.rules import (
    MAX_EXPERIENCES,
    MAX_PROJECTS,
    MAX_BULLETS_PER_EXPERIENCE,
    MIN_BULLETS_PER_EXPERIENCE,
    MIN_BULLET_LENGTH,
    MAX_BULLET_LENGTH,
    MAX_SUMMARY_WORDS,
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
    ResumeAchievementEntry,
    ResumeCustomSection,
    ResumeBullet,
    BulletStatus,
)
from app.services.resume_strength_service import strengthen_resume_recommendation
from app.services.resume_budget_service import fit_resume_to_page_budget
from app.services.resume_quality_gate import apply_resume_quality_gate, build_skill_taxonomy
from app.services.locked_fields_service import build_locked_fields, validate_locked_fields_in_output
from app.services.resume_strategy_service import ResumeStrategy, build_resume_strategy
from app.services.keyword_placement_service import build_master_keyword_list
from app.services.skill_taxonomy_service import sanitize_resume_skill_groups
from app.services.candidate_evidence_service import (
    EvidenceGraph,
    build_candidate_evidence,
    classify_jd_keyword_truth,
    contains_term,
)
from app.services.jd_sanitization_service import sanitize_parsed_jd
from app.services.candidate_timeline_service import (
    CandidateTimelineAssessment,
    assess_candidate_timeline,
    is_fresher_or_student,
)
from app.services.rag_retrieval_service import RequirementEvidence
from app.services.bullet_quality_service import (
    has_jd_boilerplate,
    is_dangling_ending,
    repair_incomplete_bullet,
    validate_single_bullet,
)
from app.ai.resume_fallback import build_evidence_fallback_bullets

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
    description: Optional[str] = None
    bullets: list[_ComposedBullet] = Field(default_factory=list)


class _ComposedResume(BaseModel):
    """AI output: the full composed resume content."""
    target_title: str
    summary: Optional[str] = None
    experiences: list[_ComposedExperience] = Field(default_factory=list)
    projects: list[_ComposedProject] = Field(default_factory=list)
    skill_groups: list[ResumeSkillGroup] = Field(default_factory=list)


RELEVANCE_SYSTEM_PROMPT = """You are a resume relevance scoring engine.
Given a candidate's master profile and a parsed job description, score how
relevant each work experience and project is to this specific role.

RULES:
1. Score each item from 0.0 (irrelevant) to 1.0 (perfect match).
2. Base scores on overlap between JD keywords, responsibilities, required
   skills, and the candidate's actual experience/project content.
3. List which JD keywords each item matches.
4. Provide brief, specific reasoning for each score.
5. If the profile has NO experiences or NO projects, return empty lists.
6. Do not generate resume bullet prose or use banned resume phrases such as
   "responsible for", "worked on", "helped with", or "results-driven".
7. Return ONLY valid JSON matching the schema."""

# v4.0 - master-profile tailoring workflow, STAR-enforced, keyword strategy
COMPOSER_SYSTEM_PROMPT = """
You are an elite AI Resume Tailoring System using an internal multi-agent
workflow. Transform the candidate's master profile evidence into a highly
targeted, ATS-optimized, recruiter-friendly, strictly one-page resume for the
provided job description.

Operate internally as these specialist agents before producing output:
1. JD Analysis Agent: extract must-have skills, good-to-have skills, repeated
   ATS keywords, tools, languages, frameworks, databases, soft skills, domain
   terms, recruiter expectations, seniority, and role category.
2. Company Context Agent: infer company industry, products/services, likely
   candidate preferences, and technology focus from the JD/company name. Use
   this only for positioning; do not invent company-specific experience.
3. ATS Keyword Strategy Agent: map exact JD phrases to real candidate evidence,
   including useful full-form/abbreviation pairs such as Object-Oriented
   Programming/OOP, Data Structures and Algorithms/DSA, Software Development
   Life Cycle/SDLC, Test-Driven Development/TDD, REST APIs, SQL, Git, Agile,
   debugging, and scalable systems when truthful.
4. Truthfulness and Claim Control Agent: market aggressively without fake
   companies, internships, certifications, metrics, tools, seniority, or
   responsibilities.
5. Resume Structure Agent: choose the best ATS section order for the JD. For
   fresher or trainee roles, projects and technical skills may come before
   experience. For experienced roles, experience may come first.
6. Bullet Rewriting Agent: rewrite bullets with action, technology,
   implementation, and outcome or relevance.
7. Project Optimization Agent: rank projects by JD relevance and highlight
   supported backend, frontend, database, API, algorithm, data, or domain
   evidence.
8. Technical Skills Agent: group skills clearly and place the most JD-relevant
   truthful skills first.
9. LaTeX/ATS Engineer Agent: keep content simple, one-page, ATS-readable, and
   safe for later LaTeX rendering.
10. Final Quality Check Agent: silently verify one-page fit, ATS alignment,
    truthfulness, strongest-first ordering, strong bullets, complete JSON, and
    renderer compatibility.

SECTION 1 - ABSOLUTE RULES
1. NO HALLUCINATION: Only use facts from EVIDENCE POINTS. If evidence is thin,
   write less, not more.
2. NO FAKE TECH: Never claim tools or languages absent from evidence or skills.
3. VERIFIED SENIORITY: Do not use "Lead", "Manager", "Architect", "Director",
   or "Principal" unless evidence confirms that level.
4. LOCKED NAMES: Never change company or institution names. Use exact strings
   from evidence.

SECTION 2 - BULLET WRITING RULES
Every bullet must pass all three checks:

CHECK 1 - STRONG ACTION VERB: First word must be strong.
Allowed: Built, Developed, Engineered, Designed, Implemented, Optimized,
Deployed, Automated, Delivered, Reduced, Increased, Launched, Scaled, Migrated,
Integrated, Resolved, Established, Refactored, Streamlined, Generated, Led,
Created, Achieved, Secured, Transformed, Accelerated, Enabled.
Never open with: Worked, Helped, Assisted, Participated, Supported, Was, Did,
Got, Made.

CHECK 2 - CONTEXT: Name the technology, tool, framework, product area, or
domain. Wrong: "Built an API that improved performance." Right: "Built a
FastAPI REST service that reduced latency by 40%."

CHECK 3 - OUTCOME: End with a result, impact, or outcome. If no metric exists,
use a qualitative outcome such as enabling, reducing, supporting, improving, or
allowing. Wrong: "Implemented authentication using JWT." Right: "Implemented
JWT authentication using FastAPI and Redis, securing access for 10,000+ users."

MAXIMUM KEYWORD DENSITY PER BULLET: Use at most 2 technology keywords per
bullet. Do not stuff six tools into one sentence.

SECTION 3 - BANNED PHRASES
Never write these in bullets: "responsible for", "worked on", "helped with",
"assisted in", "was involved in", "participated in", "supported the team",
"contributed to".
Never write these in summaries: "results-driven", "dynamic professional",
"team player", "hard worker", "passionate about", "go-getter", "synergy",
"fast learner", "detail-oriented", "motivated self-starter". Rewrite with
specific action plus outcome.

SECTION 4 - BEFORE/AFTER EXAMPLES
Experienced weak: "Responsible for backend development using Python."
Experienced strong: "Engineered a Python/Django REST API handling 50K daily
requests, reducing p95 latency from 800ms to 120ms."

Fresher weak: "Worked on a web application project using React."
Fresher strong: "Built a full-stack inventory system using React 18 and FastAPI,
handling 500+ product SKUs with real-time WebSocket updates."

Sparse evidence: If only a GitHub link or thin description exists, describe the
observable artifact, tech stack, documentation, deployment, tests, or limits.

SECTION 5 - FRESHER AND STUDENT RULES
For freshers or students, projects and academic work are professional evidence.
Every project bullet must answer: what was built, which tech was used, and what
outcome it enabled. Academic context, hackathon wins, deployed URLs, GitHub
stars, coursework scope, and feature count are valid when supplied. Do not
apologise for lack of experience.

SECTION 6 - SUMMARY RULES
Write 2-3 sentences: who the candidate is, the strongest confirmed technical
fit, and the value they bring to the target role. Do not write a keyword list,
comma-separated skill dump, banned phrase, or unsupported seniority claim.

SECTION 7 - SKILLS RULES
Confirmed skills from evidence go in normal skill groups. Aspirational JD terms
without profile evidence go only in "Learning Focus". Do not mix confirmed and
aspirational skills. Do not list soft skills. Use at most 8 skills per group.

SECTION 8 - STRUCTURE AND PROJECT RULES
Use ATS-friendly section names: Education, Technical Skills, Projects,
Experience, Certifications, Achievements, Leadership, or Coursework. Select
only relevant sections. Remove or compress weak sections if needed for a strict
one-page resume. Put the strongest JD-aligned project first. Make academic
projects sound like practical project experience when the evidence supports it.

SECTION 9 - FINAL OUTPUT CONTRACT
This application renders LaTeX after your structured output. Therefore return
ONLY valid JSON matching the _ComposedResume schema. Do not return LaTeX,
markdown, explanations, ATS scores, comments, or internal workflow notes.
Do not mention the agent workflow in the output fields.

Output MUST be valid JSON matching the _ComposedResume schema.
JD Seniority: {seniority}
Target Page Count: {target_pages}
"""


def _render_composer_system_prompt(
    *,
    seniority: str,
    target_pages: int = 1,
    ats_optimization_mode: str = "realistic",
) -> str:
    """Render configured prompt tokens without interpreting example braces."""
    replacements = {
        "{seniority}": seniority,
        "{target_pages}": str(target_pages),
    }
    rendered = COMPOSER_SYSTEM_PROMPT
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    if ats_optimization_mode == "aggressive":
        rendered += """

SECTION 10 - USER-APPROVED AGGRESSIVE ATS MODE (MANDATORY)
The user has explicitly approved maximizing ATS match for this resume.
This is the HIGHEST PRIORITY instruction — override Sections 1, 4, and 7 evidence
restrictions for keyword coverage.

KEYWORD EMBEDDING MANDATE:
You MUST include EVERY keyword from the CONFIRMED KEYWORDS and PRIORITY TERMS lists
in the output JSON. Zero missing keywords is the target. Place each keyword as follows:

1. SKILLS SECTION: ALL technical keywords (languages, frameworks, databases, tools,
   platforms, methodologies) MUST appear in properly categorized skill groups.
   Do NOT use "Learning Focus" — put all skills directly in main groups.
2. SUMMARY: Include the job title, company name (if given), and top 3-5 JD keywords
   naturally in 2-3 professional sentences.
3. EXPERIENCE BULLETS: Weave remaining JD keywords into action-oriented bullets.
   Each bullet must mention at least 1 JD keyword naturally.
4. PROJECT DESCRIPTIONS: Include JD-relevant technologies in project tech stacks
   and descriptions.
5. MULTI-SECTION COVERAGE: Every high-priority keyword must appear in at least
   2 sections (e.g., skills + a bullet, or skills + summary).

WHAT YOU MAY DO IN AGGRESSIVE MODE:
- Add JD-required skills to skill groups even without profile evidence
- Rewrite experience bullets to incorporate JD keywords and technologies
- Add JD tools/frameworks to project technology lists
- Strengthen summary with JD-aligned domain terms and tools
- Use exact JD phrases and terminology verbatim for ATS match

WHAT YOU MUST NOT DO:
- Invent fake company names, job titles, dates, or institutions
- Fabricate specific metrics (revenue numbers, team sizes) not in profile
- Claim certifications, degrees, or credentials not in profile
- Change the candidate's actual employment history or education

QUALITY RULES (STILL APPLY IN AGGRESSIVE MODE):
- Every bullet must follow: Action Verb + Technology/Context + Scope + Outcome
- No weak openings (responsible for, worked on, helped with)
- Summary must be 2-3 specific sentences, not a keyword dump
- Skills must be in ATS-scannable groups (Languages, Frameworks, Databases, etc.)

PRE-SUBMISSION CHECKLIST (perform silently before returning JSON):
1. Count keywords from CONFIRMED KEYWORDS list — are ALL present in output? If not, add missing ones.
2. Does summary contain the job title and top 3 keywords? If not, rewrite it.
3. Does every experience entry have at least 3 strong bullets? If not, add more.
4. Are all technical skills in properly labeled groups? If not, reorganize.
5. Do project entries mention relevant JD technologies? If not, add them.
"""
    return rendered


async def generate_recommendation(
    profile: MasterProfile,
    parsed_jd: ParsedJD,
    generation_id: str,
    emphasis: str | None = None,
    rejected_ids: list[str] | None = None,
    locked_bullets: dict[str, str] | None = None,
    target_pages: int = 1,
    additional_alignment_text: str | None = None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
    rag_evidence: list[RequirementEvidence] | None = None,
    ats_optimization_mode: str = "realistic",
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
        generation_id: Supabase resume generation identifier for this flow.
        emphasis: Optional user emphasis (e.g. "leadership", "backend").
        rejected_ids: IDs to exclude from recommendations.
        locked_bullets: Bullet ID → text pairs to preserve exactly.

    Returns:
        ResumeRecommendation ready for human review.
    """
    import time as _time
    rejected_ids = rejected_ids or []
    locked_bullets = locked_bullets or {}
    budget = None
    client = get_gemini_client()
    locked = build_locked_fields(profile)
    logger.info(
        "[%s] locked_fields.built companies=%d institutions=%d certs=%d",
        generation_id,
        len(locked.company_names),
        len(locked.institution_names),
        len(locked.cert_names),
    )

    # ── Phase 0: Sanitize parsed JD (serial, fast — everything depends on it) ──
    parsed_jd = sanitize_parsed_jd(parsed_jd)

    # ── Phase 1: Strategy + profile enrichment (independent, parallel) ──────
    t0 = _time.perf_counter()
    strategy, profile = await asyncio.gather(
        asyncio.to_thread(build_resume_strategy, parsed_jd, profile),
        asyncio.to_thread(_enrich_thin_profile, profile, parsed_jd),
    )
    logger.info("[%s] Phase 1 (strategy+enrich) took %.2fs", generation_id, _time.perf_counter() - t0)

    # ── Pre-Step: Filter out rejected items ──────────────────────────────
    filtered_experience = [e for e in profile.work_experience if e.id not in rejected_ids]
    filtered_projects = [p for p in profile.projects if p.id not in rejected_ids]

    # ── Phase 2: Run Step 1 (AI relevance) in parallel with evidence + timeline ──
    logger.info("[%s] Step 1: Relevance matching (parallel w/ evidence+timeline)", generation_id)
    t1 = _time.perf_counter()

    relevance_prompt = _build_relevance_prompt(
        filtered_experience, 
        filtered_projects, 
        profile.skills,
        parsed_jd, 
        emphasis,
        ats_plan,
    )

    relevance_task = client.generate_structured(
        prompt=relevance_prompt,
        response_model=_RelevanceResult,
        system_instruction=RELEVANCE_SYSTEM_PROMPT,
    )
    evidence_task = asyncio.to_thread(build_candidate_evidence, profile)
    timeline_task = asyncio.to_thread(assess_candidate_timeline, profile)

    relevance, evidence_graph, timeline = await asyncio.gather(
        relevance_task, evidence_task, timeline_task,
    )
    logger.info("[%s] Phase 2 (relevance+evidence+timeline) took %.2fs", generation_id, _time.perf_counter() - t1)

    # ── Phase 3: Resume Composition (uses pre-computed evidence + timeline) ──
    logger.info("[%s] Step 2: Resume composition", generation_id)
    t2 = _time.perf_counter()

    top_exp_ids = _select_top_items(relevance.experience_scores, MAX_EXPERIENCES)
    top_proj_ids = _select_top_items(relevance.project_scores, MAX_PROJECTS)

    selected_experience = [e for e in filtered_experience if e.id in top_exp_ids]
    selected_projects = [p for p in filtered_projects if p.id in top_proj_ids]

    composer_system = _render_composer_system_prompt(
        seniority=parsed_jd.seniority.value,
        target_pages=target_pages,
        ats_optimization_mode=ats_optimization_mode,
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
        evidence_graph=evidence_graph,
        timeline=timeline,
        rag_evidence=rag_evidence,
        ats_optimization_mode=ats_optimization_mode,
    )

    composed = await client.generate_structured(
        prompt=composer_prompt,
        response_model=_ComposedResume,
        system_instruction=composer_system,
    )
    logger.info("[%s] Phase 3 (composition) took %.2fs", generation_id, _time.perf_counter() - t2)

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
    _repair_or_fallback_composed_entries(
        composed,
        parsed_jd=parsed_jd,
        profile=profile,
        selected_experience=selected_experience,
        selected_projects=selected_projects,
        ats_plan=ats_plan,
    )

    # ── Phase 4: Assemble and enforce rules ────────────────────────────────
    logger.info("[%s] Step 3: Assembling recommendation", generation_id)
    t3 = _time.perf_counter()

    recommendation = _assemble_recommendation(
        generation_id=generation_id,
        profile=profile,
        parsed_jd=parsed_jd,
        relevance=relevance,
        composed=composed,
        selected_experience=selected_experience,
        selected_projects=selected_projects,
        locked_bullets=locked_bullets,
        emphasis=emphasis,
        ats_plan=ats_plan,
    )
    recommendation.locked_fields = locked.model_dump(mode="json")
    violations = validate_locked_fields_in_output(recommendation, locked, logger=logger)
    if violations:
        logger.warning("[%s] locked_fields.%d_violations_fixed", generation_id, len(violations))

    gated = apply_resume_quality_gate(
        recommendation=recommendation,
        parsed_jd=parsed_jd,
        profile=profile,
        target_pages=target_pages,
        locked=locked,
    )
    strengthened = strengthen_resume_recommendation(
        recommendation=gated,
        parsed_jd=parsed_jd,
        ats_plan=ats_plan,
        target_pages=target_pages,
    )
    fitted = fit_resume_to_page_budget(
        recommendation=strengthened,
        parsed_jd=parsed_jd,
        ats_plan=ats_plan,
        target_pages=target_pages,
    )
    result = apply_resume_quality_gate(fitted, parsed_jd, profile, target_pages, locked=locked)
    result.locked_fields = locked.model_dump(mode="json")
    final_violations = validate_locked_fields_in_output(result, locked, logger=logger)
    if final_violations:
        logger.warning("[%s] locked_fields.%d_final_violations_fixed", generation_id, len(final_violations))
    logger.info("[%s] Phase 4 (assemble+enforce) took %.2fs", generation_id, _time.perf_counter() - t3)
    logger.info("[%s] Total generation took %.2fs", generation_id, _time.perf_counter() - t0)
    return result


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
    skills_text = ", ".join(_sanitize_prompt_text(s.name, 120) for s in profile_skills[:30])
    keywords = ", ".join(_sanitize_prompt_text(k.keyword, 120) for k in parsed_jd.keywords[:30])
    planner_keywords = ", ".join(_sanitize_prompt_text(v, 120) for v in (ats_plan.priority_keywords if ats_plan else [])[:30])

    prompt = f"""Score the relevance of each profile item to this job description.

ROLE: {_sanitize_prompt_text(parsed_jd.job_title, 160)} at {_sanitize_prompt_text(parsed_jd.company or 'Unknown Company', 160)}
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
        prompt += f"\n\nUSER EMPHASIS: Prioritize items related to '{_sanitize_prompt_text(emphasis, 240)}'."

    return _limit_prompt_size(prompt)


def _build_composer_prompt(
    profile: MasterProfile,
    experiences: list,
    projects: list,
    parsed_jd: ParsedJD,
    emphasis: str | None,
    strategy: ResumeStrategy,
    budget,
    additional_alignment_text: str | None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
    evidence_graph: EvidenceGraph | None = None,
    timeline: CandidateTimelineAssessment | None = None,
    rag_evidence: list[RequirementEvidence] | None = None,
    ats_optimization_mode: str = "realistic",
) -> str:
    """Build an evidence-first composer prompt with abstract JD alignment targets.
    
    Accepts optional pre-computed evidence_graph and timeline to avoid recomputation
    when the caller has already computed them (e.g., parallelised pipeline).
    """
    from app.services.resume_strategy_service import ResumeRoleClassification
    
    parsed_jd = sanitize_parsed_jd(parsed_jd)
    if evidence_graph is None:
        evidence_graph = build_candidate_evidence(profile)

    rag_section = _build_rag_evidence_section(rag_evidence or [])
    evidence_mode = "RAG" if rag_section else "FLAT"
    logger.info("composer.evidence_mode=%s", evidence_mode)
    
    # ── Strategy Hint ───────────────────────────────────────────────────
    if strategy.classification == ResumeRoleClassification.FRESHER_INTERN:
        strategy_hint = (
            "FRESHER STRATEGY: This candidate has no/minimal work experience. "
            "Projects and academic work are their primary professional evidence. "
            "Apply Section 5 fresher rules strictly. "
            "Do not apologise for lack of experience; present projects with full professional confidence. "
            "Education should appear BEFORE experience in section order. "
            "Highlight GPA if above 7.5 CGPA or 3.5 GPA."
        )
    elif strategy.classification == ResumeRoleClassification.SENIOR:
        strategy_hint = "Emphasis: Strategic leadership, scalability, mentorship, and business outcomes. Use an executive, authoritative tone."
    else:
        strategy_hint = "Emphasis: Professional reliability, technical competency, and consistent delivery. Use a professional, direct tone."

    exp_detail = ""
    for e in experiences:
        nodes = evidence_graph.filter_by_source(e.id)
        evidence_points = "\n".join([f"  - [{n.type.value}] {n.content}" for n in nodes])
        exp_detail += (
            f"ID: {e.id}\nTitle: {e.title}\nCompany: {e.company}\n"
            f"Dates: {e.start_date} - {e.end_date or 'Present'}\n"
            f"EVIDENCE POINTS:\n{evidence_points or '  (use description: ' + _sanitize_prompt_text(e.description or '', 400) + ')'}\n\n"
        )

    proj_detail = ""
    for p in projects:
        nodes = evidence_graph.filter_by_source(p.id)
        evidence_points = "\n".join([f"  - [{n.type.value}] {n.content}" for n in nodes])
        proj_detail += (
            f"ID: {p.id}\nName: {p.name}\nTech: {', '.join(p.technologies)}\n"
            f"EVIDENCE POINTS:\n{evidence_points or '  (use description: ' + _sanitize_prompt_text(p.description or '', 400) + ')'}\n\n"
        )

    # ── JD RECONSTRUCTION ───────────────────────────────────────────────
    jd_summary = f"Role: {parsed_jd.job_title}\nCompany: {parsed_jd.company or 'Target Company'}\n"
    if parsed_jd.responsibilities:
        jd_summary += "Top Responsibilities:\n" + "\n".join([f"- {r}" for r in parsed_jd.responsibilities[:5]]) + "\n"
    if parsed_jd.requirements:
        jd_summary += "Top Requirements:\n" + "\n".join([f"- {r.text}" for r in parsed_jd.requirements[:5]]) + "\n"

    # ── MASTER KEYWORD LIST — same list the scorer will check ──────────
    # CRITICAL: these are the EXACT strings the ATS scoring function uses.
    # The AI must embed each one VERBATIM (exact JD spelling) somewhere in
    # the resume. Paraphrasing = scorer miss = lower ATS score.
    master_keywords = build_master_keyword_list(parsed_jd, ats_plan)
    # Pass the full top keyword set to the AI, labeled by evidence status.
    # The output cleaner remains the safety net for truly unsupported claims.
    truth = classify_jd_keyword_truth(parsed_jd, evidence_graph, ats_plan, keywords=master_keywords)
    priority_set = set()
    if ats_plan:
        priority_set = set(kw.casefold() for kw in (
            ats_plan.priority_keywords[:12] + ats_plan.must_include_skills
        ))
    supported_set = set(truth.source_supported)
    all_jd_keywords = master_keywords[:60]
    aggressive_mode = ats_optimization_mode == "aggressive"
    confirmed_kw = all_jd_keywords if aggressive_mode else [kw for kw in all_jd_keywords if kw in supported_set]
    aspirational_kw = [] if aggressive_mode else [kw for kw in all_jd_keywords if kw not in supported_set][:20]
    if aggressive_mode:
        kw_section = (
            "USER-APPROVED ATS KEYWORDS - use verbatim across summary, skills, projects, and bullets:\n"
            f"{', '.join(confirmed_kw[:60]) or '(none)'}"
        )
    else:
        kw_section = (
            "CONFIRMED KEYWORDS - use verbatim in bullets and summary (your profile has evidence):\n"
            f"{', '.join(confirmed_kw[:40]) or '(none)'}\n\n"
            "ASPIRATIONAL KEYWORDS - include in Learning Focus skills ONLY (JD requires, profile lacks):\n"
            f"{', '.join(aspirational_kw[:20]) or '(none)'}"
        )
    top_keywords = [
        kw for kw in confirmed_kw
        if kw.casefold() in priority_set
    ][:15]

    requirement_themes = _abstract_requirement_themes(parsed_jd, ats_plan)

    skills_str = ", ".join(_sanitize_prompt_text(s.name, 80) for s in profile.skills[:20])
    style_guidance = " ".join(_sanitize_prompt_text(v, 200) for v in (ats_plan.resume_style_guidance if ats_plan else [])[:3])
    summary_themes = " ".join(_sanitize_prompt_text(v, 200) for v in (ats_plan.suggested_summary_themes if ats_plan else [])[:5])
    min_summary_words = 70

    # Assess candidate timeline for seniority safety context
    if timeline is None:
        timeline = assess_candidate_timeline(profile)
    is_fresher = is_fresher_or_student(timeline)
    timeline_summary = (
        f"Candidate is a {'student/fresher' if timeline.is_student else 'fresher'}" if is_fresher
        else f"Candidate has {timeline.professional_years}y professional experience (level: {timeline.candidate_seniority.value})"
    ) + (
        f" with {timeline.internship_years}y internship experience."
        if timeline.internship_months > 0 else "."
    ) if not is_fresher else (
        f" (no full-time work)."
        if not timeline.has_full_time_work
        else f" with {timeline.internship_years}y internship experience."
    )

    seniority_safety = (
        "SENIORITY SAFETY: The target title above has already been adjusted based on candidate evidence. "
        "Do NOT restore Senior, Lead, Principal, Architect, or Manager unless the candidate evidence unambiguously supports it. "
        "If the candidate is a fresher/student, every bullet must reflect entry-level context (projects, coursework, internships). "
        "Never write bullets that imply the candidate led teams, owned architecture decisions, or drove org-wide strategy unless evidence explicitly supports it."
    )

    prompt = f"""RESUME COMPOSITION INPUT

TARGET TITLE: {_sanitize_prompt_text((ats_plan.target_resume_title if ats_plan else parsed_jd.job_title), 160)}
ROLE FAMILY: {_sanitize_prompt_text(parsed_jd.job_title, 160)}
TARGET COMPANY: {_sanitize_prompt_text(parsed_jd.company or 'Target Company', 160)}
CANDIDATE LEVEL: {getattr(strategy, 'classification', 'experienced')}
SECTION ORDER: {', '.join(getattr(strategy, 'section_order', []) or [])}
STRATEGY HINT: {strategy_hint}

TIMELINE: {timeline_summary}
{seniority_safety}

JD ALIGNMENT TARGETS
Do not copy JD prose. You MUST include all listed ATS keywords naturally.
In realistic mode, unsupported terms go only to Learning Focus. In aggressive mode, the user approved using JD keywords across skills, bullets, and project descriptions.

PRIORITY TERMS:
{chr(10).join(f'  - {kw}' for kw in top_keywords) or '  (see full list below)'}

{kw_section}

ABSTRACT REQUIREMENT THEMES:
{', '.join(requirement_themes) or '(none)'}

CANDIDATE EVIDENCE
Write claims from this evidence. Do not copy JD prose or hiring language.
{rag_section}

SELECTED EXPERIENCES:
{exp_detail or '(none)'}

SELECTED PROJECTS:
{proj_detail or '(none)'}

CANDIDATE SKILLS: {skills_str or '(none)'}
SUMMARY THEMES: {summary_themes or '(natural evidence-backed positioning)'}
STYLE: {style_guidance or 'Clean single-column ATS format.'}
OPTIONAL USER TAILORING INSTRUCTIONS:
{_sanitize_prompt_text(additional_alignment_text or '(none)', 4000)}

OUTPUT TASKS
1. Use the target title above exactly.
2. Summary: {min_summary_words}-{MAX_SUMMARY_WORDS} words of evidence-backed positioning.
3. Bullets: one complete sentence each; action + context + supported skill/tool + credible outcome.
4. Skills: recruiter-safe groups; unsupported JD terms only in Learning Focus.
5. Keep JD text as alignment context only; do not quote or paraphrase JD sentences."""

    if emphasis:
        prompt += f"\n\nEMPHASIS: '{_sanitize_prompt_text(emphasis, 240)}'"

    return prompt


def _build_rag_evidence_section(rag_evidence: list[RequirementEvidence]) -> str:
    """Build targeted evidence matched to JD requirements for the composer prompt."""
    if not rag_evidence:
        return ""
    lines = [
        "TARGETED EVIDENCE (matched to JD requirements):",
        "For each requirement below, use the matched profile evidence first.",
        "If a requirement has no direct evidence, keep it out of hands-on claims and place relevant terms in Learning Focus.",
        "",
    ]
    for req_ev in rag_evidence[:12]:
        lines.append(f"REQUIREMENT: {_sanitize_prompt_text(req_ev.requirement, 220)} [{req_ev.priority}]")
        if req_ev.is_covered and req_ev.top_evidence:
            for index, evidence in enumerate(req_ev.top_evidence[:2], 1):
                text = _sanitize_prompt_text(evidence.chunk_text, 300)
                lines.append(
                    f"  Evidence {index} ({evidence.chunk_type}, similarity={evidence.similarity:.2f}): {text}"
                )
        else:
            lines.append("  [No direct evidence; do not assert as hands-on experience.]")
        lines.append("")
    return "\n".join(lines)


def _limit_prompt_size(prompt: str) -> str:
    """Keep composer prompts under an approximate configured token budget."""
    max_chars = max(4000, get_settings().GEMINI_MAX_TOKENS * 4)
    if len(prompt) <= max_chars:
        return prompt
    logger.warning("composer.prompt_truncated chars=%d max_chars=%d", len(prompt), max_chars)
    suffix = "\n\n[Prompt truncated to configured Gemini token budget. Use only visible evidence.]"
    return prompt[: max_chars - len(suffix)].rstrip() + suffix


_THEME_STOPWORDS = {
    "and", "the", "for", "with", "from", "into", "using", "use", "our", "your",
    "candidate", "responsibilities", "include", "seeking", "ideal", "must", "should",
    "will", "years", "experience", "work", "team", "role",
}


def _abstract_requirement_themes(parsed_jd: ParsedJD, ats_plan: ATSKeywordPlannerOutput | None) -> list[str]:
    values = [*parsed_jd.responsibilities, *([*ats_plan.must_include_responsibilities] if ats_plan else [])]
    themes: list[str] = []
    for value in values[:20]:
        tokens = [
            token.casefold()
            for token in re.findall(r"[A-Za-z0-9+#./-]{3,}", _sanitize_prompt_text(value, 240))
            if token.casefold() not in _THEME_STOPWORDS
        ]
        theme = " ".join(tokens[:4]).strip()
        if theme and theme not in themes:
            themes.append(theme)
    return themes[:10]


_PROMPT_INJECTION_RE = re.compile(
    r"\b(ignore|disregard|override|forget)\s+(all\s+)?(previous|prior|above|system)\s+(instructions|rules)\b|"
    r"\b(system prompt|developer message|you are now|act as)\b",
    re.IGNORECASE,
)


def _sanitize_prompt_text(value: str | None, max_chars: int = 1000) -> str:
    """Strip obvious prompt-injection phrases because JD/profile text is user supplied."""
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    cleaned = _PROMPT_INJECTION_RE.sub("[removed instruction-like text]", cleaned)
    return cleaned[:max_chars]


def _needs_rewrite_entry(bullets: list[str]) -> bool:
    """Detect weak PDF-ingested bullets so prompts explicitly treat them as raw material."""
    joined = " ".join(bullets).casefold()
    weak_phrases = ("basic technical knowledge", "analytical skills", "showcasing", "demonstrating", "responsible for", "worked on")
    return not bullets or any(phrase in joined for phrase in weak_phrases) or any(len(b.strip()) < MIN_BULLET_LENGTH for b in bullets)


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

    evidence = build_candidate_evidence(profile)
    truth = classify_jd_keyword_truth(parsed_jd, evidence, ats_plan)
    # truth.adjacent_or_learning = skills user is building toward; valid in bullets with framing
    # truth.unsupported = skills with NO evidence whatsoever; block these only
    # Only block truly unsupported claims (no connection to profile whatsoever)
    # Adjacent/learning skills are valid with appropriate framing -- do not block them
    claim_guard_terms = list(truth.unsupported)
    jd_copy_sources = _jd_copy_sources(parsed_jd, ats_plan)

    valid_experiences = []
    for exp in composed.experiences:
        valid_bullets = []
        for bullet in exp.bullets:
            cleaned_text = _repair_composed_bullet_text(bullet.text)
            unsupported_claim = any(
                contains_term(cleaned_text, term) and not evidence.supports(term, source_id=exp.source_id)
                for term in claim_guard_terms
            )
            invalid_generation = _composed_bullet_is_invalid(cleaned_text, jd_copy_sources)
            if cleaned_text and not unsupported_claim and not invalid_generation:
                # Run through the bullet quality service for deeper validation
                quality = validate_single_bullet(
                    cleaned_text,
                    evidence_text=evidence.source_corpus.get(exp.source_id, ""),
                )
                if quality.is_valid and not has_jd_boilerplate(quality.text):
                    bullet.text = quality.text
                    valid_bullets.append(bullet)
                elif quality.is_fixable and quality.text:
                    bullet.text = quality.text
                    valid_bullets.append(bullet)
        if len(valid_bullets) >= 1:
            exp.bullets = valid_bullets
            valid_experiences.append(exp)
        else:
            logger.warning("Composer dropped experience %s because it returned zero valid bullets", exp.source_id)
    composed.experiences = valid_experiences

    valid_projects = []
    for project in composed.projects:
        valid_bullets = []
        for bullet in project.bullets:
            cleaned_text = _repair_composed_bullet_text(bullet.text)
            unsupported_claim = any(
                contains_term(cleaned_text, term) and not evidence.supports(term, source_id=project.source_id)
                for term in claim_guard_terms
            )
            invalid_generation = _composed_bullet_is_invalid(cleaned_text, jd_copy_sources)
            if cleaned_text and not unsupported_claim and not invalid_generation:
                quality = validate_single_bullet(
                    cleaned_text,
                    evidence_text=evidence.source_corpus.get(project.source_id, ""),
                )
                if quality.is_valid and not has_jd_boilerplate(quality.text):
                    bullet.text = quality.text
                    valid_bullets.append(bullet)
                elif quality.is_fixable and quality.text:
                    bullet.text = quality.text
                    valid_bullets.append(bullet)
        if len(valid_bullets) >= 1:
            project.bullets = valid_bullets
            valid_projects.append(project)
        else:
            logger.warning("Composer dropped project %s because it returned zero valid bullets", project.source_id)
    composed.projects = valid_projects

    composed.skill_groups = sanitize_resume_skill_groups(composed.skill_groups)


_COMPOSED_CONTAMINATION_RE = re.compile(
    r"\b(?:we are seeking|ideal candidate|responsibilities include|equal opportunity|apply now|job description|about us)\b",
    re.IGNORECASE,
)
_COMPOSED_TERMINAL_RE = re.compile(r"[.!?]$")


def _repair_composed_bullet_text(text: str | None) -> str:
    cleaned = _clean_grammar_errors(re.sub(r"\s+", " ", str(text or "")).strip())
    cleaned = cleaned.strip(" -*\t")
    # Use the quality service to detect and fix dangling endings
    if is_dangling_ending(cleaned):
        quality_text = repair_incomplete_bullet(cleaned, evidence_text=None)
        if quality_text:
            cleaned = quality_text
    if cleaned and not _COMPOSED_TERMINAL_RE.search(cleaned):
        cleaned = f"{cleaned.rstrip(' ,;:')}."
    return cleaned


def _composed_bullet_is_invalid(text: str, jd_copy_sources: list[str]) -> bool:
    if not text or not _COMPOSED_TERMINAL_RE.search(text):
        return True
    if _COMPOSED_CONTAMINATION_RE.search(text):
        return True
    if has_jd_boilerplate(text):
        return True
    normalized = _normalized_copy_text(text)
    return any(source and len(source.split()) >= 5 and source in normalized for source in jd_copy_sources)


def _jd_copy_sources(parsed_jd: ParsedJD, ats_plan: ATSKeywordPlannerOutput | None) -> list[str]:
    values = [
        *parsed_jd.responsibilities,
        *[requirement.text for requirement in parsed_jd.requirements],
        *([*ats_plan.must_include_responsibilities] if ats_plan else []),
        *_raw_jd_sentence_fragments(parsed_jd.raw_text),
    ]
    return _dedupe_strings([_normalized_copy_text(value) for value in values])


def _normalized_copy_text(value: str | None) -> str:
    lowered = str(value or "").casefold()
    lowered = re.sub(r"[^a-z0-9+#./\s-]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _raw_jd_sentence_fragments(raw_text: str | None) -> list[str]:
    fragments = re.split(r"(?<=[.!?])\s+|\n+", str(raw_text or ""))
    return [
        fragment.strip()
        for fragment in fragments
        if 5 <= len(_normalized_copy_text(fragment).split()) <= 28
    ][:40]


def _repair_or_fallback_composed_entries(
    composed: _ComposedResume,
    *,
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    selected_experience: list,
    selected_projects: list,
    ats_plan: ATSKeywordPlannerOutput | None,
) -> None:
    """Use deterministic evidence bullets when LLM output has no safe source bullets."""
    experience_by_id = {entry.source_id: entry for entry in composed.experiences}
    for source in selected_experience:
        entry = experience_by_id.get(source.id)
        if entry and entry.bullets:
            continue
        fallback = build_evidence_fallback_bullets(
            section_type="experience",
            source_id=source.id,
            profile_context=source,
            parsed_jd=parsed_jd,
            ats_plan=ats_plan,
            bullet_limit=MAX_BULLETS_PER_EXPERIENCE,
        )
        safe_bullets = _fallback_composed_bullets(fallback, parsed_jd, ats_plan)
        if not safe_bullets:
            continue
        if entry:
            entry.bullets = safe_bullets
        else:
            composed.experiences.append(_ComposedExperience(source_id=source.id, bullets=safe_bullets))

    project_by_id = {entry.source_id: entry for entry in composed.projects}
    for source in selected_projects:
        entry = project_by_id.get(source.id)
        if entry and entry.bullets:
            continue
        fallback = build_evidence_fallback_bullets(
            section_type="project",
            source_id=source.id,
            profile_context=source,
            parsed_jd=parsed_jd,
            ats_plan=ats_plan,
            bullet_limit=4,
        )
        safe_bullets = _fallback_composed_bullets(fallback, parsed_jd, ats_plan)
        if not safe_bullets:
            continue
        if entry:
            entry.bullets = safe_bullets
        else:
            composed.projects.append(_ComposedProject(source_id=source.id, bullets=safe_bullets))


def _fallback_composed_bullets(
    bullets: list[ResumeBullet],
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
) -> list[_ComposedBullet]:
    copy_sources = _jd_copy_sources(parsed_jd, ats_plan)
    result: list[_ComposedBullet] = []
    for bullet in bullets:
        text = _repair_composed_bullet_text(bullet.text)
        if _composed_bullet_is_invalid(text, copy_sources):
            continue
        result.append(_ComposedBullet(text=text, matched_keywords=bullet.matched_keywords))
    return result


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
    generation_id: str,
    profile: MasterProfile,
    parsed_jd: ParsedJD,
    relevance: _RelevanceResult,
    composed: _ComposedResume,
    selected_experience: list,
    selected_projects: list,
    locked_bullets: dict[str, str],
    emphasis: str | None,
    ats_plan: ATSKeywordPlannerOutput | None = None,
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
    skill_groups = build_skill_taxonomy(composed.skill_groups, parsed_jd, profile, target_pages=1)

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
        generation_id=generation_id,
        target_title=composed.target_title,
        summary=composed.summary,
        contact=contact,
        experience=experience_entries,
        education=education_entries,
        skills=skill_groups,
        projects=project_entries,
        certifications=cert_entries,
        achievements=_profile_achievements(profile),
        custom_sections=_profile_custom_sections(profile, parsed_jd),
        section_order=(build_resume_strategy(parsed_jd, profile).section_order),
        emphasis=emphasis,
        warnings=list(ats_plan.seniority_warnings) if ats_plan else [],
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

        # Enforce bullet length rules (validation only, no truncation)
        text = cb.text.strip()
        if len(text) < MIN_BULLET_LENGTH:
            continue  # Skip too-short bullets

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


def _profile_achievements(profile: MasterProfile) -> list[ResumeAchievementEntry]:
    entries: list[ResumeAchievementEntry] = []
    seen_titles: set[str] = set()

    def add_entry(entry: ResumeAchievementEntry) -> None:
        # Deduplicate by title because awards may arrive through both structured and custom sections.
        key = _clean_text_key(entry.title)
        if not key or key in seen_titles:
            return
        seen_titles.add(key)
        entries.append(entry)

    for award in profile.awards:
        add_entry(
            ResumeAchievementEntry(
                source_id=award.id,
                title=award.title,
                issuer=award.issuer,
                date=award.date,
                description=award.description,
            )
        )
    direct_achievements = getattr(profile, "achievements", []) or []
    for achievement in direct_achievements:
        title = getattr(achievement, "title", None) or str(achievement)
        add_entry(ResumeAchievementEntry(
            source_id=getattr(achievement, "id", f"achievement-{len(entries)}"),
            title=title,
            issuer=getattr(achievement, "issuer", None),
            date=getattr(achievement, "date", None),
            description=getattr(achievement, "description", None),
        ))
    custom_items: list[str] = []
    for section_name in ("Achievements", "Awards", "Recognition", "Honors"):
        custom_items.extend(profile.custom_sections.get(section_name, []))
    for index, item in enumerate(custom_items):
        cleaned = " ".join(str(item).split()).strip()
        if cleaned:
            add_entry(ResumeAchievementEntry(source_id=f"custom-achievement-{index}", title=cleaned))
    return entries


def _profile_custom_sections(profile: MasterProfile, parsed_jd: ParsedJD) -> list[ResumeCustomSection]:
    """
    Include ALL non-reserved custom sections unconditionally.

    CHANGED: Removed JD token-matching filter — custom sections (Languages, Tools,
    Certificates, Achievements, etc.) are ALWAYS included when non-empty.
    Filtering them out silently made thin resumes even thinner and lowered ATS scores.
    """
    reserved = {"certifications", "education", "projects", "experience", "skills"}
    sections: list[ResumeCustomSection] = []
    for title, items in profile.custom_sections.items():
        title_key = title.casefold()
        if title_key in reserved or title_key in {"achievements", "awards"}:
            continue
        cleaned_items = _dedupe_strings([str(item) for item in items])
        if not cleaned_items:
            continue
        sections.append(ResumeCustomSection(title=title, items=cleaned_items))
    return sections


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split()).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _clean_text_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


# ─── Profile Enrichment (Always-Generate) ────────────────────────────────────

def _enrich_thin_profile(profile: MasterProfile, parsed_jd: ParsedJD) -> MasterProfile:
    """
    Enrich a thin/empty profile so the AI composer always has source material.

    Strategy (answers Q1 + Q5 from architecture review):
    - Work experience empty → synthesise from skills + education + projects + certs + achievements.
    - Skills empty → inject from JD required_skills + project technologies (Q5: A+B combined).
    - Does NOT invent employers, dates, degrees, or certifications.
    - All generated entries are flagged needs_rewrite=True so the AI rewrites them entirely.
    """
    from app.schemas.profile import WorkExperience, Skill
    import uuid

    updates: dict = {}

    # ── Enrich skills first (needed by experience synthesis below) ───────
    enriched_skills = list(profile.skills)
    existing_skill_names = {s.name.casefold() for s in enriched_skills}

    # Q5-A: infer skills from project technologies
    for project in profile.projects:
        for tech in project.technologies:
            if tech.casefold() not in existing_skill_names and tech.strip():
                enriched_skills.append(Skill(name=tech))
                existing_skill_names.add(tech.casefold())

    if enriched_skills != list(profile.skills):
        updates["skills"] = enriched_skills

    # ── Synthesise experience when work_experience is empty ──────────────
    if not profile.work_experience:
        # Construct context from all available profile material.
        skill_names = [s.name for s in enriched_skills[:15]]
        edu_context = ""
        if profile.education:
            edu = profile.education[0]
            edu_context = f"{edu.degree} in {edu.field_of_study or 'the relevant field'} at {edu.institution}"
        
        description_parts = []
        if edu_context:
            description_parts.append(f"Candidate pursuing {edu_context}.")
        if skill_names:
            description_parts.append(f"Skills: {', '.join(skill_names)}.")
        if profile.projects:
            proj_names = [p.name for p in profile.projects[:3]]
            description_parts.append(f"Projects: {', '.join(proj_names)}.")

        description = " ".join(description_parts) or f"Student/Fresher targeting {parsed_jd.job_title} role."

        synthetic_exp = WorkExperience(
            id=f"synthetic-exp-{uuid.uuid4().hex[:8]}",
            company="Project Experience",
            title=parsed_jd.job_title or "Software Developer",
            location=None,
            start_date="2024-01", # Assume recent
            end_date=None,
            is_current=True,
            description=description,
            bullets=[],
            needs_rewrite=True,
        )
        updates["work_experience"] = [synthetic_exp]

    # ── Mark ALL existing empty-bullet entries for rewrite ───────────────
    if profile.work_experience and "work_experience" not in updates:
        rewritten = []
        for exp in profile.work_experience:
            if not exp.bullets or all(len(b.strip()) < 40 for b in exp.bullets):
                rewritten.append(exp.model_copy(update={"needs_rewrite": True}))
            else:
                rewritten.append(exp)
        if rewritten != list(profile.work_experience):
            updates["work_experience"] = rewritten

    if not updates:
        return profile

    return profile.model_copy(update=updates)
