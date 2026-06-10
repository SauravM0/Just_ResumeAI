"""
Shared helpers for resume recommendation and regeneration use cases.

Owns the three helpers previously defined in the route layer:
  - require_generation   (lookup + parsed JD validation)
  - locked_bullets       (build locked-bullet map)
  - build_recommendation (AI call with fallback + alignment)
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.application.use_cases.parsed_jd_compat import normalize_saved_parsed_jd
from app.ai.gemini_client import GeminiClientError
from app.ai.orchestrators.resume_orchestrator import generate_recommendation
from app.ai.resume_fallback import generate_recommendation_without_ai
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.resume import (
    ResumeRecommendRequest,
    ResumeRecommendResponse,
    ResumeRecommendation,
    ResumeRegenerateRequest,
)
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.services.generation_service import GenerationNotFoundError
from app.services.jd_sanitization_service import (
    assert_parsed_jd_safe,
    assert_render_text_safe,
    assert_resume_recommendation_safe,
    recommendation_to_plain_text,
)

logger = logging.getLogger(__name__)


def require_generation(user_id: str, generation_id: str):
    """Look up a generation by owner, validate and return (generation, parsed_jd).

    Raises HTTPException(404) if not found, HTTPException(400) if missing JD.
    """
    try:
        generation = GenerationRepository().assert_owner(user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")
    if not generation.parsed_jd_json:
        raise HTTPException(status_code=400, detail="Parsed job description not found")
    parsed_jd = normalize_saved_parsed_jd(
        generation.parsed_jd_json,
        job_title=getattr(generation, "job_title", None),
        company=getattr(generation, "company", None),
        raw_text=getattr(generation, "raw_jd_text", None),
    )
    assert_parsed_jd_safe(parsed_jd)
    return generation, parsed_jd


def locked_bullets(
    recommendation: ResumeRecommendation | None,
    locked_ids: list[str],
) -> dict[str, str]:
    """Build a {bullet_id: text} map from a recommendation's locked bullet IDs."""
    if not recommendation:
        return {}
    locked: dict[str, str] = {}
    for entry in [*recommendation.experience, *recommendation.projects]:
        for bullet in entry.bullets:
            if bullet.id in locked_ids:
                locked[bullet.id] = bullet.text
    return locked


async def build_recommendation(
    *,
    request: ResumeRecommendRequest | ResumeRegenerateRequest,
    parsed_jd,
    current_draft: ResumeRecommendation | None = None,
) -> ResumeRecommendResponse:
    """Run AI recommendation (or fallback) and return the response with alignment report."""
    clean_profile = request.profile
    ats_plan = build_ats_keyword_plan(
        parsed_jd=parsed_jd,
        profile=clean_profile,
        emphasis=request.emphasis,
        target_pages=1,
        current_draft=current_draft,
    )
    locked = locked_bullets(
        current_draft,
        getattr(request, "locked_bullet_ids", []),
    )

    fallback_used = False
    try:
        recommendation = await generate_recommendation(
            profile=clean_profile,
            parsed_jd=parsed_jd,
            generation_id=request.generation_id,
            emphasis=request.emphasis,
            rejected_ids=request.rejected_item_ids,
            locked_bullets=locked,
            additional_alignment_text=request.additional_alignment_text,
            ats_plan=ats_plan,
        )
    except GeminiClientError as exc:
        logger.warning("Resume generation AI unavailable, using fallback: %s", exc)
        fallback_used = True
        recommendation = generate_recommendation_without_ai(
            profile=clean_profile,
            parsed_jd=parsed_jd,
            generation_id=request.generation_id,
            emphasis=request.emphasis,
            rejected_ids=request.rejected_item_ids,
            locked_bullets=locked,
            additional_alignment_text=request.additional_alignment_text,
            ats_plan=ats_plan,
        )

    if fallback_used:
        recommendation.warnings.append(
            "AI resume generation was temporarily unavailable. "
            "A rule-based fallback was used instead. Review the output carefully "
            "and consider regenerating if the AI service is available."
        )

    assert_resume_recommendation_safe(recommendation)
    assert_render_text_safe(
        recommendation_to_plain_text(recommendation),
        artifact="recommendation_plain_text",
    )
    alignment_report = build_ats_alignment_report(parsed_jd, recommendation, ats_plan=ats_plan)
    return ResumeRecommendResponse(recommendation=recommendation, alignment_report=alignment_report)
