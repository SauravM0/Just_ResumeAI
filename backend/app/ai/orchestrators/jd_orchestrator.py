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
from app.services.jd_sanitization_service import (
    assert_parsed_jd_safe,
    require_valid_jd_text,
    sanitize_parsed_jd,
)

logger = logging.getLogger(__name__)

JD_ANALYSIS_SYSTEM_PROMPT = """You are an expert job description analyzer for an ATS-optimized resume builder.

Your task is to parse a raw job description into a high-fidelity structured format.

RULES:
1. Extract basic info: job title, company, location, seniority level, department.
2. Identify ALL core requirements. For each requirement, create a structured object:
   - 'text': The requirement phrase (e.g., "5+ years of Java experience").
   - 'priority': 
      - 'must-have' if the JD uses words like "required", "must", "mandatory", "minimum", or lists it in a core requirements section.
      - 'should-have' for important but not strictly mandatory items.
      - 'nice-to-have' if the JD uses "preferred", "plus", "bonus", "advantage", or "desired".
   - 'category': One of 'technical_skill', 'soft_skill', 'experience', 'education', 'domain_knowledge'.
   - 'suggested_placement': Array containing one or more of 'summary', 'skills', 'experience', 'projects', 'education', 'achievements'.
   - 'synonyms': Array of common alternative names (e.g., for "React", add ["React.js", "ReactJS"]).
3. List ALL keywords recruiter would search for. Rate importance: 'critical' (must-haves), 'high', 'medium', 'low'.
4. Separate required_skills and preferred_skills clearly.
5. Preserve and split slash terms (e.g., "PL/SQL", "Java/Microservices").
6. Group tech terms into the provided categories (languages, frameworks, etc.).
7. Clean the job title and accurately detect seniority (Intern, Entry, Mid, Senior, Lead, etc.).
8. Identify required years of experience and education.
9. Return ONLY valid JSON matching the schema. No conversational filler."""


async def analyze_jd(raw_text: str) -> ParsedJD:
    """
    Run the JD Analyzer step: raw text → structured ParsedJD.

    Args:
        raw_text: The raw job description text pasted by the user.

    Returns:
        ParsedJD with extracted requirements, keywords, and quality assessment.
    """
    sanitization = require_valid_jd_text(raw_text)
    clean_text = sanitization.clean_text
    client = get_gemini_client()

    prompt = f"""Analyze the following job description and extract structured information.

JOB DESCRIPTION:
---
{clean_text}
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
        result = analyze_jd_without_ai(clean_text)

    result.raw_text = clean_text
    result = enrich_parsed_jd_for_ats(result, clean_text)
    result = sanitize_parsed_jd(result, source_text=clean_text, sanitization=sanitization)
    assert_parsed_jd_safe(result)

    logger.info(
        f"JD analyzed: title='{result.job_title}', "
        f"keywords={len(result.keywords)}, quality={result.quality}"
    )

    return result
