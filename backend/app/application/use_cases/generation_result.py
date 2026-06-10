"""Generation result lifecycle decisions.

The route layer should stay HTTP-shaped; this use-case layer owns generation
lifecycle orchestration. The resume writing/scoring algorithms remain in the
existing services and pipeline module for now.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.supabase import ResumeGenerationRecord, ResumeGenerationUpdate
from app.services.generation_progress_service import has_progress_channel
from app.services.generation_service import GenerationNotFoundError
from app.services.supabase_service import SupabaseDatabaseError

GENERATION_STATUS_DRAFT = "draft"
GENERATION_STATUS_QUEUED = "queued"
GENERATION_STATUS_RUNNING = "running"
GENERATION_STATUS_COMPLETED = "completed"
GENERATION_STATUS_FAILED = "failed"
GENERATION_STATUS_CANCELLED = "cancelled"
GENERATION_STATUS_ARCHIVED = "archived"

ACTIVE_GENERATION_STATUSES = {
    GENERATION_STATUS_DRAFT,
    GENERATION_STATUS_QUEUED,
    GENERATION_STATUS_RUNNING,
}
TERMINAL_GENERATION_STATUSES = {
    GENERATION_STATUS_COMPLETED,
    GENERATION_STATUS_FAILED,
    GENERATION_STATUS_CANCELLED,
    GENERATION_STATUS_ARCHIVED,
}

GENERATION_STEP_PROGRESS = {
    "started": 5,
    "jd_parsing": 12,
    "jd_parsed": 20,
    "scoring_original": 30,
    "original_scored": 35,
    "building_evidence": 45,
    "composing": 60,
    "repair_pass": 72,
    "pdf_compile": 88,
    "complete": 100,
    "error": 100,
}

SAFE_FAILURE_MESSAGES = {
    "JD_INVALID": "Job description could not be parsed. Please check the content.",
    "AI_TIMEOUT": "AI generation timed out. Please retry.",
    "PIPELINE_ERROR": "Generation failed. Please retry.",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def status_payload(
    gen: ResumeGenerationRecord,
    *,
    message: str | None = None,
    channel_available: bool | None = None,
) -> dict[str, Any]:
    status = gen.status or GENERATION_STATUS_DRAFT
    payload: dict[str, Any] = {
        "generation_id": str(gen.id),
        "status": status,
        "current_step": gen.current_step if gen.current_step else current_step_for_status(status),
        "progress_percentage": gen.progress_percentage if gen.progress_percentage is not None else progress_for_status(status),
        "updated_at": gen.updated_at.isoformat() if gen.updated_at else None,
    }
    if gen.progress_json:
        payload["progress_json"] = gen.progress_json
    if message:
        payload["message"] = message
    if channel_available is not None:
        payload["channel_available"] = channel_available
    return payload


def current_step_for_status(status: str) -> str:
    if status == GENERATION_STATUS_COMPLETED:
        return "complete"
    if status == GENERATION_STATUS_FAILED:
        return "error"
    if status == GENERATION_STATUS_CANCELLED:
        return "cancelled"
    if status == GENERATION_STATUS_QUEUED:
        return "queued"
    return "running" if status == GENERATION_STATUS_RUNNING else "draft"


def progress_for_status(status: str) -> int:
    if status == GENERATION_STATUS_COMPLETED:
        return 100
    if status in {GENERATION_STATUS_FAILED, GENERATION_STATUS_CANCELLED}:
        return 100
    if status == GENERATION_STATUS_RUNNING:
        return 10
    if status == GENERATION_STATUS_QUEUED:
        return 5
    return 0


def update_generation_status(
    user_id: str,
    generation_id: str,
    status: str,
    *,
    current_step: str | None = None,
    progress_percentage: int | None = None,
) -> None:
    repo = GenerationRepository()
    payload = ResumeGenerationUpdate(
        status=status,
        updated_at=utc_now(),
        current_step=current_step or current_step_for_status(status),
        progress_percentage=(
            progress_percentage
            if progress_percentage is not None
            else progress_for_status(status)
        ),
    )
    try:
        repo.update(user_id=user_id, generation_id=generation_id, data=payload)
    except SupabaseDatabaseError:
        if status not in {GENERATION_STATUS_QUEUED, GENERATION_STATUS_RUNNING}:
            raise
        repo.update(
            user_id=user_id,
            generation_id=generation_id,
            data=payload.model_copy(update={"status": GENERATION_STATUS_DRAFT}),
        )


def safe_failure_message(error_code: str) -> str:
    return SAFE_FAILURE_MESSAGES.get(error_code, SAFE_FAILURE_MESSAGES["PIPELINE_ERROR"])


def get_generation_result_for_user(user_id: str, generation_id: str):
    """Return the same result endpoint semantics established in Phase 3."""
    try:
        repo = GenerationRepository()
        gen = repo.assert_owner(user_id, generation_id)
    except GenerationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Generation not found") from exc

    if gen.status in ACTIVE_GENERATION_STATUSES:
        return JSONResponse(
            status_code=202,
            content=status_payload(
                gen,
                message="Generation is still in progress.",
                channel_available=has_progress_channel(generation_id),
            ),
        )
    if gen.status == GENERATION_STATUS_FAILED:
        raise HTTPException(status_code=409, detail=safe_failure_message("PIPELINE_ERROR"))
    if gen.status == GENERATION_STATUS_CANCELLED:
        raise HTTPException(status_code=409, detail="Generation was cancelled.")
    return gen
