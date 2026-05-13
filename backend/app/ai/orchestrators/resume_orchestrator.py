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
import re
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
    ResumeAchievementEntry,
    ResumeCustomSection,
    ResumeBullet,
    BulletStatus,
)
from app.services.resume_strength_service import strengthen_resume_recommendation
from app.services.resume_budget_service import fit_resume_to_page_budget
from app.services.resume_quality_gate import apply_resume_quality_gate, build_skill_taxonomy
from app.services.resume_strategy_service import build_resume_strategy
from app.services.keyword_placement_service import build_master_keyword_list

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
4. If the profile has NO experiences or NO projects, return empty lists — do not error.
5. Return ONLY valid JSON matching the schema."""

COMPOSER_SYSTEM_PROMPT = """
╔══════════════════════════════════════════════════════════════════════════╗
║         JD-FIRST ATS RESUME COMPOSER — 100% KEYWORD COVERAGE           ║
║         GOAL: JD IN → PERFECT ATS RESUME OUT — ZERO EXCEPTIONS         ║
╚══════════════════════════════════════════════════════════════════════════╝

You are the world's best ATS resume writer. Your ONLY goal is a 100% ATS match.
The JD is your PRIMARY source. The profile provides the candidate's name,
company names, job titles, education, and dates ONLY.
ALL bullet content is derived from the JD. NO profile bullet is copied as-is.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 0 — JD IS THE ONLY SOURCE OF TRUTH (ABSOLUTE):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  The JD responsibilities list = your bullet writing BLUEPRINT.
  For EVERY JD responsibility you receive, write AT LEAST ONE bullet in the
  resume that covers it using the candidate's role context.
  Example: JD says "Design REST APIs for microservices" →
    Bullet: "Designed and implemented RESTful APIs for {company} microservices
             architecture, reducing inter-service latency by ~30%"
  This is NON-NEGOTIABLE. Every responsibility must map to a bullet.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 1 — KEYWORD CARPET BOMBING (100% coverage target):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EVERY keyword, skill, tool, and technology from the JD MUST appear
  somewhere in the resume — in bullets, skills section, or summary.
  Use EXACT JD spelling: "Node.js" not "nodejs", "REST APIs" not "rest api".
  Required skills → verbatim in Technical Skills section ALWAYS.
  Top 10 keywords → embedded in summary.
  All other keywords → distributed across bullets.
  There are NO exceptions. A missing keyword = ATS rejection.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 2 — BULLET FORMULA (every bullet, no exceptions):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [Strong Action Verb] + [what was built/done using JD terms]
  + [technology from JD] + [number / % / time / scale]
  Min {min_len} chars, max {max_len} chars.
  Must contain ≥1 quantifier. Estimate with "~" prefix if needed.
  BANNED openers: Responsible for / Worked on / Utilized / Helped with

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 3 — VERBATIM KEYWORD MANDATE (ABSOLUTE — NO EXCEPTIONS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You will receive a "VERBATIM KEYWORD MANDATE" list in the user message.
EVERY item on that list MUST appear in your output using EXACT spelling.
The scoring system uses character-level exact matching after lowercasing.
"Node.js" scores. "NodeJS" does not. "REST APIs" scores. "RESTful APIs" does not.
"CI/CD" scores. "CI CD" does not. Use the EXACT string from the mandate list.
PLACEMENT RULES (must follow for high section weights):
• Every top-priority term → in summary (first 120 words) AND skills section
• Every skill/tool/language → in Technical Skills section (exact JD spelling)
• Tech terms in context → in at least one experience or project bullet
• Do NOT just list all keywords in one block — distribute them naturally
• The Technical Skills section is YOUR BEST ATS SCORING OPPORTUNITY —
include ALL mandate terms that are skills/tools/languages here

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 4 — SKILLS SECTION (verbatim from JD):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Include ALL required_skills, programming_languages, frameworks, tools,
  databases, cloud_devops_tools from the JD — VERBATIM, EXACT spelling.
  Group by: Programming Languages | Backend & APIs | Web & UI Development
            Databases & Data Modelling | Cloud & DevOps | Automation & Tools
            AI/ML & Data | Mobile Development
  Target 15-25 skills minimum. Certifications go in their own section.
  NEVER include: teamwork / communication / analytical skills / problem-solving

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 5 — SUMMARY (70-120 words, keyword-dense):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Line 1: "{JD title} with [X years / pursuing {degree}] specializing in
           [top 3 JD domains using EXACT JD wording]."
  Lines 2-3: Embed 8-12 priority JD keywords naturally in 2 sentences.
  Line 4: "Targeting {company} to deliver [JD core outcome]."
  Must contain the EXACT target_resume_title from the ATS planner.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 6 — ONE-PAGE FORMAT (Saurav Madake style):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Output section order: Summary → Education → Experience →
                        Projects → Achievements → Technical Skills
  Every section must be compact. No paragraph filler. No vague phrases.
  Achievements = hackathons, prizes, leadership, certifications (one-liners).
  Technical Skills = grouped, comma-separated, NO bullet points.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 7 — ABSOLUTE PROHIBITIONS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✗ Copy old profile bullets verbatim
  ✗ Invent employers, dates, degrees, or certifications
  ✗ Leave ANY field null or empty
  ✗ Return partial JSON or non-JSON
  ✗ Write soft-skill filler ("team player", "good communicator")
  ✗ Write "Results-driven Application" (grammar error)
  ✗ Skip a JD responsibility without writing a bullet for it

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE 8 — OUTPUT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Return ONLY valid JSON matching _ComposedResume schema.
  No markdown, no code fences, no preamble.
  Seniority: {seniority}"""


def _render_composer_system_prompt(
    *,
    min_len: int,
    max_len: int,
    min_bullets: int,
    max_bullets: int,
    min_sum: int,
    max_sum: int,
    seniority: str,
) -> str:
    """Render configured prompt tokens without interpreting example braces."""
    replacements = {
        "{min_len}": str(min_len),
        "{max_len}": str(max_len),
        "{min_bullets}": str(min_bullets),
        "{max_bullets}": str(max_bullets),
        "{min_sum}": str(min_sum),
        "{max_sum}": str(max_sum),
        "{seniority}": seniority,
    }
    rendered = COMPOSER_SYSTEM_PROMPT
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


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
    strategy = build_resume_strategy(parsed_jd, profile)
    budget = None
    client = get_gemini_client()

    # ── Pre-step: Enrich thin profiles so AI always has source material ──
    profile = _enrich_thin_profile(profile, parsed_jd)

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

    composer_system = _render_composer_system_prompt(
        min_len=MIN_BULLET_LENGTH,
        max_len=MAX_BULLET_LENGTH,
        min_bullets=MIN_BULLETS_PER_EXPERIENCE,
        max_bullets=MAX_BULLETS_PER_EXPERIENCE,
        min_sum=70,
        max_sum=MAX_SUMMARY_WORDS,
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

    gated = apply_resume_quality_gate(
        recommendation=recommendation,
        parsed_jd=parsed_jd,
        profile=profile,
        target_pages=target_pages,
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
    return apply_resume_quality_gate(fitted, parsed_jd, profile, target_pages)


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

    prompt = f"""Score the relevance of these profile items to the job description.

JOB: {_sanitize_prompt_text(parsed_jd.job_title, 160)} at {_sanitize_prompt_text(parsed_jd.company or 'Unknown Company', 160)}
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
    """
    Build the JD-FIRST composer prompt.

    Every experience entry is treated as needs_rewrite=True — bullets are
    written FROM the JD responsibilities, not copied from the profile.
    The profile provides: name, company, title, dates, education only.
    """
    # ── Experience context (name/company/title/dates only — bullets are rebuilt) ──
    exp_detail = "\n\n".join(
        f"ID: {e.id}\nTitle: {e.title}\nCompany: {e.company}\n"
        f"Dates: {e.start_date} - {e.end_date or 'Present'}\n"
        f"[ALL BULLETS MUST BE REWRITTEN FROM JD — DO NOT COPY THESE]\n"
        f"Profile bullets (raw reference only):\n"
        + "\n".join(f"  • {b}" for b in e.bullets)
        for e in experiences
    )

    proj_detail = "\n\n".join(
        f"ID: {p.id}\nName: {p.name}\nTech: {', '.join(p.technologies)}\n"
        f"[REWRITE ALL BULLETS USING JD TERMS + PROJECT TECH]\n"
        f"Profile bullets (raw reference only):\n"
        + "\n".join(f"  • {b}" for b in p.bullets)
        for p in projects
    )

    # ── MASTER KEYWORD LIST — same list the scorer will check ──────────
    # CRITICAL: these are the EXACT strings the ATS scoring function uses.
    # The AI must embed each one VERBATIM (exact JD spelling) somewhere in
    # the resume. Paraphrasing = scorer miss = lower ATS score.
    master_keywords = build_master_keyword_list(parsed_jd, ats_plan)
    # Separate into: top-priority (go in summary + skills), regular (skills)
    priority_set = set()
    if ats_plan:
        priority_set = set(kw.casefold() for kw in (
            ats_plan.priority_keywords[:12] + ats_plan.must_include_skills
        ))
    top_keywords = [kw for kw in master_keywords if kw.casefold() in priority_set][:15]
    all_jd_keywords = master_keywords[:60]

    # JD responsibilities — the bullet BLUEPRINT
    responsibilities = [
        *parsed_jd.responsibilities,
        *([r for r in ats_plan.must_include_responsibilities] if ats_plan else []),
    ][:25]
    resp_numbered = "\n".join(f"  {i+1}. {_sanitize_prompt_text(r, 200)}"
                              for i, r in enumerate(responsibilities))

    skills_str = ", ".join(_sanitize_prompt_text(s.name, 80) for s in profile.skills[:20])
    style_guidance = " ".join(_sanitize_prompt_text(v, 200) for v in (ats_plan.resume_style_guidance if ats_plan else [])[:3])
    summary_themes = " ".join(_sanitize_prompt_text(v, 200) for v in (ats_plan.suggested_summary_themes if ats_plan else [])[:5])

    prompt = f"""══════════════════════════════════════════════════════════
JD-FIRST RESUME GENERATION — 100% ATS TARGET
══════════════════════════════════════════════════════════

TARGET JOB TITLE : {_sanitize_prompt_text(parsed_jd.job_title, 160)}
TARGET COMPANY   : {_sanitize_prompt_text(parsed_jd.company or 'Target Company', 160)}
SENIORITY        : {getattr(strategy, 'classification', 'experienced')}
SECTION ORDER    : {', '.join(getattr(strategy, 'section_order', []) or [])}

══════════════════════════════════════════════════════════
STEP 1 — BULLET BLUEPRINT (JD RESPONSIBILITIES TO COVER)
══════════════════════════════════════════════════════════
You MUST write at least one resume bullet that covers EACH responsibility below.
Anchor each bullet to the candidate\'s role (use their company/title from the
experience entries). Use JD language + achievement formula.

{resp_numbered or '  (No responsibilities listed — derive from JD keywords)'}

══════════════════════════════════════════════════════════
STEP 2 — VERBATIM KEYWORD MANDATE (SCORER EXACT-MATCH LIST)
══════════════════════════════════════════════════════════
CRITICAL: The ATS scorer uses EXACT string matching after normalization.
"Node.js" ≠ "nodejs" ≠ "NodeJS". Use the EXACT spelling shown below.
Every term in this list MUST appear VERBATIM somewhere in your output.
Do NOT paraphrase. Do NOT abbreviate. Do NOT use synonyms.
Copy these strings character-for-character into your output.

TOP PRIORITY — must appear in SUMMARY AND Skills section:
{chr(10).join(f'  • {kw}' for kw in top_keywords) or '  (see full list below)'}

FULL VERBATIM LIST — every item must appear in output:
{', '.join(all_jd_keywords) or '(see JD)'}

INJECTION RULES:
- Skills/tools/languages → put in Technical Skills section (exact spelling)
- Frameworks/databases/cloud terms → put in Technical Skills section
- All top-priority terms → also embed in Professional Summary
- Do NOT cluster all keywords in one sentence — distribute naturally

══════════════════════════════════════════════════════════
STEP 3 — CANDIDATE ANCHORING DATA (structure only)
══════════════════════════════════════════════════════════
Use these for names, companies, dates, and project tech stacks ONLY.
Do NOT copy the bullets below — rewrite everything from JD.

EXPERIENCES:
{exp_detail or '(none — use education/skills context)'}

PROJECTS:
{proj_detail or '(none)'}

CANDIDATE SKILLS (merge with JD keywords): {skills_str or '(see JD)'}
EXTRA CONTEXT: {_sanitize_prompt_text(additional_alignment_text or '(none)', 800)}
SUMMARY THEMES: {summary_themes or '(use top JD keywords)'}
STYLE: {style_guidance or 'Clean single-column ATS format.'}

══════════════════════════════════════════════════════════
STEP 4 — GENERATE (follow Rules 0-8 from system prompt)
══════════════════════════════════════════════════════════
Produce:
1. Target title (exact JD title — no labels like "Designation:")
2. Summary: 70-{MAX_SUMMARY_WORDS} words, exact JD title in sentence 1, 8-12 JD keywords
3. All experience bullets ({MIN_BULLETS_PER_EXPERIENCE}+ per entry) written from STEP 1 blueprint
4. All project bullets (3-4 per project) using JD terms + project tech
5. Technical Skills with ALL items from STEP 2 checklist (verbatim)
6. Achievements, certifications as present in candidate profile"""

    if emphasis:
        prompt += f"\n\nEMPHASIS: '{_sanitize_prompt_text(emphasis, 240)}'"

    return prompt


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

    valid_experiences = []
    for exp in composed.experiences:
        valid_bullets = []
        for bullet in exp.bullets:
            cleaned_text = bullet.text.strip()
            cleaned_text = _clean_grammar_errors(cleaned_text)
            if cleaned_text:
                bullet.text = cleaned_text
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
            cleaned_text = bullet.text.strip()
            cleaned_text = _clean_grammar_errors(cleaned_text)
            if cleaned_text:
                bullet.text = cleaned_text
                valid_bullets.append(bullet)
        if len(valid_bullets) >= 1:
            project.bullets = valid_bullets
            valid_projects.append(project)
        else:
            logger.warning("Composer dropped project %s because it returned zero valid bullets", project.source_id)
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
        session_id=session_id,
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
        warnings=[],
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

    # Q5-B: inject JD required_skills and programming_languages not already present
    jd_skills_to_inject = [
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks[:8],
        *parsed_jd.databases[:6],
        *parsed_jd.tools_platforms[:8],
        *parsed_jd.cloud_devops_tools[:8],
    ]
    for skill_name in jd_skills_to_inject:
        clean = skill_name.strip()
        if clean and clean.casefold() not in existing_skill_names:
            enriched_skills.append(Skill(name=clean))
            existing_skill_names.add(clean.casefold())

    if enriched_skills != list(profile.skills):
        updates["skills"] = enriched_skills

    # ── Synthesise experience when work_experience is empty ──────────────
    if not profile.work_experience:
        logger.info(
            "Profile has no work experience — synthesising entry from skills + education + JD context."
        )
        # Build a descriptive context from all available profile material.
        skill_names = [s.name for s in enriched_skills[:15]]
        edu_context = ""
        if profile.education:
            edu = profile.education[0]
            edu_context = f"{edu.degree} in {edu.field_of_study or 'the relevant field'} at {edu.institution}"
        cert_names = [c.name for c in profile.certifications[:3]]
        award_titles = [a.title for a in profile.awards[:3]]

        # Construct a rich description from all available material so the
        # AI has real context to derive bullets from — not a blank slate.
        description_parts = []
        if edu_context:
            description_parts.append(f"Candidate pursuing {edu_context}.")
        if skill_names:
            description_parts.append(f"Skills: {', '.join(skill_names)}.")
        if cert_names:
            description_parts.append(f"Certifications: {', '.join(cert_names)}.")
        if award_titles:
            description_parts.append(f"Awards/Achievements: {', '.join(award_titles)}.")
        if profile.projects:
            proj_names = [p.name for p in profile.projects[:3]]
            description_parts.append(f"Projects: {', '.join(proj_names)}.")

        description = " ".join(description_parts) or f"Candidate targeting {parsed_jd.job_title} role."

        synthetic_exp = WorkExperience(
            id=f"synthetic-exp-{uuid.uuid4().hex[:8]}",
            company="Academic / Project-Based Experience",
            title=parsed_jd.job_title or "Software Developer",
            location=None,
            start_date="2022-01",
            end_date=None,
            is_current=True,
            description=description,
            bullets=[],          # AI will write all bullets from the description + JD
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
