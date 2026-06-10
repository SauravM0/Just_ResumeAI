"""
PDF resume export use case.

Orchestrates PDF (and DOCX-fallback) export for saved resume generations.
The route layer stays HTTP-shaped; this module owns export validation,
compilation, DB updates, and response construction.

SupabaseService = low-level DB adapter (raw PostgREST calls)
Repository      = table/use-case-specific database boundary (encapsulated queries)
"""

from __future__ import annotations

import pydantic
import json
import logging
import re
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.application.use_cases.parsed_jd_compat import normalize_saved_parsed_jd
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.infrastructure.repositories.usage_repository import UsageRepository
from app.schemas.resume import ResumeRecommendation
from app.schemas.supabase import ResumeGenerationUpdate
from app.services.jd_sanitization_service import (
    assert_parsed_jd_safe,
    assert_render_text_safe,
    assert_resume_recommendation_safe,
    recommendation_to_plain_text,
)
from app.services.pdf_compile_service import PDFCompileError
from app.services.pdf_page_fit_service import compile_pdf_to_page_target
from app.services.resume_budget_service import fit_resume_to_page_budget
from app.services.resume_validation_gate import (
    ResumeValidationError,
    validate_resume_for_export,
)

logger = logging.getLogger(__name__)


# ── Internal helpers ────────────────────────────────────────────────────


def _remove_local_file(path: str | None) -> None:
    """Cleanup a local temp file after download response is sent."""
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove local generated file after failed upload: %s", path)


def _clean_name_slug(name: str | None) -> str:
    """Convert a candidate name to a file-safe slug."""
    if not name:
        return "resume"
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", name)
    slug = re.sub(r"\s+", "-", slug.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "resume"


def _download_response(
    path: str,
    *,
    generation_id: str,
    file_type: Literal["pdf", "docx"],
    candidate_name: str | None = None,
) -> FileResponse:
    """Build a FileResponse with proper content-type and cleanup."""
    media_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    name_slug = _clean_name_slug(candidate_name) if candidate_name else "resume"
    filename = f"{name_slug}.{file_type}"
    return FileResponse(
        path=path,
        media_type=media_types[file_type],
        filename=filename,
    )


def _fit_for_export(
    parsed_jd,
    recommendation: ResumeRecommendation,
    target_pages: int = 1,
) -> ResumeRecommendation:
    """Fit resume to page budget before export."""
    return fit_resume_to_page_budget(
        recommendation=recommendation,
        parsed_jd=parsed_jd,
        target_pages=target_pages,
    )


def _log_export(user_id: str, generation_id: str, event_type: str, metadata: dict) -> None:
    """Best-effort usage logging for exports."""
    try:
        UsageRepository().log(
            user_id=user_id,
            event_type=event_type,
            generation_id=generation_id,
            metadata=metadata,
        )
    except Exception:
        logger.warning("Failed to log %s usage event", event_type)


# ── Shared export validation ────────────────────────────────────────────


def require_saved_export_data(gen) -> tuple[ResumeRecommendation, object, dict]:
    """
    Validate and prepare export data from a generation record.

    Returns (recommendation, parsed_jd, validation_meta).
    Raises HTTPException on invalid / blocked data.
    """
    if not gen.resume_json or not gen.parsed_jd_json:
        raise HTTPException(status_code=400, detail="No saved resume data found for this generation")

    parsed_jd = normalize_saved_parsed_jd(
        gen.parsed_jd_json,
        job_title=getattr(gen, "job_title", None),
        company=getattr(gen, "company", None),
        raw_text=getattr(gen, "raw_jd_text", None),
    )
    assert_parsed_jd_safe(parsed_jd)

    try:
        recommendation = ResumeRecommendation(**gen.resume_json)
    except pydantic.ValidationError as e:
        import logging
        logging.getLogger(__name__).error("Resume validation errors: %s", e.errors())
        raise

    ats_score_json = gen.ats_score_json or {}
    score_version = ats_score_json.get("resume_version_id")
    ats_score_stale = bool(score_version and recommendation.version_id != score_version)

    recommendation = _fit_for_export(parsed_jd, recommendation, target_pages=getattr(gen, "target_pages", 1))
    try:
        validation = validate_resume_for_export(recommendation, parsed_jd=parsed_jd)
    except ResumeValidationError as exc:
        detail = ["Resume export blocked by validation gate."]
        detail.extend(
            f"{issue.path}: {issue.message}" if issue.path else issue.message
            for issue in exc.issues
        )
        raise HTTPException(status_code=422, detail=detail) from exc

    validation_warnings = [
        issue.message
        for issue in validation.issues
        if issue.severity.value in ("warning", "error")
    ][:10]
    if ats_score_stale:
        validation_warnings.insert(
            0,
            "Resume content changed since the last ATS check; export continued without refreshing ATS.",
        )

    meta = {
        "validation_repaired": validation.repaired,
        "validation_export_ready": validation.export_ready,
        "validation_warnings": validation_warnings[:10],
    }
    assert_resume_recommendation_safe(validation.recommendation)
    assert_render_text_safe(
        recommendation_to_plain_text(validation.recommendation),
        artifact="recommendation_plain_text",
    )
    return validation.recommendation, parsed_jd, meta


# ── PDF export orchestration ────────────────────────────────────────────


async def export_resume_pdf(
    user_id: str,
    generation_id: str,
    gen,
    *,
    regenerated: bool = False,
) -> FileResponse:
    """
    Compile, validate, persist, and return a PDF (or DOCX fallback) FileResponse.

    Preserves all existing headers:
      X-Compile-Warnings, X-PDF-Inspection-Warnings, X-PDF-Page-Count,
      X-Resume-Compressed, X-Compression-Actions, X-Regenerated,
      X-Validation-Repaired, X-Validation-Warnings, X-PDF-Failed, X-User-Message
    """
    recommendation, parsed_jd, validation_meta = require_saved_export_data(gen)
    repo = GenerationRepository()

    try:
        fitted = await compile_pdf_to_page_target(
            recommendation=recommendation,
            parsed_jd=parsed_jd,
            generation_id=generation_id,
            target_pages=getattr(gen, "target_pages", 1),
            ats_plan=None,
        )
    except ResumeValidationError as exc:
        detail = ["Resume export blocked. Fix the highlighted resume content and try again."]
        detail.extend(
            f"{issue.path}: {issue.message}" if issue.path else issue.message
            for issue in exc.issues[:8]
        )
        raise HTTPException(status_code=422, detail=detail) from exc
    except PDFCompileError as exc:
        raise HTTPException(status_code=422, detail=exc.response_errors()) from exc
    except Exception as exc:
        logger.exception("[%s] PDF page fitting failed", generation_id)
        raise HTTPException(status_code=422, detail=[str(exc)]) from exc

    # DOCX fallback path
    if fitted.pdf_failed and fitted.docx_fallback_path:
        repo.update(
            user_id=user_id,
            generation_id=generation_id,
            data=ResumeGenerationUpdate(
                resume_json=fitted.recommendation.model_dump(),
                ats_score_json=fitted.ats_score.model_dump(),
                latex_source=fitted.latex_source,
                last_exported_version_id=fitted.recommendation.version_id,
                last_validated_version_id=fitted.recommendation.version_id,
            ),
        )
        _log_export(
            user_id,
            generation_id,
            "docx_fallback_export",
            {"compile_success": False, "regenerated": regenerated},
        )
        response = _download_response(
            fitted.docx_fallback_path,
            generation_id=generation_id,
            file_type="docx",
            candidate_name=fitted.recommendation.contact.full_name,
        )
        response.headers["X-PDF-Failed"] = "true"
        response.headers["X-User-Message"] = (
            "Your resume is ready as a Word document. PDF generation had a formatting issue."
        )
        return response

    # Successful PDF path
    repo.update(
        user_id=user_id,
        generation_id=generation_id,
        data=ResumeGenerationUpdate(
            resume_json=fitted.recommendation.model_dump(),
            ats_score_json=fitted.ats_score.model_dump(),
            latex_source=fitted.latex_source,
            last_exported_version_id=fitted.recommendation.version_id,
            last_validated_version_id=fitted.recommendation.version_id,
        ),
    )

    _log_export(
        user_id,
        generation_id,
        "pdf_export",
        {
            "compile_success": True,
            "regenerated": regenerated,
            "page_count": fitted.page_count,
            "compressed": fitted.compression_applied,
        },
    )

    response = _download_response(
        fitted.pdf_path,
        generation_id=generation_id,
        file_type="pdf",
        candidate_name=fitted.recommendation.contact.full_name,
    )
    if fitted.compile_warnings:
        response.headers["X-Compile-Warnings"] = json.dumps(fitted.compile_warnings)
    if fitted.inspection_warnings:
        response.headers["X-PDF-Inspection-Warnings"] = json.dumps(fitted.inspection_warnings)
    response.headers["X-PDF-Page-Count"] = str(fitted.page_count)
    response.headers["X-Resume-Compressed"] = "true" if fitted.compression_applied else "false"
    response.headers["X-Compression-Actions"] = json.dumps(fitted.compression_actions)
    response.headers["X-Regenerated"] = "true" if regenerated else "false"
    response.headers["X-Validation-Repaired"] = "true" if validation_meta.get("validation_repaired") else "false"
    if validation_meta.get("validation_warnings"):
        response.headers["X-Validation-Warnings"] = json.dumps(validation_meta["validation_warnings"])
    return response
