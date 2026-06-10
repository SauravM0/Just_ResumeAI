"""
UsageRepository: best-effort database logging to the usage_events table.

Wraps SupabaseService (low-level PostgREST adapter) with a guarantee that
logging failures never propagate to callers. Usage logging is best-effort:
if the database is unavailable or the write fails, the error is logged and
suppressed.

SupabaseService = low-level DB adapter (raw PostgREST calls)
Repository      = table/use-case-specific database boundary (encapsulated queries)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any
from uuid import UUID

from app.services.supabase_service import SupabaseService, get_supabase_service

logger = logging.getLogger(__name__)


class UsageRepository:
    """Best-effort logging to usage_events. Never fails the calling request."""

    def __init__(self, supabase_service: SupabaseService | None = None):
        self._svc = supabase_service or get_supabase_service()

    def log(
        self,
        user_id: UUID | str,
        event_type: str,
        metadata: dict[str, Any] | None = None,
        generation_id: UUID | str | None = None,
    ) -> None:
        """Record a usage event. Failures are logged but not propagated."""
        try:
            self._svc.log_usage_event(
                user_id=user_id,
                event_type=event_type,
                metadata=metadata,
                generation_id=generation_id,
            )
        except Exception:
            logger.exception(
                "Usage logging failed (suppressed) event=%s user=%s",
                event_type,
                user_id,
            )


@lru_cache()
def get_usage_repository() -> UsageRepository:
    return UsageRepository()
