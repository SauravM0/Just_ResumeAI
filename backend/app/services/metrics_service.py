"""Simple production metrics for generation monitoring.

Metrics are intentionally lightweight: every important event is emitted as a
structured log line, and best-effort rows are written to Supabase usage events
when a user id is available.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.config import get_settings
from app.services.supabase_service import SupabaseDatabaseError, get_supabase_service

logger = logging.getLogger("metrics")


class MetricEvent(str, Enum):
    GENERATION_STARTED = "generation_started"
    GENERATION_COMPLETED = "generation_completed"
    GENERATION_FAILED = "generation_failed"
    JD_CACHE_HIT = "jd_cache_hit"
    JD_CACHE_MISS = "jd_cache_miss"
    GEMINI_RETRY = "gemini_retry"
    GEMINI_TIMEOUT = "gemini_timeout"
    PDF_COMPILE_FAILED = "pdf_compile_failed"
    DOCX_FALLBACK_USED = "docx_fallback_used"
    PDF_EXPORT = "pdf_export"
    DOCX_EXPORT = "docx_export"
    GENERATION_CANCELLED = "generation_cancelled"
    GENERATION_RATE_LIMITED = "generation_rate_limited"


@dataclass
class GenerationTimer:
    """Context manager for timing generation stages."""

    stage_name: str
    generation_id: str = ""
    elapsed_ms: float = 0.0

    def __enter__(self) -> "GenerationTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args) -> None:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
        logger.debug(
            "metric.stage stage=%s generation_id=%s ms=%.0f",
            self.stage_name,
            self.generation_id,
            self.elapsed_ms,
        )


def record_generation_started(generation_id: str, user_id: str) -> None:
    logger.info("metric.generation_started generation_id=%s user_id=%s", generation_id, user_id)
    _log_usage_event(user_id, MetricEvent.GENERATION_STARTED.value, generation_id, {})


def record_generation_completed(
    generation_id: str,
    user_id: str,
    final_score: float,
    original_score: float | None,
    duration_ms: float,
    repair_passes: int,
    jd_cache_hit: bool = False,
) -> None:
    """Record a successful generation with key metrics."""
    logger.info(
        "metric.generation_completed "
        "generation_id=%s user_id=%s score=%.1f original_score=%s "
        "duration_ms=%.0f repair_passes=%d jd_cache_hit=%s",
        generation_id,
        user_id,
        final_score,
        f"{original_score:.1f}" if original_score is not None else "null",
        duration_ms,
        repair_passes,
        jd_cache_hit,
    )
    _log_usage_event(
        user_id,
        MetricEvent.GENERATION_COMPLETED.value,
        generation_id,
        {
            "final_score": final_score,
            "original_score": original_score,
            "duration_ms": duration_ms,
            "repair_passes": repair_passes,
            "jd_cache_hit": jd_cache_hit,
        },
    )


def record_generation_failed(
    generation_id: str,
    user_id: str,
    error_code: str,
    duration_ms: float,
) -> None:
    """Record a failed generation."""
    logger.warning(
        "metric.generation_failed generation_id=%s user_id=%s error_code=%s duration_ms=%.0f",
        generation_id,
        user_id,
        error_code,
        duration_ms,
    )
    _log_usage_event(
        user_id,
        MetricEvent.GENERATION_FAILED.value,
        generation_id,
        {"error_code": error_code, "duration_ms": duration_ms},
    )


def record_generation_cancelled(generation_id: str, user_id: str) -> None:
    """Record a cancelled generation."""
    logger.info("metric.generation_cancelled generation_id=%s user_id=%s", generation_id, user_id)
    _log_usage_event(user_id, MetricEvent.GENERATION_CANCELLED.value, generation_id, {})


def record_generation_rate_limited(
    user_id: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a blocked generation attempt without storing private payload data."""
    safe_metadata = {"reason": reason, **(metadata or {})}
    logger.warning(
        "metric.generation_rate_limited user_id=%s reason=%s",
        user_id,
        reason,
    )
    try:
        get_supabase_service().log_usage_event(
            user_id=user_id,
            event_type=MetricEvent.GENERATION_RATE_LIMITED.value,
            metadata=safe_metadata,
        )
    except Exception as exc:
        logger.debug(
            "metric.supabase_write_failed event=%s error=%s",
            MetricEvent.GENERATION_RATE_LIMITED.value,
            exc,
        )


def record_export_event(export_type: str, generation_id: str, user_id: str) -> None:
    """Record a PDF or DOCX export event."""
    logger.info(
        "metric.export export_type=%s generation_id=%s user_id=%s",
        export_type,
        generation_id,
        user_id,
    )
    _log_usage_event(user_id, export_type, generation_id, {})


def record_gemini_event(event: MetricEvent, attempt: int = 0) -> None:
    """Record Gemini API events for rate monitoring."""
    logger.info("metric.gemini event=%s attempt=%d", event.value, attempt)


def _log_usage_event(user_id: str, event_type: str, generation_id: str, metadata: dict[str, Any]) -> None:
    try:
        get_supabase_service().log_usage_event(
            user_id=user_id,
            event_type=event_type,
            generation_id=generation_id,
            metadata=metadata,
        )
    except Exception as exc:
        logger.debug("metric.supabase_write_failed event=%s error=%s", event_type, exc)


def get_generation_metrics_last_24h() -> dict[str, Any]:
    """Return production generation metrics for the previous 24 hours."""
    rows = _fetch_recent_generations(hours=24)
    total = len(rows)
    completed = [row for row in rows if row.get("status") == "completed"]
    failed = [row for row in rows if row.get("status") == "failed"]
    cancelled = [row for row in rows if row.get("status") == "cancelled"]
    scores = [_score_from_row(row) for row in completed]
    scores = [score for score in scores if score is not None]

    user_counts: dict[str, int] = {}
    for row in rows:
        user_id = str(row.get("user_id") or "")
        if user_id:
            user_counts[user_id] = user_counts.get(user_id, 0) + 1

    return {
        "window_hours": 24,
        "generation_count": total,
        "completed_count": len(completed),
        "failed_count": len(failed),
        "cancelled_count": len(cancelled),
        "generation_success_rate": round((len(completed) / total) * 100, 1) if total else 0.0,
        "avg_ats_score": round(sum(scores) / len(scores), 1) if scores else None,
        "users_with_generation": len(user_counts),
        "users_with_first_generation": sum(1 for count in user_counts.values() if count == 1),
        "error_rate_by_code": _error_counts_from_usage_events(hours=24),
    }


def get_live_generation_counts() -> dict[str, int]:
    """Return current counts of generations in queued and running states."""
    try:
        svc = get_supabase_service()
        queued = _count_generations_by_status(svc, "queued")
        running = _count_generations_by_status(svc, "running")
        return {"queued": queued, "running": running}
    except Exception:
        return {"queued": 0, "running": 0}


def get_stale_generation_counts() -> dict[str, int]:
    """Return current counts of stale running and queued generations.

    Uses the same timeout as the sweeper config.
    """
    from app.infrastructure.repositories.generation_repository import GenerationRepository

    settings = get_settings()
    timeout = settings.STALE_GENERATION_TIMEOUT_MINUTES
    repo = GenerationRepository()
    try:
        stale_running = len(repo.list_stale_running_generations(timeout))
        stale_queued = len(repo.list_stale_queued_generations(timeout))
        return {"stale_running": stale_running, "stale_queued": stale_queued}
    except Exception:
        return {"stale_running": 0, "stale_queued": 0}


def get_export_counts(hours: int = 24) -> dict[str, int]:
    """Return counts of PDF and DOCX export events in the given window."""
    pdf = _count_usage_events_by_type(MetricEvent.PDF_EXPORT.value, hours)
    docx = _count_usage_events_by_type(MetricEvent.DOCX_EXPORT.value, hours)
    return {"pdf_export_count": pdf, "docx_export_count": docx, "window_hours": hours}


def get_average_generation_duration(hours: int = 24) -> dict[str, Any]:
    """Return average generation duration for completed generations."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        svc = get_supabase_service()
        response = svc._client.get(
            svc._table_url("resume_generations"),
            params={
                "select": "created_at,completed_at",
                "status": "eq.completed",
                "and": f"(completed_at.gte.{since.isoformat()},completed_at.not.is.null)",
                "limit": 1000,
            },
        )
        response.raise_for_status()
        rows = response.json()
    except Exception:
        return {"average_duration_ms": None, "sample_count": 0, "window_hours": hours}

    durations: list[float] = []
    for row in rows:
        created = row.get("created_at")
        completed = row.get("completed_at")
        if created and completed:
            try:
                c = datetime.fromisoformat(created)
                comp = datetime.fromisoformat(completed)
                durations.append((comp - c).total_seconds() * 1000)
            except (ValueError, TypeError):
                continue

    if not durations:
        return {"average_duration_ms": None, "sample_count": 0, "window_hours": hours}

    return {
        "average_duration_ms": round(sum(durations) / len(durations), 1),
        "sample_count": len(durations),
        "window_hours": hours,
    }


def get_gemini_error_count() -> dict[str, int]:
    """Return count of Gemini-related errors (retries + timeouts) in the last 24h."""
    retries = _count_usage_events_by_type(MetricEvent.GEMINI_RETRY.value, 24)
    timeouts = _count_usage_events_by_type(MetricEvent.GEMINI_TIMEOUT.value, 24)
    return {"gemini_retry_count": retries, "gemini_timeout_count": timeouts, "total_gemini_errors": retries + timeouts}


def _count_generations_by_status(svc, status: str) -> int:
    try:
        response = svc._client.get(
            svc._table_url("resume_generations"),
            params={
                "select": "id",
                "status": f"eq.{status}",
                "limit": 1,
            },
        )
        response.raise_for_status()
        rows = response.json()
        return len(rows) if isinstance(rows, list) else 0
    except Exception:
        return 0


def _count_usage_events_by_type(event_type: str, hours: int) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        svc = get_supabase_service()
        response = svc._client.get(
            svc._table_url("usage_events"),
            params={
                "select": "id",
                "event_type": f"eq.{event_type}",
                "created_at": f"gte.{since.isoformat()}",
                "limit": 1000,
            },
        )
        response.raise_for_status()
        rows = response.json()
        return len(rows) if isinstance(rows, list) else 0
    except Exception:
        return 0


def _fetch_recent_generations(hours: int) -> list[dict[str, Any]]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        svc = get_supabase_service()
        response = svc._client.get(
            svc._table_url("resume_generations"),
            params={
                "select": "id,user_id,status,ats_score_json,created_at,updated_at",
                "created_at": f"gte.{since.isoformat()}",
                "order": "created_at.desc",
                "limit": 1000,
            },
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise SupabaseDatabaseError("Failed to fetch generation metrics") from exc


def _error_counts_from_usage_events(hours: int) -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        svc = get_supabase_service()
        response = svc._client.get(
            svc._table_url("usage_events"),
            params={
                "select": "metadata_json,event_type,created_at",
                "event_type": f"eq.{MetricEvent.GENERATION_FAILED.value}",
                "created_at": f"gte.{since.isoformat()}",
                "limit": 1000,
            },
        )
        response.raise_for_status()
    except Exception:
        return {}

    counts: dict[str, int] = {}
    for row in response.json():
        metadata = row.get("metadata_json") or {}
        code = str(metadata.get("error_code") or "UNKNOWN")
        counts[code] = counts.get(code, 0) + 1
    return counts


def _score_from_row(row: dict[str, Any]) -> float | None:
    score_json = row.get("ats_score_json") or {}
    value = score_json.get("overall_score") if isinstance(score_json, dict) else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
