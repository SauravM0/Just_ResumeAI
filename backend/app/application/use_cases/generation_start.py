"""Start streaming generation use case.

Routes receive HTTP inputs; this module coordinates generation lifecycle
startup. The algorithmic resume generation/scoring remains in the existing
pipeline/services layer for now.

In Phase 6D, this module supports two execution modes controlled by the
GENERATION_EXECUTOR config:
  - "in-process" (default): runs generation via asyncio.create_task.
  - "worker": enqueues a GenerationJobPayload to Redis/RQ for a separate
    worker process.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from app.application.use_cases.generation_result import (
    GENERATION_STATUS_FAILED,
    GENERATION_STATUS_QUEUED,
    update_generation_status,
)
from app.application.use_cases.generation_runner import log_generation_step
from app.config import get_settings
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.pipeline import PipelineOptimizedGenerateRequest
from app.schemas.supabase import ResumeGenerationCreate
from app.services.generation_progress_service import create_progress_channel, set_generation_user
from app.services.jd_sanitization_service import (
    INVALID_JD_USER_MESSAGE,
    InvalidJobDescriptionError,
    require_valid_jd_text,
)
from app.services.metrics_service import record_generation_rate_limited

logger = logging.getLogger(__name__)

PipelineRunnerFactory = Callable[[dict[str, Any]], Awaitable[None]]


def start_generation_use_case(
    *,
    body: PipelineOptimizedGenerateRequest,
    user_id: str,
    request_id: str | None,
    runner_factory: PipelineRunnerFactory,
) -> dict[str, str]:
    """Create a generation row, queue progress, and launch the background runner."""
    settings = get_settings()
    _validate_generation_payload(body, settings)
    _enforce_generation_limits(user_id, settings)

    raw_jd_text = body.raw_jd_text

    if not raw_jd_text or len(raw_jd_text.strip()) < 50:
        raise HTTPException(status_code=422, detail="Job description is too short. Please provide at least 50 characters.")

    try:
        sanitization = require_valid_jd_text(raw_jd_text)
    except InvalidJobDescriptionError as exc:
        raise HTTPException(status_code=422, detail=INVALID_JD_USER_MESSAGE) from exc

    clean_jd_text = sanitization.clean_text
    if len(clean_jd_text.strip()) < 50:
        raise HTTPException(
            status_code=422,
            detail="Job description is too short after cleanup. Please provide role-specific content.",
        )

    repo = GenerationRepository()
    generation = repo.create(
        user_id,
        ResumeGenerationCreate(
            raw_jd_text=raw_jd_text,
            target_pages=body.target_pages,
        ),
    )
    generation_id = str(generation.id)
    update_generation_status(user_id, generation_id, GENERATION_STATUS_QUEUED)
    set_generation_user(generation_id, user_id)

    # ── Enqueue to worker when configured ───────────────────────────────────
    if settings.GENERATION_EXECUTOR == "worker":
        from app.application.jobs.generation_job_contract import (
            GenerationJobPayload,
        )
        from app.application.jobs.generation_queue_factory import (
            get_generation_queue,
        )

        payload = GenerationJobPayload(
            generation_id=generation_id,
            user_id=user_id,
            raw_jd_text=raw_jd_text,
            clean_jd_text=clean_jd_text,
            sanitization_json=dataclasses.asdict(sanitization),
            profile_json=body.profile.model_dump(mode="json"),
            target_pages=body.target_pages,
            allow_two_pages_for_senior=body.allow_two_pages_for_senior,
            generate_pdf=body.generate_pdf,
            target_ats_score=body.target_ats_score,
            max_repair_attempts=body.max_repair_attempts,
            emphasis=body.emphasis,
            additional_alignment_text=body.additional_alignment_text,
            ats_optimization_mode=body.ats_optimization_mode,
            request_id=request_id,
        )

        try:
            queue = get_generation_queue()
            queue.enqueue(payload)
        except Exception as exc:
            logger.error(
                "[%s] Failed to enqueue generation job: %s",
                generation_id, exc,
            )
            update_generation_status(user_id, generation_id, GENERATION_STATUS_FAILED)
            raise HTTPException(
                status_code=503,
                detail="Generation queue is temporarily unavailable. Please retry later.",
            ) from exc

        return {"generation_id": generation_id, "status": GENERATION_STATUS_QUEUED}

    # ── In-process (default): create progress channel and run via task ──────
    create_progress_channel(generation_id)
    log_generation_step(
        request_id=request_id,
        generation_id=generation_id,
        user_id=user_id,
        step="started",
        status="queued",
    )

    asyncio.create_task(
        runner_factory({
            "raw_jd_text": raw_jd_text,
            "clean_jd_text": clean_jd_text,
            "sanitization": sanitization,
            "profile": body.profile,
            "user_id": user_id,
            "generation_id": generation_id,
            "target_pages": body.target_pages,
            "target_ats_score": body.target_ats_score,
            "max_repair_attempts": body.max_repair_attempts,
            "emphasis": body.emphasis,
            "additional_alignment_text": body.additional_alignment_text,
            "ats_optimization_mode": body.ats_optimization_mode,
            "request_id": request_id,
        })
    )

    return {"generation_id": generation_id, "status": GENERATION_STATUS_QUEUED}


def _validate_generation_payload(body: PipelineOptimizedGenerateRequest, settings) -> None:
    raw_jd_length = len(body.raw_jd_text or "")
    if raw_jd_length > settings.MAX_RAW_JD_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Job description is too large. Please keep it under {settings.MAX_RAW_JD_CHARS} characters.",
        )

    alignment_text = body.additional_alignment_text or ""
    if len(alignment_text) > settings.MAX_ALIGNMENT_TEXT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Additional alignment text is too large. Please keep it under {settings.MAX_ALIGNMENT_TEXT_CHARS} characters.",
        )

    profile_size = _json_char_count(body.profile.model_dump(mode="json"))
    if profile_size > settings.MAX_PROFILE_PAYLOAD_CHARS:
        raise HTTPException(
            status_code=422,
            detail="Profile payload is too large. Please remove unused profile details and try again.",
        )


def _enforce_generation_limits(user_id: str, settings) -> None:
    if not settings.ENABLE_GENERATION_LIMITS:
        return

    repo = GenerationRepository()
    try:
        active_count = repo.count_active_for_user(user_id)
        if active_count >= settings.MAX_ACTIVE_GENERATIONS_PER_USER:
            _record_limit_block(
                user_id,
                "active_generation_limit",
                {
                    "active_count": active_count,
                    "limit": settings.MAX_ACTIVE_GENERATIONS_PER_USER,
                },
            )
            raise HTTPException(
                status_code=409,
                detail="You already have active generations running. Please wait for one to finish before starting another.",
            )

        now = datetime.now(timezone.utc)
        hourly_count = repo.count_for_user_since(user_id, now - timedelta(hours=1))
        if hourly_count >= settings.HOURLY_GENERATION_LIMIT_PER_USER:
            _record_limit_block(
                user_id,
                "hourly_generation_limit",
                {
                    "window": "1h",
                    "count": hourly_count,
                    "limit": settings.HOURLY_GENERATION_LIMIT_PER_USER,
                },
            )
            raise HTTPException(
                status_code=429,
                detail="Hourly generation limit reached. Please try again later.",
            )

        daily_count = repo.count_for_user_since(user_id, now - timedelta(days=1))
        if daily_count >= settings.DAILY_GENERATION_LIMIT_PER_USER:
            _record_limit_block(
                user_id,
                "daily_generation_limit",
                {
                    "window": "24h",
                    "count": daily_count,
                    "limit": settings.DAILY_GENERATION_LIMIT_PER_USER,
                },
            )
            raise HTTPException(
                status_code=429,
                detail="Daily generation limit reached. Please try again tomorrow.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("generation.limit_check_failed user_id=%s error=%s", user_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Generation limits are temporarily unavailable. Please retry later.",
        ) from exc


def _record_limit_block(user_id: str, reason: str, metadata: dict[str, Any]) -> None:
    record_generation_rate_limited(user_id=user_id, reason=reason, metadata=metadata)


def _json_char_count(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
