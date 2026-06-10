import asyncio
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.utils.observability import (
    REQUEST_ID_HEADER,
    generation_id_from_path,
    get_request_id,
    get_request_user,
    log_event,
    normalize_request_id,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

settings = get_settings()

REQUIRED_EVERYWHERE = [
    "SUPABASE_URL",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_SERVICE_ROLE_KEY",
]


class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with body larger than max_content_size bytes."""

    def __init__(self, app, max_content_size: int | None = None):
        if max_content_size is None:
            max_content_size = settings.MAX_REQUEST_BODY_SIZE_KB * 1024
        super().__init__(app)
        self.max_content_size = max_content_size

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_content_size:
            max_kb = self.max_content_size // 1024
            return JSONResponse(
                _error_content(
                    "PAYLOAD_TOO_LARGE",
                    f"Request body too large. Maximum size is {max_kb}KB.",
                    get_request_id(request),
                ),
                status_code=413,
            )
        return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a safe request_id to request state and every response."""

    async def dispatch(self, request: Request, call_next):
        request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Log request latency and status for every endpoint."""

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            path = request.url.path
            user_id = get_request_user(request)
            should_log = (
                status_code >= 400
                or bool(user_id)
                or path.startswith("/api/v1/pipeline/generate")
            )
            if should_log and path not in {"/api/v1/health", "/api/v1/health/ready"}:
                log_event(
                    logger,
                    logging.INFO,
                    "http.request",
                    request_id=get_request_id(request),
                    method=request.method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round(duration_ms),
                    user_id=user_id,
                    generation_id=generation_id_from_path(path),
                )


def validate_environment():
    """Validate required environment variables on startup.

    Prints clear error messages without exposing secret values.
    Exits the process if critical variables are missing.
    """
    missing_required = settings.check_required(*REQUIRED_EVERYWHERE)
    if missing_required:
        logger.error(
            "Missing required environment variables: %s. "
            "The application cannot start without these. "
            "Add them to your .env file or deployment environment.",
            ", ".join(missing_required),
        )

    is_production = settings.APP_ENV.lower() in {"prod", "production"}

    if is_production:
        if settings.DEBUG:
            logger.warning("DEBUG is enabled in production. Set DEBUG=false for security.")

        cors_origins_str = str(settings.CORS_ORIGINS)
        if not settings.CORS_ORIGINS:
            logger.error(
                "CORS_ORIGINS is empty in production. "
                "Set CORS_ORIGINS to your frontend domain(s), e.g. https://my-app.vercel.app"
            )
            sys.exit(1)

        if "localhost" in cors_origins_str.lower() or "127.0.0.1" in cors_origins_str.lower():
            logger.error(
                "CORS_ORIGINS contains localhost/127.0.0.1 in production (%s). "
                "This is a security risk. Refusing to start.",
                cors_origins_str,
            )
            sys.exit(1)

    if missing_required:
        logger.error(
            "Startup aborted due to missing required environment variables. "
            "See errors above. No secrets have been printed."
        )
        sys.exit(1)


validate_environment()

limiter = Limiter(key_func=get_remote_address, default_limits=["200/hour"])


# ── Health probe state (must be defined BEFORE router import) ──────────────

_supabase_ok: bool = False


def get_supabase_health() -> bool:
    """Return cached Supabase health status (updated during lifespan)."""
    return _supabase_ok


from app.api.v1.router import api_router


# ── Background cleanup ─────────────────────────────────────────────────────

async def _run_periodic_cleanup():
    """Run LaTeX file cleanup every 6 hours in background."""
    while True:
        try:
            await asyncio.sleep(6 * 3600)  # 6 hours
            from app.scripts.cleanup_expired_files import run_cleanup

            deleted = await asyncio.to_thread(run_cleanup)
            logger.info("Periodic cleanup completed: %d file(s) deleted", deleted)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Cleanup task error: %s", e)


# ── Lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager handling startup and shutdown."""
    global _supabase_ok

    # ── Startup ────────────────────────────────────────────────────────
    os.makedirs(settings.LATEX_OUTPUT_DIR, exist_ok=True)

    # Probe Supabase connectivity
    try:
        from app.services.supabase_service import get_supabase_service
        svc = get_supabase_service()
        svc.list_generations("00000000-0000-0000-0000-000000000000", limit=1)
        _supabase_ok = True
        logger.info("Supabase health check: OK")
    except Exception as exc:
        _supabase_ok = False
        logger.warning("Supabase health check: FAILED — %s", exc)

    # Probe Redis connectivity (only when in worker mode)
    if settings.GENERATION_EXECUTOR == "worker":
        try:
            from app.services.queue_health import check_redis_reachable
            redis_result = check_redis_reachable()
            if redis_result.get("ok"):
                logger.info("Redis health check: OK")
            else:
                logger.warning(
                    "Redis health check: FAILED — %s. "
                    "Worker mode requires Redis. Set GENERATION_EXECUTOR=in-process "
                    "if Redis is not available.",
                    redis_result.get("detail", "unreachable"),
                )
        except Exception as exc:
            logger.warning("Redis health check: FAILED — %s", exc)
    else:
        logger.info("Redis health check: skipped (GENERATION_EXECUTOR=in-process)")

    logger.info(
        "app.start name=%s version=%s env=%s auth_mode=%s executor=%s cors_origins=%d gemini=%s supabase=%s",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.APP_ENV,
        settings.AUTH_ACCESS_MODE,
        settings.GENERATION_EXECUTOR,
        len(settings.CORS_ORIGINS),
        "configured" if settings.GEMINI_API_KEY else "missing",
        "configured" if settings.SUPABASE_URL else "missing",
    )

    # Start background cleanup task
    cleanup_task = asyncio.create_task(_run_periodic_cleanup())
    logger.info("Background file cleanup task started (6-hour interval)")

    yield  # ── App is running ──────────────────────────────────────────

    # ── Shutdown ───────────────────────────────────────────────────────
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("Application shutdown complete")


# ── Error response helpers ─────────────────────────────────────────────────

HTTP_STATUS_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
    504: "GATEWAY_TIMEOUT",
}


def _status_code_to_error_code(status_code: int) -> str:
    return HTTP_STATUS_ERROR_CODES.get(status_code, "UNKNOWN_ERROR")


def _error_content(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }


def _error_response(
    status_code: int,
    message: str,
    request_id: str,
    code: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_error_content(code or _status_code_to_error_code(status_code), message, request_id),
        headers={REQUEST_ID_HEADER: request_id} if request_id else None,
    )


# ── FastAPI app ────────────────────────────────────────────────────────────

openapi_tags = [
    {"name": "health", "description": "Health checks and service status"},
    {"name": "pipeline", "description": "Resume generation pipeline endpoints (blocking and SSE streaming)"},
    {"name": "profile", "description": "User master profile management and source resume uploads"},
    {"name": "job-description", "description": "Job description analysis and structured extraction"},
    {"name": "resume", "description": "Resume access, editing, validation, and file download"},
    {"name": "cover-letter", "description": "Cover letter generation and editing"},
    {"name": "history", "description": "Generation history listing and detail"},
    {"name": "generations", "description": "Raw generation record access"},
    {"name": "settings", "description": "User preferences and configuration"},
]

app = FastAPI(
    title="JustResume AI API",
    description=(
        "AI-powered ATS-optimised resume generation API. "
        "Analyse job descriptions, generate tailored resumes, "
        "optimise for ATS keyword scoring, and download PDF/DOCX exports."
    ),
    version=settings.APP_VERSION,
    lifespan=lifespan,
    openapi_tags=openapi_tags,
    docs_url="/docs" if not (settings.APP_ENV in {"prod", "production"} and not settings.DEBUG) else None,
    redoc_url=None,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    request_id = get_request_id(request)
    return _error_response(
        status_code=429,
        message="Too many requests. Please retry later.",
        request_id=request_id,
        code="RATE_LIMITED",
    )


# ── Global exception handlers ──────────────────────────────────────────────


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions and return a standardised error response."""
    request_id = get_request_id(request)
    log_event(
        logger,
        logging.ERROR,
        "http.unhandled_exception",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        user_id=get_request_user(request),
        generation_id=generation_id_from_path(request.url.path),
        error_type=type(exc).__name__,
    )
    logger.exception("Unhandled exception request_id=%s method=%s path=%s", request_id, request.method, request.url.path)

    # Only expose internal details when explicitly configured (dev environments)
    expose_details = settings.EXPOSE_ERROR_DETAILS and settings.DEBUG
    message = (
        f"An unexpected error occurred: {exc}"
        if expose_details
        else "An unexpected error occurred. Please retry."
    )
    return _error_response(
        status_code=500,
        message=message,
        request_id=request_id,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Convert HTTPExceptions into the standardised error format.

    Internal details are only exposed when EXPOSE_ERROR_DETAILS + DEBUG are enabled.
    """
    expose_details = settings.EXPOSE_ERROR_DETAILS and settings.DEBUG
    request_id = get_request_id(request)
    message = (
        exc.detail
        if isinstance(exc.detail, str)
        else str(exc.detail)
    )
    # Sanitise 500 messages to avoid leaking internals
    if exc.status_code == 500 and not expose_details:
        message = "An unexpected error occurred. Please retry."
    return _error_response(
        status_code=exc.status_code,
        message=message,
        request_id=request_id,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = get_request_id(request)
    details = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", []) if part != "body")
        msg = str(error.get("msg", "Invalid value"))
        details.append(f"{loc or 'request'}: {msg}")
    message = "\n".join(details[:10]) or "Request validation failed."
    log_event(
        logger,
        logging.INFO,
        "http.validation_error",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        user_id=get_request_user(request),
        generation_id=generation_id_from_path(request.url.path),
    )
    return _error_response(
        status_code=422,
        message=message,
        request_id=request_id,
        code="VALIDATION_ERROR",
    )


# ── Middleware ──────────────────────────────────────────────────────────────

# Content size check must run first (outermost middleware)
app.add_middleware(ContentSizeLimitMiddleware, max_content_size=settings.MAX_REQUEST_BODY_SIZE_KB * 1024)

app.add_middleware(SlowAPIMiddleware)

app.add_middleware(RequestTimingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=[
        "Content-Disposition",
        "X-Compile-Warnings",
        "X-Regenerated",
        "X-PDF-Page-Count",
        "X-Resume-Compressed",
        "X-Compression-Actions",
        "X-PDF-Inspection-Warnings",
        "X-Request-ID",
        "X-PDF-Failed",
        "X-User-Message",
        "X-Validation-Repaired",
        "X-Validation-Warnings",
    ],
)

app.add_middleware(RequestIDMiddleware)

app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    reload_enabled = settings.DEBUG and not (settings.APP_ENV.lower() in {"prod", "production"})
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload_enabled)
