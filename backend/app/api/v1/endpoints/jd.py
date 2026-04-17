"""
JD analysis endpoint — POST /api/v1/jd/analyze

Accepts raw job description text, runs the Gemini JD Analyzer,
returns structured ParsedJD with quality assessment.
"""

from fastapi import APIRouter, HTTPException
import logging

from app.schemas.jd import JDAnalyzeRequest, JDAnalyzeResponse
from app.ai.orchestrators.jd_orchestrator import analyze_jd
from app.ai.gemini_client import GeminiClientError
from app.services.session_service import create_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jd", tags=["job-description"])


@router.post("/analyze", response_model=JDAnalyzeResponse)
async def analyze_job_description(request: JDAnalyzeRequest):
    """
    Analyze a raw job description and return structured data.

    Creates a new session for this analysis flow.
    The session_id should be passed to subsequent resume endpoints.
    """
    try:
        # Create session for this flow
        session = create_session()

        # Run JD analysis
        parsed_jd = await analyze_jd(request.raw_jd_text)

        # Store in session
        session.parsed_jd = parsed_jd

        # Collect warnings
        warnings = list(parsed_jd.quality_warnings)
        if parsed_jd.quality.value == "weak":
            warnings.insert(0, "⚠️ This job description is vague. Results may be less targeted.")

        return JDAnalyzeResponse(
            session_id=session.session_id,
            parsed_jd=parsed_jd,
            warnings=warnings,
        )

    except GeminiClientError as e:
        logger.error(f"JD analysis failed: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error in JD analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
