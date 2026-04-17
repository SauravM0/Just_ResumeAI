"""
Resume endpoints — recommend, regenerate, validate, render-latex, render-pdf.

These endpoints manage the full resume generation and rendering pipeline.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import logging

from app.schemas.resume import (
    ResumeRecommendRequest,
    ResumeRecommendResponse,
    ResumeRegenerateRequest,
    ResumeValidateRequest,
    ResumeRenderLatexRequest,
    ResumeRenderLatexResponse,
    ResumeRenderPdfRequest,
    ResumeRenderPdfResponse,
)
from app.schemas.scoring import ValidateResponse
from app.ai.orchestrators.resume_orchestrator import generate_recommendation
from app.ai.gemini_client import GeminiClientError
from app.services.session_service import get_session
from app.services.scoring_service import compute_ats_score
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import compile_pdf, PDFCompileError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resume", tags=["resume"])


def _require_session_parsed_jd(session_id: str):
    """Load the authoritative parsed JD from session or raise a 4xx error."""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if not session.parsed_jd:
        raise HTTPException(status_code=400, detail="Parsed JD not found in session")
    return session, session.parsed_jd


@router.post("/recommend", response_model=ResumeRecommendResponse)
async def recommend_resume(request: ResumeRecommendRequest):
    """
    Generate a resume recommendation from profile + parsed JD.

    This runs the multi-step AI pipeline:
    1. Relevance matching
    2. Resume composition
    3. Deterministic rule enforcement

    Returns a recommendation for human review.
    """
    session, parsed_jd = _require_session_parsed_jd(request.session_id)

    try:
        recommendation = await generate_recommendation(
            profile=request.profile,
            parsed_jd=parsed_jd,
            session_id=request.session_id,
            emphasis=request.emphasis,
            rejected_ids=request.rejected_item_ids,
        )

        # Store in session
        session.recommendation = recommendation

        return ResumeRecommendResponse(recommendation=recommendation)

    except GeminiClientError as e:
        logger.error(f"Resume recommendation failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI generation failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in recommendation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/regenerate", response_model=ResumeRecommendResponse)
async def regenerate_resume(request: ResumeRegenerateRequest):
    """
    Regenerate resume with updated preferences (emphasis, locked bullets, rejected items).
    Same pipeline as recommend, but with user constraints applied.
    """
    session, parsed_jd = _require_session_parsed_jd(request.session_id)

    try:
        # Build locked bullets map from IDs
        locked_bullets = {}
        if session.recommendation:
            for exp in session.recommendation.experience:
                for b in exp.bullets:
                    if b.id in request.locked_bullet_ids:
                        locked_bullets[b.id] = b.text
            for proj in session.recommendation.projects:
                for b in proj.bullets:
                    if b.id in request.locked_bullet_ids:
                        locked_bullets[b.id] = b.text

        recommendation = await generate_recommendation(
            profile=request.profile,
            parsed_jd=parsed_jd,
            session_id=request.session_id,
            emphasis=request.emphasis,
            rejected_ids=request.rejected_item_ids,
            locked_bullets=locked_bullets,
        )

        session.recommendation = recommendation
        return ResumeRecommendResponse(recommendation=recommendation)

    except GeminiClientError as e:
        logger.error(f"Resume regeneration failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI generation failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in regeneration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/validate", response_model=ValidateResponse)
async def validate_resume(request: ResumeValidateRequest):
    """
    Run ATS validation scoring on the reviewed resume.
    Returns keyword coverage, readability score, and actionable recommendations.
    """
    _, parsed_jd = _require_session_parsed_jd(request.session_id)

    ats_score = compute_ats_score(request.recommendation, parsed_jd)

    return ValidateResponse(
        session_id=request.session_id,
        ats_score=ats_score,
    )


@router.post("/render-latex", response_model=ResumeRenderLatexResponse)
async def render_resume_latex(request: ResumeRenderLatexRequest):
    """
    Render the reviewed resume recommendation into LaTeX source code.
    """
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        latex_source = render_latex(request.recommendation)
        session.latex_source = latex_source

        return ResumeRenderLatexResponse(
            latex_source=latex_source,
            warnings=[],
        )
    except Exception as e:
        logger.error(f"LaTeX rendering failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"LaTeX rendering failed: {str(e)}")


@router.post("/render-pdf", response_model=ResumeRenderPdfResponse)
async def render_resume_pdf(request: ResumeRenderPdfRequest):
    """
    Compile LaTeX source into a downloadable PDF.
    """
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        pdf_path, warnings = await compile_pdf(
            latex_source=request.latex_source,
            session_id=request.session_id,
        )

        # Generate download URL (served as static file)
        pdf_filename = pdf_path.split("/")[-1].split("\\")[-1]
        pdf_url = f"/api/v1/resume/download/{pdf_filename}"

        return ResumeRenderPdfResponse(
            pdf_url=pdf_url,
            compile_success=True,
            compile_errors=[],
            compile_warnings=warnings,
        )

    except PDFCompileError as e:
        return ResumeRenderPdfResponse(
            pdf_url="",
            compile_success=False,
            compile_errors=e.errors,
            compile_warnings=[],
        )
    except Exception as e:
        logger.error(f"PDF compilation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF compilation failed: {str(e)}")


@router.get("/download/{filename}")
async def download_pdf(filename: str):
    """Serve a compiled PDF for download."""
    from pathlib import Path
    from app.config import get_settings

    settings = get_settings()
    pdf_path = Path(settings.LATEX_OUTPUT_DIR) / filename

    if not pdf_path.exists() or not pdf_path.suffix == ".pdf":
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )
