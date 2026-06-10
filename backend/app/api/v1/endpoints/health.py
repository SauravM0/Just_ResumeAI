"""
Health check endpoint with detailed service status.

Phase 7 additions:
  - Redis/RQ reachability (only checked when GENERATION_EXECUTOR=worker).
  - Worker mode config validity.
  - Stale sweeper config status.
  - No secrets exposed in any response field.
"""

from pathlib import Path
import shutil
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.main import get_supabase_health

router = APIRouter(tags=["health"])

_settings = get_settings()


@router.get(
    "/health",
    response_model=dict,
    summary="Health check",
    description="Returns the current service status including version, environment,"
    " Supabase connectivity, Gemini API key configuration, Redis connectivity"
    " (worker mode only), and LaTeX tooling availability.",
)
async def health_check():
    """Enhanced health check with service dependency status."""
    checks = _service_checks()
    return {
        "status": "ok" if checks["ready"] else "degraded",
        "service": "justresume-api",
        "version": _settings.APP_VERSION,
        "environment": _settings.APP_ENV,
        **checks,
    }


@router.get(
    "/health/ready",
    response_model=dict,
    summary="Readiness check",
    description="Returns 200 only when critical production dependencies are configured."
    " In worker mode, Redis must also be reachable.",
)
async def readiness_check():
    checks = _service_checks()
    payload = {
        "status": "ready" if checks["ready"] else "not_ready",
        "service": "justresume-api",
        "version": _settings.APP_VERSION,
        **checks,
    }
    if not checks["ready"]:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=payload)
    return payload


def _service_checks() -> dict[str, Any]:
    supabase_ok = get_supabase_health()
    gemini_configured = bool(_settings.GEMINI_API_KEY)
    latex_template_dir_ok = Path(_settings.LATEX_TEMPLATE_DIR).exists()
    latex_output_dir_ok = Path(_settings.LATEX_OUTPUT_DIR).exists()
    pdflatex_available = shutil.which("pdflatex") is not None

    executor = _settings.GENERATION_EXECUTOR
    redis_reachable: bool | None = None
    worker_config_ok: bool = True
    if executor == "worker":
        from app.services.queue_health import check_redis_reachable
        redis_result = check_redis_reachable()
        redis_reachable = redis_result.get("ok", False)
        worker_config_ok = bool(_settings.REDIS_URL)
    sweeper_enabled = _settings.GENERATION_STALE_SWEEPER_ENABLED

    critical_ok = (
        supabase_ok
        and gemini_configured
        and latex_template_dir_ok
        and latex_output_dir_ok
    )

    if executor == "worker":
        critical_ok = critical_ok and bool(redis_reachable)

    return {
        "ready": critical_ok,
        "supabase": "ok" if supabase_ok else "error",
        "gemini": "configured" if gemini_configured else "missing",
        "latex_template_dir": "ok" if latex_template_dir_ok else "missing",
        "latex_output_dir": "ok" if latex_output_dir_ok else "missing",
        "pdflatex": "available" if pdflatex_available else "missing",
        "generation_executor": executor,
        "redis_reachable": redis_reachable if executor == "worker" else "not_required",
        "worker_config_valid": worker_config_ok,
        "stale_sweeper_enabled": sweeper_enabled,
    }
