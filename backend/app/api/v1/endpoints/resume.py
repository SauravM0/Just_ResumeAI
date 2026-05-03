"""
Resume endpoints — recommend, regenerate, validate, render-latex, render-pdf.

These endpoints manage the full resume generation and rendering pipeline.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
import logging
import re
from pathlib import Path

from app.config import get_settings
from app.dependencies.user import get_current_user_id
from app.schemas.resume import (
    ResumeRecommendRequest,
    ResumeRecommendResponse,
    ResumeRegenerateRequest,
    ResumeValidateRequest,
    ResumeApproveGeneratePdfRequest,
    ResumeApproveGeneratePdfResponse,
    ResumeRenderLatexRequest,
    ResumeRenderLatexResponse,
    ResumeRenderPdfRequest,
    ResumeRenderPdfResponse,
)
from app.schemas.scoring import ValidateResponse
from app.ai.resume_fallback import generate_recommendation_without_ai
from app.ai.orchestrators.resume_orchestrator import generate_recommendation
from app.ai.gemini_client import GeminiClientError
from app.services.session_service import get_session, save_session
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.services.scoring_service import compute_ats_score
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import compile_pdf, PDFCompileError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resume", tags=["resume"])

_SAFE_PDF_FILENAME_RE = re.compile(r"^resume_[a-f0-9]{32}_[a-f0-9]{6}\.pdf$")


class LaTeXRenderError(Exception):
    """Compatibility error type for renderers that return structured LaTeX errors."""

    def __init__(self, errors: list[str]):
        super().__init__("LaTeX rendering failed")
        self.errors = errors


def _require_session_parsed_jd(session_id: str, user_id: str):
    """Load the authoritative parsed JD from session or raise a 4xx error."""
    session = get_session(session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if not session.parsed_jd:
        raise HTTPException(status_code=400, detail="Parsed JD not found in session")
    return session, session.parsed_jd


def _safe_tex_reference(path: str | None) -> str | None:
    if not path:
        return None
    settings = get_settings()
    if settings.DEBUG:
        return path
    return Path(path).name


def _compile_failure_response(
    exc: PDFCompileError,
    latex_source: str = "",
) -> dict:
    logger.error(
        "PDF compilation failed. tex=%s line=%s errors=%s warnings=%s excerpt=%s raw=%s",
        exc.generated_tex_path,
        exc.line_number,
        exc.errors,
        exc.warnings,
        exc.pdflatex_excerpt,
        (exc.raw_output or "")[-4000:],
    )
    return {
        "latex_source": latex_source,
        "pdf_url": "",
        "compile_success": False,
        "compile_errors": exc.response_errors(),
        "compile_warnings": exc.warnings,
        "generated_tex_path": _safe_tex_reference(exc.generated_tex_path),
        "pdflatex_excerpt": exc.pdflatex_excerpt,
        "line_number": exc.line_number,
    }


@router.post("/recommend", response_model=ResumeRecommendResponse)
async def recommend_resume(
    request: ResumeRecommendRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Generate a resume recommendation from profile + parsed JD.

    This runs the multi-step AI pipeline:
    1. Relevance matching
    2. Resume composition
    3. Deterministic rule enforcement

    Returns a recommendation for human review.
    """
    session, parsed_jd = _require_session_parsed_jd(request.session_id, user_id)
    clean_profile = request.profile
    ats_plan = build_ats_keyword_plan(
        parsed_jd=parsed_jd,
        profile=clean_profile,
        emphasis=request.emphasis,
        target_pages=1,
    )
    try:
        recommendation = await generate_recommendation(
            profile=clean_profile,
            parsed_jd=parsed_jd,
            session_id=request.session_id,
            emphasis=request.emphasis,
            rejected_ids=request.rejected_item_ids,
            additional_alignment_text=request.additional_alignment_text,
            ats_plan=ats_plan,
        )
        alignment_report = build_ats_alignment_report(parsed_jd, recommendation)

        # Store in session
        session.recommendation = recommendation
        session.rejected_ids = list(request.rejected_item_ids)
        save_session(session)

        return ResumeRecommendResponse(recommendation=recommendation, alignment_report=alignment_report)

    except GeminiClientError as e:
        logger.warning(f"Resume recommendation AI path failed, using fallback: {e}")
        recommendation = generate_recommendation_without_ai(
            profile=clean_profile,
            parsed_jd=parsed_jd,
            session_id=request.session_id,
            emphasis=request.emphasis,
            rejected_ids=request.rejected_item_ids,
            additional_alignment_text=request.additional_alignment_text,
            ats_plan=ats_plan,
        )
        alignment_report = build_ats_alignment_report(parsed_jd, recommendation)
        session.recommendation = recommendation
        session.rejected_ids = list(request.rejected_item_ids)
        save_session(session)
        return ResumeRecommendResponse(recommendation=recommendation, alignment_report=alignment_report)
    except Exception as e:
        logger.error(f"Unexpected error in recommendation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/regenerate", response_model=ResumeRecommendResponse)
async def regenerate_resume(
    request: ResumeRegenerateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Regenerate resume with updated preferences (emphasis, locked bullets, rejected items).
    Same pipeline as recommend, but with user constraints applied.
    """
    session, parsed_jd = _require_session_parsed_jd(request.session_id, user_id)
    clean_profile = request.profile
    ats_plan = build_ats_keyword_plan(
        parsed_jd=parsed_jd,
        profile=clean_profile,
        emphasis=request.emphasis,
        target_pages=1,
        current_draft=session.recommendation,
    )
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
            profile=clean_profile,
            parsed_jd=parsed_jd,
            session_id=request.session_id,
            emphasis=request.emphasis,
            rejected_ids=request.rejected_item_ids,
            locked_bullets=locked_bullets,
            additional_alignment_text=request.additional_alignment_text,
            ats_plan=ats_plan,
        )
        alignment_report = build_ats_alignment_report(parsed_jd, recommendation)

        session.recommendation = recommendation
        session.rejected_ids = list(request.rejected_item_ids)
        save_session(session)
        return ResumeRecommendResponse(recommendation=recommendation, alignment_report=alignment_report)

    except GeminiClientError as e:
        logger.warning(f"Resume regeneration AI path failed, using fallback: {e}")
        recommendation = generate_recommendation_without_ai(
            profile=clean_profile,
            parsed_jd=parsed_jd,
            session_id=request.session_id,
            emphasis=request.emphasis,
            rejected_ids=request.rejected_item_ids,
            locked_bullets=locked_bullets,
            additional_alignment_text=request.additional_alignment_text,
            ats_plan=ats_plan,
        )
        alignment_report = build_ats_alignment_report(parsed_jd, recommendation)
        session.recommendation = recommendation
        session.rejected_ids = list(request.rejected_item_ids)
        save_session(session)
        return ResumeRecommendResponse(recommendation=recommendation, alignment_report=alignment_report)
    except Exception as e:
        logger.error(f"Unexpected error in regeneration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/validate", response_model=ValidateResponse)
async def validate_resume(
    request: ResumeValidateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Run ATS validation scoring on the reviewed resume.
    Returns keyword coverage, readability score, and actionable recommendations.
    """
    _, parsed_jd = _require_session_parsed_jd(request.session_id, user_id)

    ats_score = compute_ats_score(request.recommendation, parsed_jd)

    return ValidateResponse(
        session_id=request.session_id,
        ats_score=ats_score,
    )


@router.post("/approve-generate-pdf", response_model=ResumeApproveGeneratePdfResponse)
async def approve_generate_pdf(
    request: ResumeApproveGeneratePdfRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Approve the reviewed recommendation, render LaTeX, compile PDF, and persist outputs.
    This is the primary MVP action behind "Approve & Generate PDF".
    """
    session = get_session(request.session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        latex_source = render_latex(request.recommendation)
        session.recommendation = request.recommendation
        session.latex_source = latex_source
        save_session(session)

        pdf_path, warnings = await compile_pdf(
            latex_source=latex_source,
            session_id=request.session_id,
        )
        pdf_filename = pdf_path.split("/")[-1].split("\\")[-1]
        session.pdf_filename = pdf_filename
        save_session(session)

        return ResumeApproveGeneratePdfResponse(
            latex_source=latex_source,
            pdf_url=f"/api/v1/resume/download/{pdf_filename}",
            compile_success=True,
            compile_errors=[],
            compile_warnings=warnings,
        )

    except LaTeXRenderError as e:
        return ResumeApproveGeneratePdfResponse(
            latex_source="",
            pdf_url="",
            compile_success=False,
            compile_errors=e.errors,
            compile_warnings=[],
        )
    except PDFCompileError as e:
        return ResumeApproveGeneratePdfResponse(**_compile_failure_response(e, session.latex_source or ""))
    except Exception as e:
        logger.error("Approve and generate PDF failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="PDF generation failed. Please retry.")


@router.post("/render-latex", response_model=ResumeRenderLatexResponse)
async def render_resume_latex(
    request: ResumeRenderLatexRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Render the reviewed resume recommendation into LaTeX source code.
    """
    session = get_session(request.session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        latex_source = render_latex(request.recommendation)
        session.latex_source = latex_source
        save_session(session)

        return ResumeRenderLatexResponse(
            latex_source=latex_source,
            warnings=[],
        )
    except Exception as e:
        logger.error(f"LaTeX rendering failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"LaTeX rendering failed: {str(e)}")


@router.post("/render-pdf", response_model=ResumeRenderPdfResponse)
async def render_resume_pdf(
    request: ResumeRenderPdfRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Compile LaTeX source into a downloadable PDF.
    """
    session = get_session(request.session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    if not session.latex_source:
        raise HTTPException(
            status_code=400,
            detail="No rendered LaTeX found in session. Call /render-latex first.",
        )

    try:
        pdf_path, warnings = await compile_pdf(
            latex_source=session.latex_source,
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
        payload = _compile_failure_response(e, "")
        payload.pop("latex_source", None)
        return ResumeRenderPdfResponse(**payload)
    except Exception as e:
        logger.error(f"PDF compilation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"PDF compilation failed: {str(e)}")


@router.get("/download/{filename}")
async def download_pdf(filename: str):
    """Serve a compiled PDF for download."""
    if not _SAFE_PDF_FILENAME_RE.match(filename):
        raise HTTPException(status_code=404, detail="PDF not found")

    settings = get_settings()
    output_dir = Path(settings.LATEX_OUTPUT_DIR).resolve()
    pdf_path = (output_dir / filename).resolve()

    if output_dir not in pdf_path.parents:
        raise HTTPException(status_code=404, detail="PDF not found")

    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF not found")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )
