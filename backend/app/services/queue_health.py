"""Redis/RQ queue health helper for monitoring and readiness checks.

Safe to import and call even when Redis is unreachable or RQ is not in use.
All methods catch exceptions and return dicts with an ``ok`` bool and details.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


def check_redis_reachable() -> dict[str, Any]:
    """Ping Redis and return health status.

    Returns dict with ``ok`` (bool) and either ``detail`` or ``error``.
    """
    import redis as redis_lib

    settings = get_settings()
    url = settings.REDIS_URL
    try:
        conn = redis_lib.from_url(url, decode_responses=False)
        ok = conn.ping()
        conn.close()
        return {"ok": ok, "detail": "connected" if ok else "ping_failed"}
    except redis_lib.exceptions.ConnectionError as e:
        return {"ok": False, "error": "redis_unreachable", "detail": str(e)}
    except Exception as e:
        return {"ok": False, "error": "redis_check_failed", "detail": str(e)}


def check_queue_length() -> dict[str, Any]:
    """Return the current generation queue depth.

    Returns dict with ``ok`` (bool) and ``queue_length`` (int).
    Returns ``queue_length=0`` with ``ok=False`` if Redis is unreachable.
    """
    import redis as redis_lib
    from rq import Queue

    settings = get_settings()
    try:
        conn = redis_lib.from_url(settings.REDIS_URL, decode_responses=False)
        conn.ping()
        queue = Queue(settings.GENERATION_QUEUE_NAME, connection=conn)
        length = queue.count
        conn.close()
        return {"ok": True, "queue_length": length}
    except Exception as e:
        logger.debug("queue_health.queue_length unavailable: %s", e)
        return {"ok": False, "queue_length": 0, "detail": str(e)}


def check_failed_job_count() -> dict[str, Any]:
    """Return count of jobs in the failed job registry.

    Returns dict with ``ok`` (bool) and ``failed_count`` (int).
    """
    import redis as redis_lib
    from rq.registry import FailedJobRegistry

    settings = get_settings()
    try:
        conn = redis_lib.from_url(settings.REDIS_URL, decode_responses=False)
        conn.ping()
        registry = FailedJobRegistry(settings.GENERATION_QUEUE_NAME, connection=conn)
        count = registry.count
        conn.close()
        return {"ok": True, "failed_count": count}
    except Exception as e:
        logger.debug("queue_health.failed_job_count unavailable: %s", e)
        return {"ok": False, "failed_count": 0, "detail": str(e)}


def check_started_job_count() -> dict[str, Any]:
    """Return count of jobs in the started job registry.

    Returns dict with ``ok`` (bool) and ``started_count`` (int).
    """
    import redis as redis_lib
    from rq.registry import StartedJobRegistry

    settings = get_settings()
    try:
        conn = redis_lib.from_url(settings.REDIS_URL, decode_responses=False)
        conn.ping()
        registry = StartedJobRegistry(settings.GENERATION_QUEUE_NAME, connection=conn)
        count = registry.count
        conn.close()
        return {"ok": True, "started_count": count}
    except Exception as e:
        logger.debug("queue_health.started_job_count unavailable: %s", e)
        return {"ok": False, "started_count": 0, "detail": str(e)}


def get_queue_health_summary() -> dict[str, Any]:
    """Return a summary of all queue health checks.

    Returns dict with ``ok`` (bool, True when all available checks pass),
    ``redis_reachable``, ``queue_length``, ``failed_job_count``,
    ``started_job_count``.
    """
    redis_check = check_redis_reachable()
    if not redis_check.get("ok"):
        return {
            "ok": False,
            "redis_reachable": False,
            "queue_length": 0,
            "failed_job_count": 0,
            "started_job_count": 0,
        }

    length = check_queue_length()
    failed = check_failed_job_count()
    started = check_started_job_count()

    return {
        "ok": True,
        "redis_reachable": True,
        "queue_length": length.get("queue_length", 0),
        "failed_job_count": failed.get("failed_count", 0),
        "started_job_count": started.get("started_count", 0),
    }
