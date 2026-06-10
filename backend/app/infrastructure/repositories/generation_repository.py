"""
GenerationRepository: database boundary for the resume_generations table.

Wraps SupabaseService (low-level PostgREST adapter) with owner-scoped
read/write methods specific to resume generations. Use cases should depend
on this repository rather than calling SupabaseService directly.

SupabaseService = low-level DB adapter (raw PostgREST calls)
Repository      = table/use-case-specific database boundary (encapsulated queries)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from uuid import UUID

from app.schemas.supabase import (
    ResumeGenerationCreate,
    ResumeGenerationRecord,
    ResumeGenerationUpdate,
)
from app.services.generation_service import GenerationNotFoundError
from app.services.supabase_service import SupabaseService, get_supabase_service

logger = logging.getLogger(__name__)


class GenerationRepository:
    """Owner-scoped CRUD for the resume_generations table."""

    def __init__(self, supabase_service: SupabaseService | None = None):
        self._svc = supabase_service or get_supabase_service()

    # ── Create ──────────────────────────────────────────────────────────────

    def create(
        self,
        user_id: UUID | str,
        data: ResumeGenerationCreate | dict[str, Any],
    ) -> ResumeGenerationRecord:
        """Create a new resume generation row (owner-scoped)."""
        return self._svc.create_generation(user_id, data)

    # ── Read ────────────────────────────────────────────────────────────────

    def get_by_id(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
    ) -> ResumeGenerationRecord | None:
        """Retrieve a generation by ID, scoped to the owning user."""
        return self._svc.get_generation(user_id, generation_id)

    def assert_owner(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
    ) -> ResumeGenerationRecord:
        """Return the generation or raise if not found / not owned."""
        gen = self.get_by_id(user_id, generation_id)
        if gen is None:
            raise GenerationNotFoundError(
                f"Generation {generation_id} not found or not owned by user"
            )
        return gen

    def list_for_user(
        self,
        user_id: UUID | str,
        limit: int = 25,
        offset: int = 0,
    ) -> list[ResumeGenerationRecord]:
        """List generations for a user, most recent first."""
        return self._svc.list_generations(user_id, limit=limit, offset=offset)

    def count_for_user_since(
        self,
        user_id: UUID | str,
        since: datetime,
    ) -> int:
        """Count generations created by a user after a cutoff."""
        return self._svc.count_generations_for_user_since(user_id, since)

    def count_active_for_user(self, user_id: UUID | str) -> int:
        """Count queued/running generations for duplicate-click protection."""
        return self._svc.count_active_generations_for_user(user_id)

    # ── Update ──────────────────────────────────────────────────────────────

    def update(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        data: ResumeGenerationUpdate | dict[str, Any],
    ) -> ResumeGenerationRecord:
        """Update a generation row (owner-scoped)."""
        return self._svc.update_generation(user_id, generation_id, data)

    def update_status(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        status: str,
    ) -> ResumeGenerationRecord:
        """Set the generation status and touch updated_at."""
        return self._svc.update_generation(
            user_id,
            generation_id,
            ResumeGenerationUpdate(status=status, updated_at=datetime.now(timezone.utc)),
        )

    def mark_running(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
    ) -> ResumeGenerationRecord:
        """Convenience: set status to 'running'."""
        return self.update_status(user_id, generation_id, "running")

    def mark_completed(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        *,
        completed_at: datetime | None = None,
    ) -> ResumeGenerationRecord:
        """Set status to 'completed' with optional completion timestamp."""
        now = completed_at or datetime.now(timezone.utc)
        return self._svc.update_generation(
            user_id,
            generation_id,
            ResumeGenerationUpdate(
                status="completed",
                updated_at=now,
                completed_at=now,
            ),
        )

    def mark_failed(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        *,
        failure_reason: str | None = None,
        failure_code: str | None = None,
        failed_at: datetime | None = None,
    ) -> ResumeGenerationRecord:
        """Set status to 'failed' with optional failure details and timestamp."""
        now = failed_at or datetime.now(timezone.utc)
        return self._svc.update_generation(
            user_id,
            generation_id,
            ResumeGenerationUpdate(
                status="failed",
                updated_at=now,
                failed_at=now,
                failure_reason=failure_reason,
                failure_code=failure_code,
            ),
        )

    def update_progress(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        *,
        current_step: str | None = None,
        progress_percentage: int | None = None,
        progress_json: dict[str, Any] | None = None,
    ) -> ResumeGenerationRecord:
        """Update generation progress fields without changing status."""
        return self._svc.update_generation(
            user_id,
            generation_id,
            ResumeGenerationUpdate(
                current_step=current_step,
                progress_percentage=progress_percentage,
                progress_json=progress_json,
            ),
        )

    def archive_for_user(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
    ) -> ResumeGenerationRecord:
        """Soft-delete: set status to 'archived'."""
        return self.update_status(user_id, generation_id, "archived")

    # ── Stale generation recovery (internal/admin — no owner scoping) ────

    def list_stale_running_generations(
        self,
        timeout_minutes: int,
        limit: int = 50,
    ) -> list[ResumeGenerationRecord]:
        """Return generations stuck in 'running' longer than timeout_minutes.

        INTERNAL USE ONLY — no owner scoping. Used by the stale
        generation sweeper.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        return self._svc.list_generations_by_status("running", older_than=cutoff, limit=limit)

    def list_stale_queued_generations(
        self,
        timeout_minutes: int,
        limit: int = 50,
    ) -> list[ResumeGenerationRecord]:
        """Return generations stuck in 'queued' longer than timeout_minutes.

        INTERNAL USE ONLY — no owner scoping.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
        return self._svc.list_generations_by_status("queued", older_than=cutoff, limit=limit)

    def requeue_stale_generation(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        *,
        existing_progress: dict[str, Any] | None,
        reason: str,
        max_retries: int = 3,
    ) -> ResumeGenerationRecord:
        """Requeue a stale generation, incrementing retry_count in progress_json.

        If retry_count >= max_retries the generation is marked as failed instead.
        """
        retry_count = 0
        if existing_progress:
            retry_count = existing_progress.get("retry_count", 0)

        now = datetime.now(timezone.utc)
        progress_json: dict[str, Any] = dict(existing_progress or {})
        progress_json["retry_count"] = retry_count + 1
        progress_json["last_retry_reason"] = reason
        progress_json["last_retry_at"] = now.isoformat()

        if retry_count >= max_retries:
            return self.mark_failed(
                user_id,
                generation_id,
                failure_code="STALE_GENERATION",
                failure_reason="Generation did not complete after maximum retries. Please start a new generation.",
                failed_at=now,
            )

        return self._svc.update_generation(
            user_id,
            generation_id,
            ResumeGenerationUpdate(
                status="queued",
                updated_at=now,
                current_step="queued",
                progress_percentage=5,
                progress_json=progress_json,
            ),
        )

    def mark_stale_generation_failed(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        *,
        failure_code: str = "STALE_GENERATION",
        failure_reason: str = "Generation was marked as stale and failed. Please start a new generation.",
    ) -> ResumeGenerationRecord:
        """Mark a stale generation as failed with a safe user-facing message."""
        return self.mark_failed(
            user_id,
            generation_id,
            failure_code=failure_code,
            failure_reason=failure_reason,
        )


@lru_cache()
def get_generation_repository() -> GenerationRepository:
    return GenerationRepository()
