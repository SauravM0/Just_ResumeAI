"""Background generation lifecycle wrapper.

This module owns reliability concerns around generation tasks. The actual
resume generation algorithm stays in `pipeline.py` and existing services for
Phase 4A.
"""

from __future__ import annotations

import logging

from app.application.use_cases.generation_result import (
    safe_failure_message,
)
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.services.generation_progress_service import cleanup_generation_user, cleanup_progress_channel, send_error
from app.services.metrics_service import record_generation_failed
from app.utils.observability import log_event

logger = logging.getLogger(__name__)


def log_generation_step(
    *,
    request_id: str | None,
    generation_id: str,
    user_id: str,
    step: str,
    status: str,
    duration_ms: float | None = None,
    **fields,
) -> None:
    log_event(
        logger,
        logging.INFO if status not in {"error", "failed"} else logging.WARNING,
        "generation.step",
        request_id=request_id,
        generation_id=generation_id,
        user_id=user_id,
        step=step,
        status=status,
        duration_ms=round(duration_ms) if duration_ms is not None else None,
        **fields,
    )


async def fail_generation(
    *,
    user_id: str,
    generation_id: str,
    request_id: str | None,
    error_code: str,
    duration_ms: float,
) -> None:
    """Persist and emit safe failed terminal state for a generation."""
    message = safe_failure_message(error_code)
    record_generation_failed(generation_id, user_id, error_code, duration_ms)
    log_generation_step(
        request_id=request_id,
        generation_id=generation_id,
        user_id=user_id,
        step="error",
        status="failed",
        duration_ms=duration_ms,
        error_code=error_code,
    )
    try:
        GenerationRepository().mark_failed(
            user_id,
            generation_id,
            failure_reason=message,
            failure_code=error_code,
        )
    except Exception:
        logger.warning("[%s] Could not mark generation failed", generation_id)
    try:
        await send_error(generation_id, error_code, message)
    except Exception:
        logger.warning("[%s] Could not emit terminal generation error", generation_id)


def cleanup_generation_channel(generation_id: str) -> None:
    """Clean up both the SSE queue and the generation→user mapping.

    Called from the pipeline task's finally block (not from the SSE stream)
    so that DB progress persistence remains available until the pipeline
    is fully terminal.
    """
    cleanup_progress_channel(generation_id)
    cleanup_generation_user(generation_id)
