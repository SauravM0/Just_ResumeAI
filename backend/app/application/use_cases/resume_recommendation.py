"""
Recommend resume use case: generate an initial recommendation from a Supabase generation.

Delegates the AI orchestration to resume_common.build_recommendation and
persists the result via GenerationRepository.
"""

from __future__ import annotations

import logging

from app.application.use_cases.resume_common import build_recommendation, require_generation
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.resume import ResumeRecommendRequest, ResumeRecommendResponse
from app.schemas.supabase import ResumeGenerationUpdate

logger = logging.getLogger(__name__)


async def recommend_resume(
    request: ResumeRecommendRequest,
    user_id: str,
) -> ResumeRecommendResponse:
    """Generate a resume recommendation for an existing Supabase generation."""
    generation, parsed_jd = require_generation(user_id, request.generation_id)

    result = await build_recommendation(request=request, parsed_jd=parsed_jd)
    GenerationRepository().update(
        user_id=user_id,
        generation_id=request.generation_id,
        data=ResumeGenerationUpdate(
            resume_json=result.recommendation.model_dump(),
            alignment_report_json=result.alignment_report.model_dump() if result.alignment_report else None,
            status="draft",
        ),
    )
    return result
