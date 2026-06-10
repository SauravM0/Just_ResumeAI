"""
JD analysis endpoint — POST /api/v1/jd/analyze

Accepts raw job description text, runs the Gemini JD Analyzer,
returns structured ParsedJD with quality assessment.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
import logging

from app.schemas.jd import JDAnalyzeRequest, JDAnalyzeResponse
from app.schemas.validation import ValidationSeverity, ValidationStatus
from app.ai.orchestrators.jd_orchestrator import analyze_jd
from app.ai.gemini_client import GeminiClientError
from app.dependencies.auth import get_current_user_id
from app.main import limiter
from app.services.generation_service import create_generation
from app.services.jd_sanitization_service import (
    INVALID_JD_USER_MESSAGE,
    InvalidJobDescriptionError,
    assert_parsed_jd_safe,
    require_valid_jd_text,
    sanitize_parsed_jd,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jd", tags=["job-description"])


@router.post("/analyze", response_model=JDAnalyzeResponse)
@limiter.limit("15/hour")
async def analyze_job_description(
    request: Request,
    body: JDAnalyzeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Analyze a raw job description and return structured data.

    Creates a Supabase generation for this analysis flow.
    The returned generation_id is the durable Supabase identity for the flow.
    """
    MAX_JD_LENGTH = 15_000
    raw_jd_text = body.raw_jd_text
    if len(raw_jd_text) > MAX_JD_LENGTH:
        raw_jd_text = raw_jd_text[:MAX_JD_LENGTH]
        logger.warning("JD text truncated to %d chars for analysis", MAX_JD_LENGTH)

    MIN_JD_LENGTH = 50
    if not raw_jd_text or len(raw_jd_text.strip()) < MIN_JD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Job description is too short ({len(raw_jd_text or '')} characters). "
                   f"Please provide at least {MIN_JD_LENGTH} characters for meaningful analysis.",
        )

    try:
        sanitization = require_valid_jd_text(raw_jd_text)
    except InvalidJobDescriptionError as exc:
        raise HTTPException(status_code=422, detail=INVALID_JD_USER_MESSAGE) from exc

    clean_jd_text = sanitization.clean_text
    if len(clean_jd_text.strip()) < MIN_JD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Job description is too short after cleanup ({len(clean_jd_text.strip())} characters). "
                f"Please provide at least {MIN_JD_LENGTH} characters of role-specific content."
            ),
        )

    try:
        parsed_jd = sanitize_parsed_jd(
            await analyze_jd(clean_jd_text),
            source_text=clean_jd_text,
            sanitization=sanitization,
        )
        assert_parsed_jd_safe(parsed_jd)
        generation = create_generation(
            user_id=user_id,
            raw_jd_text=raw_jd_text,
            initial_data={
                "parsed_jd_json": parsed_jd.model_dump(),
                "job_title": parsed_jd.job_title,
                "company": parsed_jd.company,
            },
        )

        # Collect warnings
        warnings = list(sanitization.warnings) + list(parsed_jd.quality_warnings)
        if parsed_jd.quality.value == "weak":
            warnings.insert(0, "⚠️ This job description is vague. Results may be less targeted.")

        # Build standard validation status
        blocked_reasons: list[str] = []
        user_actions: list[str] = []
        repair_actions: list[str] = []
        if parsed_jd.quality.value == "weak":
            user_actions.append("Paste a more detailed job description for better results.")
        if sanitization.warnings:
            for sw in sanitization.warnings:
                repair_actions.append(sw)

        if blocked_reasons:
            severity = ValidationSeverity.BLOCKED
        elif warnings:
            severity = ValidationSeverity.WARNING
        else:
            severity = ValidationSeverity.PASS

        validation_status = ValidationStatus(
            export_ready=True,
            severity=severity,
            blocked_reasons=blocked_reasons,
            warnings=warnings,
            repair_actions=repair_actions,
            user_actions=user_actions,
        )

        return JDAnalyzeResponse(
            generation_id=str(generation.id),
            parsed_jd=parsed_jd,
            warnings=warnings,
            validation_status=validation_status,
        )

    except InvalidJobDescriptionError as exc:
        raise HTTPException(status_code=422, detail=INVALID_JD_USER_MESSAGE) from exc
    except GeminiClientError as e:
        logger.error("JD analysis failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"AI service is temporarily unavailable: {e}",
        )
    except Exception:
        logger.exception("JD analysis: unexpected error")
        raise HTTPException(status_code=500, detail="Job description analysis failed. Please retry.")
