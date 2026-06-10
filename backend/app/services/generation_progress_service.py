"""
In-memory SSE event bus for generation progress.

Maps generation_id → asyncio.Queue of ProgressEvent objects.
Events are consumed by the SSE stream endpoint and emitted by the
background generation pipeline task.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.infrastructure.repositories.generation_repository import GenerationRepository

# ── Safe progress_json sanitizer ──────────────────────────────────────────
# Only these keys are allowed in DB-persisted progress_json. Large,
# nested, or sensitive payloads are never written.
_PROGRESS_JSON_ALLOWED_KEYS: set[str] = {
    "step", "total", "label", "detail",
    "job_title", "keywords_found",
    "original_score", "final_score",
    "attempt", "max_attempts", "score",
    "page_count", "warning_count",
    "code",
    # Stale-job recovery metadata (written by sweeper, not emit_progress)
    "retry_count", "last_retry_reason", "last_retry_at",
}
_PROGRESS_JSON_MAX_STRING_LENGTH: int = 200
_PROGRESS_JSON_MAX_LABEL_LENGTH: int = 200


def _sanitize_for_progress_json(data: dict[str, Any]) -> dict[str, Any]:
    """Return only whitelisted, small, safe fields from an emit_progress payload.

    Never persists full resume_json, raw_jd_text, profile_json,
    AI responses, uploaded document text, tokens, keys, or
    large validation/scoring blobs.
    """
    out: dict[str, Any] = {}
    for key in _PROGRESS_JSON_ALLOWED_KEYS:
        if key not in data:
            continue
        val = data[key]
        if isinstance(val, str):
            max_len = 60 if key == "code" else _PROGRESS_JSON_MAX_STRING_LENGTH
            out[key] = val[:max_len]
        elif isinstance(val, bool):
            out[key] = val
        elif isinstance(val, (int, float)):
            out[key] = val
        # dict, list, None, and other types are silently dropped
    return out


logger = logging.getLogger(__name__)

# Map: generation_id → asyncio.Queue
_progress_queues: dict[str, asyncio.Queue] = {}
# Map: generation_id → user_id (for DB progress persistence)
_generation_user_map: dict[str, str] = {}


@dataclass
class ProgressEvent:
    """A single progress event to be streamed via SSE."""
    event: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


def create_progress_channel(generation_id: str) -> asyncio.Queue:
    """Create a new progress queue for a generation. Returns the queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _progress_queues[generation_id] = q
    return q


def has_progress_channel(generation_id: str) -> bool:
    """Return whether an in-memory stream channel exists for a generation."""
    return generation_id in _progress_queues


async def emit_progress(
    generation_id: str,
    event: str,
    data: dict[str, Any],
) -> None:
    """Emit a progress event to the SSE stream and persist to DB."""
    q = _progress_queues.get(generation_id)
    if q:
        try:
            await q.put(ProgressEvent(event=event, data=data))
        except asyncio.QueueFull:
            logger.warning(
                "progress_queue.full generation_id=%s event=%s",
                generation_id, event,
            )
    _persist_progress_to_db(generation_id, event, data)


def emit_progress_sync(generation_id: str, event: str, data: dict[str, Any]) -> None:
    """Sync wrapper for emit_progress — use in non-async contexts."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(emit_progress(generation_id, event, data))
    except RuntimeError:
        pass  # No event loop — not a streaming context


async def get_next_event(
    generation_id: str,
    timeout: float = 60.0,
) -> ProgressEvent | None:
    """Get the next event for a generation. Returns None on timeout."""
    q = _progress_queues.get(generation_id)
    if not q:
        return None
    try:
        return await asyncio.wait_for(q.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


def cleanup_progress_channel(generation_id: str) -> None:
    """Remove the in-memory SSE queue only (not the user mapping).

    The user mapping lifecycle is managed separately via
    cleanup_generation_user() so that DB progress writes can
    continue after the SSE stream has ended.
    """
    _progress_queues.pop(generation_id, None)


def cleanup_generation_user(generation_id: str) -> None:
    """Remove the generation→user mapping after the pipeline task is terminal.

    Called from the pipeline task's finally block, not from the SSE stream,
    so that _persist_progress_to_db still works until the very last
    emit_progress call.
    """
    _generation_user_map.pop(generation_id, None)


def set_generation_user(generation_id: str, user_id: str) -> None:
    """Register the user_id associated with a generation for DB persistence."""
    _generation_user_map[generation_id] = user_id


def _get_generation_user(generation_id: str) -> str | None:
    """Look up the user_id associated with a generation."""
    return _generation_user_map.get(generation_id)


def _persist_progress_to_db(
    generation_id: str,
    event: str,
    data: dict[str, Any],
) -> None:
    """Write current_step/progress_percentage/progress_json to DB."""
    user_id = _get_generation_user(generation_id)
    if user_id is None:
        return
    # Lazy import to avoid circular dependency (generation_result imports has_progress_channel from this module)
    from app.application.use_cases.generation_result import GENERATION_STEP_PROGRESS
    percentage = GENERATION_STEP_PROGRESS.get(event)
    if percentage is None:
        return
    progress_json: dict[str, Any] = {
        "step": event,
        "percentage": percentage,
    }
    safe_data = _sanitize_for_progress_json(data)
    if safe_data:
        progress_json.update(safe_data)
    try:
        GenerationRepository().update_progress(
            user_id=user_id,
            generation_id=generation_id,
            current_step=event,
            progress_percentage=percentage,
            progress_json=progress_json,
        )
    except Exception:
        logger.warning(
            "progress_db.failed generation_id=%s event=%s",
            generation_id, event,
        )


async def send_complete(
    generation_id: str,
    final_score: float,
    original_score: float | None = None,
) -> None:
    """Send terminal 'complete' event and signal stream end."""
    await emit_progress(generation_id, "complete", {
        "step": 8,
        "label": "Done!",
        "final_score": final_score,
        "original_score": original_score,
        "generation_id": generation_id,
    })
    # Sentinel: put None to signal stream end
    q = _progress_queues.get(generation_id)
    if q:
        await q.put(None)


async def send_error(generation_id: str, code: str, message: str) -> None:
    """Send terminal 'error' event and signal stream end."""
    await emit_progress(generation_id, "error", {
        "code": code,
        "message": message,
        "generation_id": generation_id,
    })
    q = _progress_queues.get(generation_id)
    if q:
        await q.put(None)  # Sentinel
