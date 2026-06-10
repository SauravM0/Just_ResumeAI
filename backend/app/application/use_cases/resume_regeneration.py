"""
Regenerate resume use case: re-run recommendation using saved state.

Loads the current draft from the generation record, then delegates to
resume_common.build_recommendation and persists the result.
"""

from __future__ import annotations

import logging

from app.application.use_cases.resume_common import build_recommendation, require_generation
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.resume import ResumeRecommendation, ResumeRecommendResponse, ResumeRegenerateRequest
from app.schemas.supabase import ResumeGenerationUpdate

logger = logging.getLogger(__name__)


async def regenerate_resume(
    request: ResumeRegenerateRequest,
    user_id: str,
) -> ResumeRecommendResponse:
    """Regenerate a saved resume using the Supabase generation as source of truth."""
    generation, parsed_jd = require_generation(user_id, request.generation_id)
    current_draft = ResumeRecommendation(**generation.resume_json) if generation.resume_json else None

    result = await build_recommendation(
        request=request,
        parsed_jd=parsed_jd,
        current_draft=current_draft,
    )
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
