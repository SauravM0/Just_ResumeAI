"""SSE stream lifecycle handling for resume generation."""

from __future__ import annotations

import asyncio
import json
import time as _time
from collections.abc import AsyncIterator

from app.application.use_cases.generation_result import (
    GENERATION_STATUS_CANCELLED,
    GENERATION_STATUS_COMPLETED,
    GENERATION_STATUS_FAILED,
    TERMINAL_GENERATION_STATUSES,
    safe_failure_message,
    status_payload,
)
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.supabase import ResumeGenerationRecord
from app.services.generation_progress_service import (
    cleanup_progress_channel,
    get_next_event,
    has_progress_channel,
)


async def _poll_db_progress(
    gen: ResumeGenerationRecord,
    generation_id: str,
) -> AsyncIterator[dict[str, str]]:
    """Fallback: poll DB progress fields when no in-memory channel exists."""
    repo = GenerationRepository()
    user_id = str(gen.user_id)
    deadline = _time.monotonic() + 300.0
    last_step: str | None = None

    while _time.monotonic() < deadline:
        try:
            current = repo.get_by_id(user_id, generation_id)
        except Exception:
            current = None

        if current is None:
            break

        if current.status == GENERATION_STATUS_COMPLETED:
            yield {
                "event": "complete",
                "data": json.dumps({
                    **status_payload(current, message="Generation completed."),
                    "final_score": (
                        current.ats_score_json.get("overall_score")
                        if isinstance(current.ats_score_json, dict)
                        else None
                    ),
                }),
            }
            return

        if current.status == GENERATION_STATUS_FAILED:
            yield {
                "event": "error",
                "data": json.dumps({
                    **status_payload(
                        current,
                        message=safe_failure_message(current.failure_code or "PIPELINE_ERROR"),
                    ),
                    "code": current.failure_code or "PIPELINE_ERROR",
                }),
            }
            return

        if current.status == GENERATION_STATUS_CANCELLED:
            yield {
                "event": "error",
                "data": json.dumps({
                    **status_payload(current, message="Generation was cancelled."),
                    "code": "GENERATION_CANCELLED",
                }),
            }
            return

        current_step = current.current_step
        if current_step and current_step != last_step:
            last_step = current_step
            yield {
                "event": "status",
                "data": json.dumps(status_payload(current, channel_available=False)),
            }

        await asyncio.sleep(3)

    yield {
        "event": "status",
        "data": json.dumps({
            **status_payload(
                gen,
                message="Generation is taking longer than expected. Poll the result endpoint for status.",
            ),
            "code": "STREAM_IDLE",
        }),
    }


async def generation_stream_events(
    gen: ResumeGenerationRecord,
    generation_id: str,
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE events without changing event names or payload compatibility."""
    terminal_seen = gen.status in TERMINAL_GENERATION_STATUSES
    try:
        if gen.status == GENERATION_STATUS_COMPLETED:
            yield {
                "event": "complete",
                "data": json.dumps({
                    **status_payload(gen, message="Generation completed."),
                    "final_score": (
                        gen.ats_score_json.get("overall_score")
                        if isinstance(gen.ats_score_json, dict)
                        else None
                    ),
                }),
            }
            return
        if gen.status == GENERATION_STATUS_FAILED:
            yield {
                "event": "error",
                "data": json.dumps({
                    **status_payload(gen, message=safe_failure_message("PIPELINE_ERROR")),
                    "code": "PIPELINE_ERROR",
                }),
            }
            return
        if gen.status == GENERATION_STATUS_CANCELLED:
            yield {
                "event": "error",
                "data": json.dumps({
                    **status_payload(gen, message="Generation was cancelled."),
                    "code": "GENERATION_CANCELLED",
                }),
            }
            return

        channel_available = has_progress_channel(generation_id)
        yield {
            "event": "status",
            "data": json.dumps(status_payload(gen, channel_available=channel_available)),
        }
        if not channel_available:
            async for db_event in _poll_db_progress(gen, generation_id):
                yield db_event
                if db_event.get("event") in ("complete", "error"):
                    terminal_seen = True
                    return
            return

        while True:
            event = await get_next_event(generation_id, timeout=30.0)
            if event is None:
                yield {
                    "event": "status",
                    "data": json.dumps({
                        **status_payload(
                            gen,
                            message="No live progress event was received. Poll the result endpoint for the latest status.",
                            channel_available=has_progress_channel(generation_id),
                        ),
                        "code": "STREAM_IDLE",
                    }),
                }
                break
            yield {
                "event": event.event,
                "data": json.dumps(event.data),
            }
            if event.event in ("complete", "error"):
                terminal_seen = True
                break
    finally:
        if terminal_seen:
            cleanup_progress_channel(generation_id)
