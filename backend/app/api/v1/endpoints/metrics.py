"""Admin-only production metrics endpoint.

Phase 7: returns aggregate generation, export, queue, and sweeper metrics.
All values are aggregate counts — no sensitive user data is exposed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies.auth import CurrentUser, get_current_user
from app.services.metrics_service import (
    get_average_generation_duration,
    get_export_counts,
    get_gemini_error_count,
    get_generation_metrics_last_24h,
    get_live_generation_counts,
    get_stale_generation_counts,
)
from app.services.queue_health import get_queue_health_summary

router = APIRouter(prefix="/metrics", tags=["metrics"])

_settings = get_settings()


@router.get("", response_model=dict, summary="Production metrics dashboard")
async def read_generation_metrics(current_user: CurrentUser = Depends(get_current_user)):
    """Return aggregate production metrics for admin users.

    Includes generation counts, export counts, queue depth, and sweeper
    status. No user-identifiable or sensitive data is returned.
    """
    if not _is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

    window_hours = 24
    generation_metrics = get_generation_metrics_last_24h()
    live_counts = get_live_generation_counts()
    stale_counts = get_stale_generation_counts()
    export_counts = get_export_counts(hours=window_hours)
    avg_duration = get_average_generation_duration(hours=window_hours)
    gemini_errors = get_gemini_error_count()

    result = {
        "window_hours": window_hours,
        "generation_started_count": generation_metrics.get("generation_count", 0),
        "generation_completed_count": generation_metrics.get("completed_count", 0),
        "generation_failed_count": generation_metrics.get("failed_count", 0),
        "generation_cancelled_count": generation_metrics.get("cancelled_count", 0),
        "generation_success_rate": generation_metrics.get("generation_success_rate", 0.0),
        "average_generation_duration_ms": avg_duration.get("average_duration_ms"),
        "current_queued_generations": live_counts.get("queued", 0),
        "current_running_generations": live_counts.get("running", 0),
        "stale_running_count": stale_counts.get("stale_running", 0),
        "stale_queued_count": stale_counts.get("stale_queued", 0),
        "pdf_export_count": export_counts.get("pdf_export_count", 0),
        "docx_export_count": export_counts.get("docx_export_count", 0),
        "pdf_export_failure_count": 0,
        "gemini_error_count": gemini_errors.get("total_gemini_errors", 0),
    }

    if _settings.GENERATION_EXECUTOR == "worker":
        queue = get_queue_health_summary()
        result["queue_depth"] = queue.get("queue_length", 0)
        result["redis_reachable"] = queue.get("redis_reachable", False)
        result["queue_failed_job_count"] = queue.get("failed_job_count", 0)
        result["queue_started_job_count"] = queue.get("started_job_count", 0)

    return result


def _is_admin(user: CurrentUser) -> bool:
    claims = user.claims or {}
    app_metadata = claims.get("app_metadata") if isinstance(claims.get("app_metadata"), dict) else {}
    user_metadata = claims.get("user_metadata") if isinstance(claims.get("user_metadata"), dict) else {}
    roles = {
        str(claims.get("role") or "").casefold(),
        str(claims.get("user_role") or "").casefold(),
        str(app_metadata.get("role") or "").casefold(),
        str(user_metadata.get("role") or "").casefold(),
    }
    return "admin" in roles or "service_role" in roles or bool(app_metadata.get("is_admin"))
