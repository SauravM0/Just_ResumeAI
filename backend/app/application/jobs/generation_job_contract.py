"""
Generation job contract — defines the shape of queueable generation work.

This module is the contract between the API service (which enqueues) and the
worker service (which executes). It is safe to import in both processes.

No queue backend (Redis, Celery, RQ, Dramatiq) is imported here. The runtime
in Phase 6 still uses in-process asyncio.create_task. This contract exists so
that the migration path is clearly defined and type-checked before dependencies
are introduced.

Usage (future):
    from app.application.jobs.generation_job_contract import (
        GenerationJobPayload,
        GenerationJobResult,
        GenerationQueue,
    )

    # API service
    queue: GenerationQueue = get_queue_backend()
    job_id = queue.enqueue(payload)

    # Worker service
    payload = queue.dequeue()
    result = run_generation(payload)
    queue.complete(job_id, result)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


# ── Job Payload ──────────────────────────────────────────────────────────────


@dataclass
class GenerationJobPayload:
    """
    Everything a worker needs to run a full generation pipeline.

    This is serialised into the queue backend (JSON for Redis, pickle for
    Celery/RQ, etc.). Keep fields JSON-serialisable.

    No secrets, API keys, or access tokens are stored in this payload.
    The worker reconstructs domain objects (MasterProfile, SanitizationResult)
    from the serialised JSON fields.
    """

    generation_id: str
    user_id: str
    raw_jd_text: str
    clean_jd_text: str
    sanitization_json: dict[str, Any] | None = None  # serialised JDSanitizationResult
    profile_json: dict[str, Any] | None = None  # serialised MasterProfile
    target_pages: int = 1
    allow_two_pages_for_senior: bool = True
    generate_pdf: bool = True
    target_ats_score: float = 0.95
    max_repair_attempts: int = 7
    emphasis: str | None = None
    additional_alignment_text: str | None = None
    ats_optimization_mode: str = "aggressive"
    request_id: str | None = None


# ── Job Result ───────────────────────────────────────────────────────────────


@dataclass
class GenerationJobResult:
    """
    Outcome of a generation job, persisted to the queue backend for
    optional post-processing (logging, webhooks, notifications).
    """

    generation_id: str
    success: bool
    final_score: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: float = 0.0

    # Phase 5 progress fields that were durable-persisted during execution
    final_current_step: str = "complete" if True else "error"
    final_progress_percentage: int = 100


# ── Queue Interface (Protocol) ───────────────────────────────────────────────


class GenerationQueue(Protocol):
    """
    Abstract queue interface for generation jobs.

    Concrete implementations (Redis-backed, DB-backed, etc.) will implement
    this protocol. The rest of the application depends on this interface,
    not on any specific queue backend.
    """

    def enqueue(
        self,
        payload: GenerationJobPayload,
        *,
        priority: int = 0,
        max_retries: int = 3,
    ) -> str:
        """Enqueue a generation job. Returns a unique job ID."""
        ...

    def dequeue(self, *, timeout: float = 5.0) -> tuple[str, GenerationJobPayload] | None:
        """Dequeue the next available job. Returns (job_id, payload) or None."""
        ...

    def complete(self, job_id: str, result: GenerationJobResult) -> None:
        """Mark a job as completed and store its result."""
        ...

    def fail(self, job_id: str, error_code: str, error_message: str) -> None:
        """Mark a job as failed with an error code and message."""
        ...

    def heartbeat(self, job_id: str, ttl: int = 60) -> None:
        """Refresh the heartbeat timestamp for a running job."""
        ...

    def get_dead_jobs(self, stale_threshold_seconds: int = 300) -> list[str]:
        """Return job IDs whose heartbeat has expired (stale running jobs)."""
        ...

    def requeue(self, job_id: str) -> None:
        """Re-queue a dead job for retry."""
        ...


# ── Placeholder (current in-process runtime) ─────────────────────────────────


# Bridge function used by generation_start.py when GENERATION_EXECUTOR=worker.
# Phase 6D wired the real queue.enqueue() behind this function.
# When GENERATION_EXECUTOR=in-process, generation_start.py uses the
# asyncio.create_task path directly and this function is NOT called.
def enqueue_generation_job(payload: GenerationJobPayload) -> str:
    """
    Enqueue a generation job to the configured backend or log in-process.

    When GENERATION_EXECUTOR=worker, this enqueues via Redis/RQ.
    When GENERATION_EXECUTOR=in-process (default), this logs and returns
    the generation_id (the caller runs asyncio.create_task directly).

    Returns payload.generation_id so the API response does not change.
    """
    from app.config import get_settings

    settings = get_settings()
    if settings.GENERATION_EXECUTOR == "worker":
        from app.application.jobs.generation_queue_factory import get_generation_queue

        queue = get_generation_queue()
        job_id = queue.enqueue(payload)
        return job_id

    import logging

    logging.getLogger(__name__).info(
        "[in-process] enqueue_generation_job generation_id=%s "
        "(placeholder — job will run in current process)",
        payload.generation_id,
    )
    return payload.generation_id
