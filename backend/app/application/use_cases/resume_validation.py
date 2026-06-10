"""
Validate resume use case: run ATS validation scoring against the generation's parsed JD.

Owns the orchestration that was previously in the POST /resume/validate route body.
"""

from __future__ import annotations

import logging

from app.application.use_cases.resume_common import require_generation
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.resume import ResumeValidateRequest
from app.schemas.scoring import ValidateResponse
from app.schemas.supabase import ResumeGenerationUpdate
from app.services.resume_validation_gate import (
    build_validation_status,
    validate_resume_for_draft,
)
from app.services.scoring_service import compute_ats_score

logger = logging.getLogger(__name__)


async def validate_resume(
    request: ResumeValidateRequest,
    user_id: str,
) -> ValidateResponse:
    """Run ATS validation scoring against the generation's parsed JD."""
    _, parsed_jd = require_generation(user_id, request.generation_id)
    validation = validate_resume_for_draft(request.recommendation, parsed_jd=parsed_jd)

    from app.services.profile_extraction_service import get_profile_by_user_id

    profile = get_profile_by_user_id(user_id)
    ats_score = compute_ats_score(
        validation.recommendation,
        parsed_jd,
        profile=profile,
        version_id=validation.recommendation.version_id,
    )

    GenerationRepository().update(
        user_id=user_id,
        generation_id=request.generation_id,
        data=ResumeGenerationUpdate(
            ats_score_json=ats_score.model_dump(),
            last_validated_version_id=validation.recommendation.version_id,
        ),
    )
    return ValidateResponse(
        generation_id=request.generation_id,
        ats_score=ats_score,
        validation_status=build_validation_status(
            validation,
            additional_warnings=ats_score.warnings,
            additional_user_actions=[
                "Edit the resume to address critical keyword gaps."
                if ats_score.missing_keywords
                else None,
            ],
        ),
    )
