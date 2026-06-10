"""
Worker callable for RQ-based generation job execution.

This module defines the real callable that replaces the Phase 6B/6C
placeholder. RQ workers import and execute this function when popping
jobs from the generation queue.

The function is a sync wrapper (required by RQ) around the async
generation pipeline. It reuses the existing _run_generation_pipeline
from the API layer, which handles all AI calls, optimization, validation,
scoring, PDF/DOCX export, and DB persistence.

SSE emit_progress calls inside _run_generation_pipeline are safe no-ops
in the worker process because the in-memory progress channel does not
exist (create_progress_channel is only called in the API process for
in-process mode).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.application.jobs.generation_job_contract import GenerationJobPayload
from app.services.generation_progress_service import set_generation_user
from app.application.use_cases.generation_result import (
    GENERATION_STATUS_FAILED,
    GENERATION_STATUS_RUNNING,
    update_generation_status,
)

logger = logging.getLogger(__name__)


def execute_generation_job(payload_dict: dict[str, Any]) -> dict[str, Any]:
    """
    RQ worker callable — deserialise payload and run the generation pipeline.

    This function is the real callable stored in RQ jobs (replaces the
    Phase 6B/6C placeholder). It is intentionally synchronous because RQ
    workers execute job functions synchronously. The async pipeline is
    wrapped with asyncio.run().

    Parameters
    ----------
    payload_dict : dict
        Serialised GenerationJobPayload fields.

    Returns
    -------
    dict
        Result dict with 'success', 'generation_id', and optionally
        'error_code' / 'error_message'. RQ stores this on the job.
    """
    payload = GenerationJobPayload(**payload_dict)

    try:
        result = asyncio.run(_run_worker_generation(payload))
        return result
    except Exception as exc:
        logger.exception(
            "[%s] Worker execution failed unexpectedly",
            payload.generation_id,
        )
        return {
            "success": False,
            "generation_id": payload.generation_id,
            "error_code": "WORKER_ERROR",
            "error_message": str(exc),
        }


async def _run_worker_generation(payload: GenerationJobPayload) -> dict[str, Any]:
    """
    Run the full generation pipeline inside an RQ worker.

    Steps
    -----
    1. Set DB status to running.
    2. Reconstruct domain objects from serialised payload fields.
    3. Call the existing pipeline runner (_run_generation_pipeline),
       which handles all AI calls, optimisation, validation, and DB writes.
    4. Log completion or forward failure to the existing fail_generation
       path.
    """
    generation_id = payload.generation_id
    user_id = payload.user_id

    logger.info(
        "[%s] Worker picked up generation job user_id=%s request_id=%s",
        generation_id,
        user_id,
        payload.request_id,
    )

    # ── Step 1: Set status to running ───────────────────────────────────
    set_generation_user(generation_id, user_id)
    update_generation_status(user_id, generation_id, GENERATION_STATUS_RUNNING)

    # ── Step 2: Reconstruct domain objects ──────────────────────────────
    profile = _deserialize_profile(payload.profile_json)
    sanitization = _deserialize_sanitization(payload.sanitization_json)

    # ── Step 3: Run the pipeline ────────────────────────────────────────
    # Lazy import to avoid pulling in FastAPI/route-layer deps at module
    # import time. The pipeline runner is the same function used by the
    # SSE streaming path — its emit_progress calls are safe no-ops in the
    # worker process (no in-memory channel exists).
    from app.api.v1.endpoints.pipeline import _run_generation_pipeline

    await _run_generation_pipeline(
        raw_jd_text=payload.raw_jd_text,
        clean_jd_text=payload.clean_jd_text,
        sanitization=sanitization,
        profile=profile,
        user_id=user_id,
        generation_id=generation_id,
        target_pages=payload.target_pages,
        target_ats_score=payload.target_ats_score,
        max_repair_attempts=payload.max_repair_attempts,
        emphasis=payload.emphasis,
        additional_alignment_text=payload.additional_alignment_text,
        ats_optimization_mode=payload.ats_optimization_mode,
        request_id=payload.request_id,
    )

    logger.info("[%s] Worker completed generation successfully", generation_id)

    return {
        "success": True,
        "generation_id": generation_id,
    }


def _deserialize_profile(
    data: dict[str, Any] | None,
) -> Any:
    """Reconstruct a MasterProfile from serialised JSON fields."""
    if data is None:
        return None
    from app.schemas.profile import MasterProfile

    return MasterProfile(**data)


def _deserialize_sanitization(
    data: dict[str, Any] | None,
) -> Any:
    """Reconstruct a JDSanitizationResult from serialised JSON fields."""
    if data is None:
        return None
    from app.services.jd_sanitization_service import JDSanitizationResult

    return JDSanitizationResult(**data)
