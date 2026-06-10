"""
Stale generation sweeper — detects and recovers stuck generation jobs.

A generation is considered stale when its status is 'running' or 'queued'
and its updated_at timestamp is older than STALE_GENERATION_TIMEOUT_MINUTES.

The sweeper checks retry_count stored in progress_json and either:
  - Requeues the generation (retry_count < GENERATION_MAX_RETRIES)
  - Marks the generation as failed (retry_count >= GENERATION_MAX_RETRIES)

This module is opt-in and must be explicitly enabled via config or CLI flag.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.config import get_settings
from app.infrastructure.repositories.generation_repository import GenerationRepository

logger = logging.getLogger(__name__)

SAFE_STALE_FAILURE_MESSAGE = (
    "Generation was marked as stale and failed. "
    "Please start a new generation."
)


def sweep_stale_generations_once(
    *,
    timeout_minutes: int | None = None,
    max_retries: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Run one sweep cycle — detect and requeue/fail stale generations.

    Parameters
    ----------
    timeout_minutes : int or None
        Override the configured STALE_GENERATION_TIMEOUT_MINUTES.
    max_retries : int or None
        Override the configured GENERATION_MAX_RETRIES.
    dry_run : bool
        When True, log what would be done but do not modify any rows.

    Returns
    -------
    dict with keys:
        scanned_running, scanned_queued, requeued, failed, errors, duration_ms
    """
    _start = time.perf_counter()
    settings = get_settings()
    timeout = timeout_minutes or settings.STALE_GENERATION_TIMEOUT_MINUTES
    retries = max_retries or settings.GENERATION_MAX_RETRIES
    repo = GenerationRepository()

    result: dict[str, int] = {
        "scanned_running": 0,
        "scanned_queued": 0,
        "requeued": 0,
        "failed": 0,
        "errors": 0,
    }

    now = datetime.now(timezone.utc)
    logger.info(
        "stale_sweeper.run timeout=%dmin max_retries=%d dry_run=%s",
        timeout, retries, dry_run,
    )

    # ── Scan stale running ───────────────────────────────────────────────
    try:
        stale_running = repo.list_stale_running_generations(timeout)
        result["scanned_running"] = len(stale_running)
    except Exception as exc:
        logger.error("stale_sweeper.list_stale_running failed: %s", exc)
        result["errors"] += 1
        stale_running = []

    for gen in stale_running:
        try:
            _handle_stale_generation(
                repo, gen, retries, "STALE_RUNNING", dry_run, result,
            )
        except Exception as exc:
            logger.error(
                "stale_sweeper.handle_stale_running failed id=%s error=%s",
                gen.id, exc,
            )
            result["errors"] += 1

    # ── Scan stale queued ────────────────────────────────────────────────
    try:
        stale_queued = repo.list_stale_queued_generations(timeout)
        result["scanned_queued"] = len(stale_queued)
    except Exception as exc:
        logger.error("stale_sweeper.list_stale_queued failed: %s", exc)
        result["errors"] += 1
        stale_queued = []

    for gen in stale_queued:
        try:
            _handle_stale_generation(
                repo, gen, retries, "STALE_QUEUED", dry_run, result,
            )
        except Exception as exc:
            logger.error(
                "stale_sweeper.handle_stale_queued failed id=%s error=%s",
                gen.id, exc,
            )
            result["errors"] += 1

    duration_ms = (time.perf_counter() - _start) * 1000
    result["duration_ms"] = round(duration_ms, 1)
    logger.info(
        "stale_sweeper.complete scanned_running=%d scanned_queued=%d "
        "requeued=%d failed=%d errors=%d duration_ms=%.0f",
        result["scanned_running"],
        result["scanned_queued"],
        result["requeued"],
        result["failed"],
        result["errors"],
        duration_ms,
    )

    return result


def _handle_stale_generation(
    repo: GenerationRepository,
    gen: "ResumeGenerationRecord",
    max_retries: int,
    reason: str,
    dry_run: bool,
    result: dict[str, int],
) -> None:
    """Requeue or fail a single stale generation based on retry_count."""
    progress_json: dict | None = None
    if hasattr(gen, "progress_json") and gen.progress_json:
        progress_json = dict(gen.progress_json)

    retry_count = 0
    if progress_json:
        retry_count = progress_json.get("retry_count", 0)

    user_id = gen.user_id
    generation_id = gen.id

    if retry_count >= max_retries:
        logger.warning(
            "stale_sweeper.failing id=%s status=%s retry_count=%d/%d reason=%s",
            generation_id, gen.status, retry_count, max_retries, reason,
        )
        if not dry_run:
            repo.mark_stale_generation_failed(
                user_id,
                generation_id,
                failure_code=reason,
                failure_reason=SAFE_STALE_FAILURE_MESSAGE,
            )
        result["failed"] += 1
    else:
        logger.info(
            "stale_sweeper.requeueing id=%s status=%s retry_count=%d/%d reason=%s",
            generation_id, gen.status, retry_count, max_retries, reason,
        )
        if not dry_run:
            repo.requeue_stale_generation(
                user_id,
                generation_id,
                existing_progress=progress_json,
                reason=reason,
                max_retries=max_retries,
            )
        result["requeued"] += 1


# Lazy import to avoid runtime dependency on schemas at module level
from app.schemas.supabase import ResumeGenerationRecord
