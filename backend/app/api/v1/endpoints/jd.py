"""
JD analysis endpoint — POST /api/v1/jd/analyze

Accepts raw job description text, runs the Gemini JD Analyzer,
returns structured ParsedJD with quality assessment.
"""

from fastapi import APIRouter, Depends, HTTPException
import logging

from app.schemas.jd import JDAnalyzeRequest, JDAnalyzeResponse
from app.ai.orchestrators.jd_orchestrator import analyze_jd
from app.ai.gemini_client import GeminiClientError
from app.dependencies.auth import get_current_user_id
from app.services.generation_service import create_generation

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jd", tags=["job-description"])


@router.post("/analyze", response_model=JDAnalyzeResponse)
async def analyze_job_description(
    request: JDAnalyzeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Analyze a raw job description and return structured data.

    Creates a Supabase generation for this analysis flow.
    The returned generation_id is the durable Supabase identity for the flow.
    """
    MIN_JD_LENGTH = 50
    if not request.raw_jd_text or len(request.raw_jd_text.strip()) < MIN_JD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Job description is too short ({len(request.raw_jd_text or '')} characters). "
                   f"Please provide at least {MIN_JD_LENGTH} characters for meaningful analysis.",
        )

    try:
        parsed_jd = await analyze_jd(request.raw_jd_text)
        generation = create_generation(
            user_id=user_id,
            raw_jd_text=request.raw_jd_text,
            initial_data={
                "parsed_jd_json": parsed_jd.model_dump(),
                "job_title": parsed_jd.job_title,
                "company": parsed_jd.company,
            },
        )

        # Collect warnings
        warnings = list(parsed_jd.quality_warnings)
        if parsed_jd.quality.value == "weak":
            warnings.insert(0, "⚠️ This job description is vague. Results may be less targeted.")

        return JDAnalyzeResponse(
            generation_id=str(generation.id),
            parsed_jd=parsed_jd,
            warnings=warnings,
        )

    except GeminiClientError as e:
        logger.error("JD analysis failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"AI service is temporarily unavailable: {e}",
        )
    except Exception:
        logger.exception("JD analysis: unexpected error")
        raise HTTPException(status_code=500, detail="Job description analysis failed. Please retry.")
