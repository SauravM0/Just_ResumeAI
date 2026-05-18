"""
Resume endpoints backed by Supabase generations and Supabase Storage.
"""

from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.ai.gemini_client import GeminiClientError
from app.ai.orchestrators.resume_orchestrator import generate_recommendation
from app.ai.resume_fallback import generate_recommendation_without_ai
from app.dependencies.auth import get_current_user, get_current_user_id
from app.schemas.resume import (
    ResumeRecommendRequest,
    ResumeRecommendResponse,
    ResumeRecommendation,
    ResumeRegenerateRequest,
    ResumeValidateRequest,
)
from app.schemas.scoring import ValidateResponse
from app.schemas.supabase import ResumeGenerationUpdate
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.services.docx_export_service import export_resume_docx
from app.services.generation_service import assert_generation_owner, get_generation, update_generation
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import PDFCompileError, compile_pdf
from app.services.resume_budget_service import fit_resume_to_page_budget
from app.services.scoring_service import compute_ats_score
from app.services.storage_service import summarize_generation_files
from app.services.supabase_service import get_supabase_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resume", tags=["resume"])


def _require_generation(user_id: str, generation_id: str):
    generation = get_generation(user_id, generation_id)
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found")
    if not generation.parsed_jd_json:
        raise HTTPException(status_code=400, detail="Parsed job description not found")
    return generation, generation.parsed_jd_json


def _locked_bullets(recommendation: ResumeRecommendation | None, locked_ids: list[str]) -> dict[str, str]:
    if not recommendation:
        return {}

    locked = {}
    for entry in [*recommendation.experience, *recommendation.projects]:
        for bullet in entry.bullets:
            if bullet.id in locked_ids:
                locked[bullet.id] = bullet.text
    return locked


def _fit_for_export(parsed_jd, recommendation: ResumeRecommendation) -> ResumeRecommendation:
    return fit_resume_to_page_budget(
        recommendation=recommendation,
        parsed_jd=parsed_jd,
        target_pages=1,
    )


def _remove_local_file(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove local generated file after failed upload: %s", path)


def _download_response(
    path: str,
    *,
    generation_id: str,
    file_type: Literal["pdf", "docx"],
) -> FileResponse:
    media_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    filename = f"resume-{generation_id}.{file_type}"
    return FileResponse(
        path=path,
        media_type=media_types[file_type],
        filename=filename,
        background=BackgroundTask(_remove_local_file, path),
    )


def _require_saved_export_data(gen) -> ResumeRecommendation:
    if not gen.resume_json or not gen.parsed_jd_json:
        raise HTTPException(status_code=400, detail="No saved resume data found for this generation")
    from app.schemas.jd import ParsedJD
    parsed_jd = ParsedJD.model_validate(gen.parsed_jd_json)
    return _fit_for_export(parsed_jd, ResumeRecommendation(**gen.resume_json))


async def _export_saved_pdf(
    user_id: str,
    generation_id: str,
    gen,
    *,
    regenerated: bool = False,
) -> FileResponse:
    recommendation = _require_saved_export_data(gen)
    latex_source = render_latex(recommendation)
    try:
        pdf_path, compile_warnings = await compile_pdf(
            latex_source=latex_source,
            generation_id=generation_id,
        )
    except PDFCompileError as exc:
        raise HTTPException(status_code=422, detail=exc.response_errors()) from exc

    _log_export(user_id, generation_id, "pdf_export", {"compile_success": True, "regenerated": regenerated})
    response = _download_response(pdf_path, generation_id=generation_id, file_type="pdf")
    if compile_warnings:
        response.headers["X-Compile-Warnings"] = json.dumps(compile_warnings)
    response.headers["X-Regenerated"] = "true" if regenerated else "false"
    return response


def _export_saved_docx(
    user_id: str,
    generation_id: str,
    gen,
    *,
    regenerated: bool = False,
) -> FileResponse:
    recommendation = _require_saved_export_data(gen)
    docx_path = export_resume_docx(recommendation, generation_id)

    _log_export(user_id, generation_id, "docx_export", {"regenerated": regenerated})
    response = _download_response(docx_path, generation_id=generation_id, file_type="docx")
    response.headers["X-Regenerated"] = "true" if regenerated else "false"
    return response


async def _build_recommendation(
    *,
    request: ResumeRecommendRequest | ResumeRegenerateRequest,
    parsed_jd,
    current_draft: ResumeRecommendation | None = None,
) -> ResumeRecommendResponse:
    clean_profile = request.profile
    ats_plan = build_ats_keyword_plan(
        parsed_jd=parsed_jd,
        profile=clean_profile,
        emphasis=request.emphasis,
        target_pages=1,
        current_draft=current_draft,
    )
    locked_bullets = _locked_bullets(
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
            locked_bullets=locked_bullets,
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
            locked_bullets=locked_bullets,
            additional_alignment_text=request.additional_alignment_text,
            ats_plan=ats_plan,
        )

    if fallback_used:
        recommendation.warnings.append(
            "AI resume generation was temporarily unavailable. "
            "A rule-based fallback was used instead. Review the output carefully "
            "and consider regenerating if the AI service is available."
        )

    alignment_report = build_ats_alignment_report(parsed_jd, recommendation, ats_plan=ats_plan)
    return ResumeRecommendResponse(recommendation=recommendation, alignment_report=alignment_report)


@router.post("/recommend", response_model=ResumeRecommendResponse)
async def recommend_resume(
    request: ResumeRecommendRequest,
    current_user=Depends(get_current_user),
):
    """Generate a resume recommendation for an existing Supabase generation."""
    generation, parsed_jd = _require_generation(current_user.user_id, request.generation_id)

    result = await _build_recommendation(request=request, parsed_jd=parsed_jd)
    update_generation(
        user_id=current_user.user_id,
        generation_id=request.generation_id,
        update_data=ResumeGenerationUpdate(
            resume_json=result.recommendation.model_dump(),
            alignment_report_json=result.alignment_report.model_dump() if result.alignment_report else None,
            status="draft",
        ),
    )
    return result


@router.post("/regenerate", response_model=ResumeRecommendResponse)
async def regenerate_resume(
    request: ResumeRegenerateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Regenerate a saved resume using the Supabase generation as source of truth."""
    generation, parsed_jd = _require_generation(user_id, request.generation_id)
    current_draft = ResumeRecommendation(**generation.resume_json) if generation.resume_json else None

    result = await _build_recommendation(
        request=request,
        parsed_jd=parsed_jd,
        current_draft=current_draft,
    )
    update_generation(
        user_id=user_id,
        generation_id=request.generation_id,
        update_data=ResumeGenerationUpdate(
            resume_json=result.recommendation.model_dump(),
            alignment_report_json=result.alignment_report.model_dump() if result.alignment_report else None,
            status="draft",
        ),
    )
    return result


@router.post("/validate", response_model=ValidateResponse)
async def validate_resume(
    request: ResumeValidateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Run ATS validation scoring against the generation's parsed JD."""
    _, parsed_jd = _require_generation(user_id, request.generation_id)
    ats_score = compute_ats_score(request.recommendation, parsed_jd)

    update_generation(
        user_id=user_id,
        generation_id=request.generation_id,
        update_data=ResumeGenerationUpdate(ats_score_json=ats_score.model_dump()),
    )
    return ValidateResponse(generation_id=request.generation_id, ats_score=ats_score)


@router.post("/{generation_id}/export/pdf")
async def export_resume_pdf(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """Export the saved resume as a PDF download without storing the file."""
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Generation not found")

    return await _export_saved_pdf(str(current_user.user_id), generation_id, gen)


@router.post("/{generation_id}/export/docx")
async def export_resume_docx_endpoint(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """Export the saved resume as a DOCX download without storing the file."""
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Generation not found")

    return _export_saved_docx(str(current_user.user_id), generation_id, gen)


@router.post("/{generation_id}/files/{file_type}/regenerate")
async def regenerate_generation_file(
    generation_id: str,
    file_type: Literal["pdf", "docx"],
    current_user=Depends(get_current_user),
):
    """Generate a fresh export from saved resume_json and return it as a download."""
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Generation not found")

    if file_type == "pdf":
        return await _export_saved_pdf(str(current_user.user_id), generation_id, gen, regenerated=True)
    return _export_saved_docx(str(current_user.user_id), generation_id, gen, regenerated=True)


@router.get("/{generation_id}/files")
async def list_generation_files(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """Return empty file metadata; exports are direct downloads and are not stored."""
    try:
        assert_generation_owner(current_user.user_id, generation_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Generation not found")

    files = []
    return {
        "generation_id": generation_id,
        **summarize_generation_files(files),
        "files": files,
    }


def _log_export(user_id: str, generation_id: str, event_type: str, metadata: dict) -> None:
    try:
        get_supabase_service().log_usage_event(
            user_id=str(user_id),
            event_type=event_type,
            generation_id=generation_id,
            metadata=metadata,
        )
    except Exception:
        logger.warning("Failed to log %s usage event", event_type)
