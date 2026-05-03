"""
JD Orchestrator — manages the JD analysis AI pipeline step.

This is step 1 of the multi-step AI pipeline:
  Raw JD text → Gemini → ParsedJD (structured, validated)
"""

from __future__ import annotations

import logging

from app.ai.gemini_client import GeminiClientError, get_gemini_client
from app.ai.jd_fallback import analyze_jd_without_ai
from app.schemas.jd import ParsedJD
from app.services.jd_ats_extraction import enrich_parsed_jd_for_ats

logger = logging.getLogger(__name__)

JD_ANALYSIS_SYSTEM_PROMPT = """You are an expert job description analyzer for an ATS-optimized resume builder.

Your task is to parse a raw job description into a structured format.

RULES:
1. Extract the job title, company, location, seniority level, and department.
2. Identify ALL requirements — separate required vs. nice-to-have.
3. List ALL keywords and phrases a recruiter would search for in an ATS system.
4. Rate each keyword's importance as 'critical', 'high', 'medium', or 'low'.
5. Extract required skills vs. preferred skills separately.
6. Preserve exact JD terms, including slash terms such as PL/SQL, UI/UX, Java/Microservices, and iOS/Android.
7. Split slash terms into useful ATS terms while also preserving the exact original phrase.
8. Extract tools/platforms, programming languages, frameworks, databases, cloud/DevOps tools,
   domain/platform terms, deployment/environment terms, mobile/platform terms, soft skills,
   role responsibilities, and important exact phrases.
9. For OBDX roles, preserve OBDX, Oracle Banking Digital Experience, PL/SQL, Oracle DB,
   Java, Microservices, UI/UX, DevOps, Git, Jenkins, CEMLI/CEMLIs, Development Workbench,
   Extensibility, non-production environments, DEV, SIT, UAT, iOS, Android,
   Mobile App development, UK Open Banking, PSD2, and Open Banking APIs when present.
10. Clean job title labels such as "Designation:" and trailing colons from the title.
11. Identify required years of experience and education level.
12. Assess the JD quality:
   - 'strong': clear requirements, specific skills, measurable expectations
   - 'moderate': some ambiguity but workable
   - 'weak': vague, missing key info, or too generic
13. If quality is 'weak' or 'moderate', provide specific warnings about what's missing.
14. Return ONLY valid JSON matching the schema. Do not include explanations outside the JSON."""


async def analyze_jd(raw_text: str) -> ParsedJD:
    """
    Run the JD Analyzer step: raw text → structured ParsedJD.

    Args:
        raw_text: The raw job description text pasted by the user.

    Returns:
        ParsedJD with extracted requirements, keywords, and quality assessment.
    """
    client = get_gemini_client()

    prompt = f"""Analyze the following job description and extract structured information.

JOB DESCRIPTION:
---
{raw_text}
---

Extract job title, company, location, seniority, requirements (required vs nice-to-have),
responsibilities, ATS keywords with importance ratings, required/preferred skills,
tools/platforms, languages, frameworks, databases, cloud/DevOps tools, domain/platform terms,
deployment/environment terms, mobile/platform terms, soft skills, important exact phrases,
years of experience, education requirements, and quality assessment."""

    try:
        result = await client.generate_structured(
            prompt=prompt,
            response_model=ParsedJD,
            system_instruction=JD_ANALYSIS_SYSTEM_PROMPT,
        )
    except GeminiClientError as exc:
        logger.warning("Gemini JD analysis unavailable, using fallback parser: %s", exc)
        result = analyze_jd_without_ai(raw_text)

    result.raw_text = raw_text
    result = enrich_parsed_jd_for_ats(result, raw_text)

    logger.info(
        f"JD analyzed: title='{result.job_title}', "
        f"keywords={len(result.keywords)}, quality={result.quality}"
    )

    return result
