"""
Queue backend factory — returns the appropriate queue implementation.

Usage (future, Phase 6C+):
    from app.application.jobs.generation_queue_factory import get_generation_queue

    queue = get_generation_queue()
    if queue is not None:
        queue.enqueue(payload)

In Phase 6B, this factory exists but is NOT called at runtime. The app
continues to use asyncio.create_task in generation_start.py.
"""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def get_generation_queue():
    """Return the generation queue backend based on configuration.

    Returns
    -------
    RedisGenerationQueue
        If GENERATION_EXECUTOR=worker and Redis is reachable.
    None
        If GENERATION_EXECUTOR=in-process (the default).
        Callers should treat None as "run in-process without a queue".

    Raises
    ------
    RuntimeError
        If GENERATION_EXECUTOR=worker but Redis connection fails.
    ValueError
        If GENERATION_EXECUTOR is set to an unknown value (validated at
        config load time, but also enforced here for safety).
    """
    settings = get_settings()
    executor = settings.GENERATION_EXECUTOR

    if executor == "in-process":
        logger.debug(
            "GENERATION_EXECUTOR=in-process — no queue backend initialised"
        )
        return None

    if executor == "worker":
        from app.infrastructure.queue.redis_generation_queue import (
            RedisGenerationQueue,
        )

        logger.info(
            "Initialising RedisGenerationQueue "
            "url=%s queue=%s max_retries=%d",
            settings.REDIS_URL,
            settings.GENERATION_QUEUE_NAME,
            settings.GENERATION_MAX_RETRIES,
        )
        return RedisGenerationQueue(
            redis_url=settings.REDIS_URL,
            queue_name=settings.GENERATION_QUEUE_NAME,
            max_retries=settings.GENERATION_MAX_RETRIES,
        )

    raise ValueError(
        f"Unknown GENERATION_EXECUTOR '{executor}'. "
        f"Allowed values: 'in-process', 'worker'."
    )
