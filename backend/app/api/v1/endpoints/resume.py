"""
Resume endpoints backed by Supabase generations.

Export, recommendation, regeneration, and validation orchestration
is delegated to application-level use cases.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.application.use_cases.resume_export_docx import export_resume_docx_file as _run_docx_export
from app.application.use_cases.resume_export_pdf import export_resume_pdf as _run_pdf_export
from app.application.use_cases.resume_files import get_generation_file_metadata
from app.application.use_cases.resume_recommendation import recommend_resume as _run_recommend
from app.application.use_cases.resume_regeneration import regenerate_resume as _run_regenerate
from app.application.use_cases.resume_validation import validate_resume as _run_validate
from app.dependencies.auth import get_current_user, get_current_user_id
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.resume import (
    ResumeRecommendRequest,
    ResumeRecommendResponse,
    ResumeRegenerateRequest,
    ResumeValidateRequest,
)
from app.schemas.scoring import ValidateResponse
from app.services.generation_service import GenerationNotFoundError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resume", tags=["resume"])


@router.post("/recommend", response_model=ResumeRecommendResponse)
async def recommend_resume(
    request: ResumeRecommendRequest,
    current_user=Depends(get_current_user),
):
    """Generate a resume recommendation for an existing Supabase generation."""
    return await _run_recommend(request, current_user.user_id)


@router.post("/regenerate", response_model=ResumeRecommendResponse)
async def regenerate_resume(
    request: ResumeRegenerateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Regenerate a saved resume using the Supabase generation as source of truth."""
    return await _run_regenerate(request, user_id)


@router.post("/validate", response_model=ValidateResponse)
async def validate_resume(
    request: ResumeValidateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Run ATS validation scoring against the generation's parsed JD."""
    return await _run_validate(request, user_id)


# ── Export routes (delegated to use cases) ──────────────────────────────


@router.post("/{generation_id}/export/pdf")
async def export_resume_pdf(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """Export the saved resume as a PDF download without storing the file."""
    try:
        gen = GenerationRepository().assert_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")
    return await _run_pdf_export(str(current_user.user_id), generation_id, gen)


@router.post("/{generation_id}/export/docx")
async def export_resume_docx_endpoint(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """Export the saved resume as a DOCX download without storing the file."""
    try:
        gen = GenerationRepository().assert_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")
    return _run_docx_export(str(current_user.user_id), generation_id, gen)


@router.post("/{generation_id}/files/{file_type}/regenerate")
async def regenerate_generation_file(
    generation_id: str,
    file_type: Literal["pdf", "docx"],
    current_user=Depends(get_current_user),
):
    """Generate a fresh export from saved resume_json and return it as a download."""
    try:
        gen = GenerationRepository().assert_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")

    if file_type == "pdf":
        return await _run_pdf_export(str(current_user.user_id), generation_id, gen, regenerated=True)
    return _run_docx_export(str(current_user.user_id), generation_id, gen, regenerated=True)


@router.get("/{generation_id}/files")
async def list_generation_files(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """Return empty file metadata; exports are direct downloads and are not stored."""
    try:
        GenerationRepository().assert_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")

    return get_generation_file_metadata(generation_id)


@router.get("/{generation_id}/download/pdf", response_model=None, summary="Download resume as PDF")
async def download_resume_pdf(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """
    Download the generated resume as a PDF file.

    Compiles the resume on-the-fly from the saved recommendation and LaTeX template.
    Returns a streaming PDF response.
    """
    try:
        gen = GenerationRepository().assert_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")

    if gen.status not in ("completed", "draft"):
        raise HTTPException(status_code=409, detail="Generation is not ready for download")

    return await _run_pdf_export(str(current_user.user_id), generation_id, gen)


@router.get("/{generation_id}/download/docx", response_model=None, summary="Download resume as Word document")
async def download_resume_docx(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """
    Download the generated resume as a Word document (.docx).

    Exports from the saved recommendation data on-the-fly.
    """
    try:
        gen = GenerationRepository().assert_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")

    if gen.status not in ("completed", "draft"):
        raise HTTPException(status_code=409, detail="Generation is not ready for download")

    return _run_docx_export(str(current_user.user_id), generation_id, gen)
