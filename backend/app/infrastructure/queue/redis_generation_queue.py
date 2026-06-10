"""
Redis/RQ-based generation queue implementation.

Satisfies the GenerationQueue protocol defined in
app.application.jobs.generation_job_contract.

This module has a hard dependency on Redis and RQ. It should only be imported
and instantiated when GENERATION_EXECUTOR=worker.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import redis as redis_lib
from rq import Queue as RQQueue, Retry
from rq.job import Job as RQJob

from app.application.jobs.generation_job_contract import (
    GenerationJobPayload,
    GenerationJobResult,
)

logger = logging.getLogger(__name__)


class RedisGenerationQueue:
    """Generation queue backed by Redis via RQ.

    Satisfies the GenerationQueue protocol. Safe to construct and enqueue
    against without a running worker — jobs persist in Redis and are picked
    up once the worker service exists (Phase 6C+).

    Raises RuntimeError if Redis is unreachable at construction time.
    """

    def __init__(
        self,
        redis_url: str,
        queue_name: str = "generations",
        max_retries: int = 3,
    ) -> None:
        self.redis_url = redis_url
        self.queue_name = queue_name
        self.default_max_retries = max_retries

        try:
            self.redis = redis_lib.from_url(redis_url, decode_responses=False)
            self.redis.ping()
        except redis_lib.exceptions.ConnectionError as e:
            raise RuntimeError(
                f"Cannot connect to Redis at {redis_url}. "
                f"Ensure Redis is running or set "
                f"GENERATION_EXECUTOR=in-process. Error: {e}"
            ) from e

        self.queue = RQQueue(queue_name, connection=self.redis)

    def enqueue(
        self,
        payload: GenerationJobPayload,
        *,
        priority: int = 0,
        max_retries: int | None = None,
    ) -> str:
        max_retries = max_retries if max_retries is not None else self.default_max_retries
        from app.application.jobs.generation_job_worker import execute_generation_job

        job = self.queue.enqueue(
            execute_generation_job,
            args=(dataclasses.asdict(payload),),
            job_timeout=600,
            result_ttl=86_400,
            failure_ttl=86_400,
            retry=Retry(max=max_retries),
        )
        logger.info(
            "Enqueued generation job job_id=%s generation_id=%s queue=%s",
            job.id,
            payload.generation_id,
            self.queue_name,
        )
        return job.id

    def get_status(self, job_id: str) -> str | None:
        """Return the RQ job status string, or None if the job is unknown."""
        try:
            job = RQJob.fetch(job_id, connection=self.redis)
            return job.get_status()
        except Exception:
            return None

    def dequeue(
        self, *, timeout: float = 5.0
    ) -> tuple[str, GenerationJobPayload] | None:
        job = self.queue.dequeue(timeout=timeout)
        if job is None:
            return None
        payload_dict = job.args[0] if job.args else {}
        payload = GenerationJobPayload(**payload_dict)
        return (job.id, payload)

    def complete(self, job_id: str, result: GenerationJobResult) -> None:
        try:
            job = RQJob.fetch(job_id, connection=self.redis)
            job.meta["result"] = dataclasses.asdict(result)
            job.save_meta()
            logger.info(
                "Job completed job_id=%s success=%s",
                job_id,
                result.success,
            )
        except Exception:
            logger.exception("Failed to record completion for job %s", job_id)

    def fail(self, job_id: str, error_code: str, error_message: str) -> None:
        try:
            job = RQJob.fetch(job_id, connection=self.redis)
            job.meta["error_code"] = error_code
            job.meta["error_message"] = error_message
            job.save_meta()
            logger.warning(
                "Job failed job_id=%s code=%s", job_id, error_code
            )
        except Exception:
            logger.exception("Failed to record failure for job %s", job_id)

    def heartbeat(self, job_id: str, ttl: int = 60) -> None:
        self.redis.expire(f"rq:job:{job_id}", ttl)

    def get_dead_jobs(
        self, stale_threshold_seconds: int = 300
    ) -> list[str]:
        from rq.registry import StartedJobRegistry

        registry = StartedJobRegistry(
            self.queue_name, connection=self.redis
        )
        return registry.get_job_ids()

    def requeue(self, job_id: str) -> None:
        existing = RQJob.fetch(job_id, connection=self.redis)
        payload_dict = existing.args[0] if existing.args else {}
        from app.application.jobs.generation_job_worker import execute_generation_job

        new_job = self.queue.enqueue(
            execute_generation_job,
            args=(payload_dict,),
            job_timeout=600,
            result_ttl=86_400,
            failure_ttl=86_400,
            retry=Retry(max=self.default_max_retries),
        )
        logger.info(
            "Requeued job original=%s new=%s", job_id, new_job.id
        )
