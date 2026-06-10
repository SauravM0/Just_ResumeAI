"""
SettingsRepository: database boundary for the user_settings table.

Wraps SupabaseService (low-level PostgREST adapter) to provide focused,
owner-scoped access to user settings. Use cases should depend on this
repository rather than calling SupabaseService directly.

SupabaseService = low-level DB adapter (raw PostgREST calls)
Repository      = table/use-case-specific database boundary (encapsulated queries)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID

from app.schemas.supabase import (
    SettingsUpdateRequest,
    UserSettingsRecord,
)
from app.services.supabase_service import SupabaseService, get_supabase_service

logger = logging.getLogger(__name__)


class SettingsRepository:
    """Owner-scoped CRUD for the user_settings table."""

    def __init__(self, supabase_service: SupabaseService | None = None):
        self._svc = supabase_service or get_supabase_service()

    def get_or_create(self, user_id: UUID | str) -> UserSettingsRecord:
        """Return existing settings or create with defaults."""
        return self._svc.get_or_create_settings(user_id)

    def update(
        self,
        user_id: UUID | str,
        data: SettingsUpdateRequest | dict[str, object],
    ) -> UserSettingsRecord:
        """Upsert user settings."""
        return self._svc.update_settings(user_id, data)


@lru_cache()
def get_settings_repository() -> SettingsRepository:
    return SettingsRepository()
