"""One-call AI composition for fast resume generation."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from app.ai.gemini_client import GeminiClientError, _parse_json_object
from app.config import get_settings
from app.schemas.profile import MasterProfile

class FastResumeContent(BaseModel):
    target_title: str
    summary: str = ""
    contact: dict[str, Any] = Field(default_factory=dict)
    experience: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    certifications: list[dict[str, Any]] = Field(default_factory=list)
    achievements: list[dict[str, Any]] = Field(default_factory=list)
    awards: list[dict[str, Any]] = Field(default_factory=list)
    custom_sections: list[dict[str, Any]] = Field(default_factory=list)
    section_order: list[str] = Field(default_factory=list)


class FastResumeOrchestrator:
    """Compose a resume with exactly one Gemini content-generation call."""

    async def compose(
        self,
        *,
        profile: MasterProfile,
        profile_context: str | None = None,
        raw_jd_text: str,
        extracted_keywords: list[str],
        confirmed_keyword_context: list[dict[str, str]] | None = None,
        job_title: str | None = None,
        company: str | None = None,
        emphasis: str | None = None,
        ats_optimization_mode: str = "realistic",
    ) -> FastResumeContent:
        settings = get_settings()
        if not settings.GEMINI_API_KEY:
            raise GeminiClientError("Gemini API key is not configured.")

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        prompt = _build_prompt(
            profile=profile,
            profile_context=profile_context,
            raw_jd_text=raw_jd_text,
            extracted_keywords=extracted_keywords,
            confirmed_keyword_context=confirmed_keyword_context or [],
            job_title=job_title,
            company=company,
            emphasis=emphasis,
            ats_optimization_mode=ats_optimization_mode,
        )
        aggressive_mode = ats_optimization_mode == "aggressive"
        schema = json.dumps(FastResumeContent.model_json_schema(), indent=2)
        config = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
            system_instruction=(
                "You are an elite AI Resume Tailoring System using an internal multi-agent "
                "workflow. Create concise, role-aligned, recruiter-friendly, ATS-optimized "
                "resume JSON from the candidate master profile and the job description. "
                "Silently perform JD analysis, company-context inference, ATS keyword "
                "strategy, truthfulness control, structure selection, bullet rewriting, "
                "project optimization, technical-skills grouping, renderer safety, and final "
                "quality checks before responding. Return JSON only; never expose workflow "
                "notes, explanations, ATS scores, markdown, or LaTeX in this response. "
                + (
                    "The user approved aggressive ATS optimization, so you may add JD-required skills "
                    "and rewrite experience or project wording for keyword coverage. Keep contact, employers, "
                    "institutions, dates, and seniority credible."
                    if aggressive_mode
                    else "Use only evidence present in the candidate profile. Use exact job-description "
                    "keywords naturally when they are supported by profile facts. Never invent employment, "
                    "degrees, certifications, years of experience, tools, metrics, clearances, awards, or credentials."
                )
            ),
        )

        import asyncio
        for attempt in range(3):
            try:
                response = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=settings.GEMINI_MODEL,
                        contents=(
                            f"{prompt}\n\nReturn ONLY valid JSON matching this schema:\n"
                            f"```json\n{schema}\n```"
                        ),
                        config=config,
                    ),
                    timeout=settings.GEMINI_TIMEOUT_SECONDS,
                )
                break
            except Exception as exc:
                if attempt == 2:
                    if isinstance(exc, asyncio.TimeoutError):
                        raise GeminiClientError("AI service did not respond in time. Please retry.") from exc
                    raise GeminiClientError(f"AI service error: {str(exc)}") from exc
                await asyncio.sleep(2 ** attempt)

        if not response.text:
            raise GeminiClientError("Gemini returned an empty response. Please retry.")
        return FastResumeContent.model_validate(_parse_json_object(response.text))


def _build_prompt(
    *,
    profile: MasterProfile,
    profile_context: str | None,
    raw_jd_text: str,
    extracted_keywords: list[str],
    confirmed_keyword_context: list[dict[str, str]],
    job_title: str | None,
    company: str | None,
    emphasis: str | None,
    ats_optimization_mode: str = "realistic",
) -> str:
    profile_json = profile_context or json.dumps(profile.model_dump(mode="json"), ensure_ascii=True)
    keyword_text = ", ".join(extracted_keywords)
    confirmation_text = json.dumps(confirmed_keyword_context, ensure_ascii=True, indent=2)
    aggressive_mode = ats_optimization_mode == "aggressive"
    mode_rules = (
        "USER-APPROVED AGGRESSIVE ATS MODE (HIGHEST PRIORITY):\n"
        "- You MUST include EVERY keyword from the extracted JD keywords list in the output.\n"
        "- SKILLS: Place ALL technical keywords (languages, frameworks, databases, tools, platforms) "
        "in properly categorized skill groups. Do NOT use 'Learning Focus' — use main groups.\n"
        "- SUMMARY: Include the job title, company, and top 3-5 JD keywords in 2-3 professional sentences.\n"
        "- BULLETS: Weave JD keywords into action-oriented bullets (Action + Tech + Scope + Outcome).\n"
        "- PROJECTS: Add JD-relevant technologies to project tech stacks and descriptions.\n"
        "- MULTI-SECTION: High-priority keywords must appear in at least 2 sections.\n"
        "- You may add JD-required skills and rewrite bullets for keyword coverage.\n"
        "- Do NOT invent fake companies, dates, degrees, certifications, or metrics.\n"
        "- PRE-CHECK: Before returning JSON, verify ALL extracted keywords appear. Add any missing ones."
        if aggressive_mode
        else
        "REALISTIC ATS MODE:\n"
        "- Stay strictly factual.\n"
        "- Put unsupported JD keywords nowhere in the resume content.\n"
        "- Use exact JD keywords naturally only when supported by the profile or user confirmation."
    )
    return f"""
Create a fast ATS-focused final resume JSON for the target role using the candidate master profile. Optimize for recruiter skim value, ATS keyword matching, truthful positioning, and later LaTeX rendering.

Internal multi-agent workflow to perform silently before producing JSON:
- JD Analysis Agent: extract must-have skills, good-to-have skills, exact ATS keywords, required tools, programming languages, frameworks, databases, soft skills, domain keywords, hidden recruiter expectations, seniority level, and role category.
- Company Context Agent: infer the company's industry, business model, products/services, technology focus, and likely candidate preferences from the JD/company fields. Use this only to improve positioning; do not invent company-specific claims.
- ATS Keyword Strategy Agent: map exact JD phrases to real candidate evidence and user-confirmed keyword context. Use full-form/abbreviation pairs where truthful, such as Object-Oriented Programming/OOP, Data Structures and Algorithms/DSA, Software Development Life Cycle/SDLC, Test-Driven Development/TDD, REST APIs, SQL, Git, Agile, debugging, and scalable systems.
- Truthfulness and Claim Control Agent: aggressively rephrase real evidence without adding fake companies, internships, certifications, metrics, tools, seniority, responsibilities, or credentials.
- Resume Structure Agent: choose ATS-friendly section order based on the JD. For fresher, trainee, internship, or academic-heavy roles, projects and technical skills may come before experience. For experienced roles, experience may come first.
- Bullet Rewriting Agent: make every bullet concise, strong, and action-oriented with technology, implementation, and outcome or relevance.
- Project Optimization Agent: rank projects by JD relevance and highlight supported backend, frontend, database, API, algorithm, data, or domain evidence.
- Technical Skills Agent: group skills clearly and place the most JD-relevant truthful skills first.
- LaTeX/ATS Engineer Agent: keep output simple, one-page, ATS-readable, and safe for downstream LaTeX rendering.
- Final Quality Check Agent: verify one-page fit, natural JD keyword use, truthfulness, strongest-first ordering, strong bullets, complete JSON, and no unsupported claims.

Target role: {job_title or "Infer from JD"}
Company: {company or "Unknown"}
Emphasis: {emphasis or "Use the strongest JD-aligned evidence"}

Deterministically extracted JD keywords to evaluate first:
{keyword_text}

User-confirmed missing keyword context:
{confirmation_text}

ATS optimization mode:
{mode_rules}

Job description:
{raw_jd_text[:12000]}

Candidate profile summary/index JSON:
{profile_json[:20000]}

Output contract:
- Return valid JSON only. No markdown, comments, prose, or explanation outside the JSON object.
- Use only fields allowed by the provided schema.
- Use standard ATS headings via section_order: summary, skills, experience, projects, education, certifications, achievements.
- In aggressive mode, include clean JD keywords where they improve ATS coverage. In realistic mode, the backend returns unsupported missing JD keywords separately after deterministic scoring.
- Do not return LaTeX from this step; the application renders the final LaTeX/PDF from this JSON after validation.
- Do not mention the internal agent workflow in any output field.

Factuality rules:
- Use only facts found in the candidate profile.
- Do not invent employers, job titles, dates, degrees, certifications, licenses, schools, publications, awards, years of experience, metrics, clients, domains, or tools.
- If a JD keyword is not supported by the profile, omit it from the resume instead of implying experience.
- User-confirmed keyword context may prove familiarity with that keyword, but it does not prove employment history, project history, credentials, metrics, clients, years of experience, or seniority.
- A keyword confirmed as "professional" may be used in skills, summary, and relevant experience bullets only when it does not create a fake employer, date, credential, metric, or responsibility.
- A keyword confirmed as "project" may be used in skills and project content; do not present it as professional employment experience.
- A keyword confirmed as "basic" may be listed in skills only; do not create bullets claiming delivery impact with it.
- A keyword confirmed as "learning" may be included only as a learning-focus skill if appropriate; do not claim hands-on production experience.
- A keyword confirmed as "no" or absent from the confirmation context is unconfirmed and must not be treated as a candidate fact.
- You may rewrite weak profile bullets for clarity, but the rewritten bullet must preserve the original scope and facts.
- If no metric exists, write impact in qualitative terms; do not create numbers.

ATS keyword rules:
- Use exact JD keywords naturally when the profile supports them.
- Prioritize required skills, tools, platforms, methodologies, domains, and seniority signals from the JD.
- Place supported high-value keywords in the summary, skills, and the most relevant experience/project bullets.
- Avoid keyword stuffing and avoid repeating a keyword without evidence.

Summary rules:
- Create a strong professional summary of 2-3 lines.
- Align the summary to the target role, seniority, core tools, domain, and strongest evidence from the profile.
- Include 3-5 supported JD-relevant keywords naturally.

Skills rules:
- Create a role-aligned skills section using ATS-readable groups.
- Group skills by practical categories such as Programming Languages, Backend, Frontend, Databases, Cloud/DevOps, Tools, Domain, or Methods.
- Include only skills supported by the profile or explicitly confirmed by the user at professional, project, basic, or learning level.
- Prefer exact JD phrasing for supported skills.

Experience and project selection rules:
- Select the most JD-relevant experience first.
- Include less relevant roles only if they add useful evidence or career continuity.
- Select projects only when they strengthen role alignment or cover supported JD keywords.
- Keep entries standard and parseable: company/title/dates/location plus bullets.

Bullet rules:
- Write bullets with action + impact + tools + result whenever profile evidence supports it.
- Make bullets specific, recruiter-readable, and role-aligned.
- Start bullets with strong action verbs.
- Tie work to business, product, operational, technical, performance, quality, automation, reliability, customer, or team outcomes.
- Include supported tools and JD keywords inside bullets where natural.
- Avoid generic phrases like responsible for, worked on, helped with, or involved in.

Do not include:
- PDF, DOCX, LaTeX, rendering, file paths, recruiter review, RAG notes, or repair-loop diagnostics.
- Unsupported missing keywords inside resume sections.
""".strip()
