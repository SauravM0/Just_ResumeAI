"""
Worker entrypoint for RQ-based generation queue processing.

Run with:          python -m app.worker
Check mode:        python -m app.worker --check
Debug logging:     python -m app.worker --debug

In Phase 6C, the worker CAN start, connect to Redis, and observe queue state,
but CANNOT execute real generation jobs. The callable stored in queued jobs
(_execute_generation_placeholder) raises NotImplementedError until Phase 6D
wires the real generation runner.

Requirements
------------
- GENERATION_EXECUTOR=worker must be set in .env (checked at startup).
- Redis must be reachable at REDIS_URL.
"""

from __future__ import annotations

import argparse
import logging
import sys
from urllib.parse import urlparse, urlunparse

import redis as redis_lib
from rq import Queue, Worker

from app.config import get_settings

logger = logging.getLogger(__name__)


# ── Logging ──────────────────────────────────────────────────────────────────


def _configure_logging(debug: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ── URL redaction (safe logging) ────────────────────────────────────────────


def _redact_redis_url(url: str) -> str:
    """Remove password from Redis URL for safe logging."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            parsed = parsed._replace(netloc=netloc)
            return urlunparse(parsed)
    except Exception:
        pass
    return url


# ── Validation ───────────────────────────────────────────────────────────────


def _validate_executor() -> None:
    """Exit with error if GENERATION_EXECUTOR != worker."""
    settings = get_settings()
    if settings.GENERATION_EXECUTOR != "worker":
        logger.error(
            "GENERATION_EXECUTOR=%s but worker requires 'worker'. "
            "Set GENERATION_EXECUTOR=worker in .env to start the worker.",
            settings.GENERATION_EXECUTOR,
        )
        sys.exit(1)


def _check_redis(redis_url: str) -> bool:
    """Ping Redis and return True if reachable."""
    try:
        conn = redis_lib.from_url(redis_url, decode_responses=False)
        ok = conn.ping()
        conn.close()
        return ok
    except redis_lib.exceptions.ConnectionError as e:
        logger.error("Redis unreachable at %s: %s", _redact_redis_url(redis_url), e)
        return False


# ── Check mode (dry-run) ────────────────────────────────────────────────────


def run_check() -> None:
    """Validate configuration and connectivity without starting the worker."""
    settings = get_settings()

    executor = settings.GENERATION_EXECUTOR
    queue_name = settings.GENERATION_QUEUE_NAME
    max_retries = settings.GENERATION_MAX_RETRIES
    redis_url = settings.REDIS_URL

    logger.info("Worker check — configuration:")
    logger.info("  GENERATION_EXECUTOR     = %s", executor)
    logger.info("  GENERATION_QUEUE_NAME   = %s", queue_name)
    logger.info("  GENERATION_MAX_RETRIES  = %d", max_retries)
    logger.info("  REDIS_URL               = %s", _redact_redis_url(redis_url))

    if executor == "worker":
        logger.info("  Redis ping ...")
        if not _check_redis(redis_url):
            logger.error("Redis is unreachable. Worker cannot start.")
            sys.exit(1)
        logger.info("  Redis ping — OK")
    else:
        logger.info(
            "  Mode: in-process (no Redis check needed). "
            "Set GENERATION_EXECUTOR=worker for queue mode."
        )

    logger.info("Worker configuration is valid.")
    sys.exit(0)


# ── Worker loop ──────────────────────────────────────────────────────────────


def run_worker() -> None:
    """Start the RQ worker process (blocks forever)."""
    settings = get_settings()

    logger.info(
        "Connecting to Redis at %s ...",
        _redact_redis_url(settings.REDIS_URL),
    )

    try:
        redis_conn = redis_lib.from_url(settings.REDIS_URL, decode_responses=False)
        redis_conn.ping()
    except redis_lib.exceptions.ConnectionError as e:
        logger.error(
            "Cannot connect to Redis at %s. "
            "Ensure Redis is running or set GENERATION_EXECUTOR=in-process. "
            "Error: %s",
            _redact_redis_url(settings.REDIS_URL),
            e,
        )
        sys.exit(1)

    queue = Queue(settings.GENERATION_QUEUE_NAME, connection=redis_conn)

    logger.info("Worker starting for queue '%s' ...", settings.GENERATION_QUEUE_NAME)
    logger.info(
        "IMPORTANT: Real generation execution is NOT wired in Phase 6C. "
        "Any jobs popped from the queue will fail with NotImplementedError. "
        "This is expected until Phase 6D wires the real generation runner."
    )
    logger.info("Worker entering work loop ...")

    worker = Worker([queue], connection=redis_conn)
    worker.work()

    logger.info("Worker shut down.")


# ── Entrypoint ───────────────────────────────────────────────────────────────


def main() -> None:
    _configure_logging()

    parser = argparse.ArgumentParser(
        description="JustResume AI generation worker process.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration and exit without starting the worker.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging.",
    )

    args = parser.parse_args()

    if args.debug:
        _configure_logging(debug=True)

    if args.check:
        run_check()

    _validate_executor()
    run_worker()


if __name__ == "__main__":
    main()
