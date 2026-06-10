"""
ProfileRepository: database boundary for user_profiles, source_resumes,
and profile_embeddings tables.

Wraps SupabaseService (low-level PostgREST adapter) to provide focused,
owner-scoped access to profile data. Use cases and services should consider
depending on this repository rather than calling SupabaseService directly.

SupabaseService = low-level DB adapter (raw PostgREST calls)
Repository      = table/use-case-specific database boundary (encapsulated queries)
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any
from uuid import UUID

from app.schemas.supabase import (
    JsonObject,
    SourceResumeCreate,
    SourceResumeRecord,
    UserProfileRecord,
)
from app.services.supabase_service import SupabaseService, get_supabase_service

logger = logging.getLogger(__name__)


class ProfileRepository:
    """Owner-scoped CRUD for user_profiles, source_resumes, and embeddings."""

    def __init__(self, supabase_service: SupabaseService | None = None):
        self._svc = supabase_service or get_supabase_service()

    # ── User Profile ────────────────────────────────────────────────────────

    def get_or_create(self, user_id: UUID | str) -> UserProfileRecord:
        """Return existing profile or create an empty one."""
        return self._svc.get_or_create_profile(user_id)

    def update(
        self,
        user_id: UUID | str,
        profile_json: JsonObject,
        profile_completion_score: int | None = None,
    ) -> UserProfileRecord:
        """Upsert profile JSON and optional completion score."""
        return self._svc.update_profile(user_id, profile_json, profile_completion_score)

    # ── Profile Embeddings (RAG) ────────────────────────────────────────────

    def replace_embeddings(
        self,
        user_id: UUID | str,
        rows: list[dict[str, Any]],
    ) -> int:
        """Replace all profile embedding rows for a user."""
        return self._svc.replace_profile_embeddings(user_id, rows)

    def count_embeddings(self, user_id: UUID | str) -> int:
        """Return the number of stored embedding chunks for a user."""
        return self._svc.count_profile_embeddings(user_id)

    def match_chunks(
        self,
        *,
        user_id: UUID | str,
        query_embedding: list[float],
        match_count: int = 3,
        similarity_threshold: float = 0.55,
    ) -> list[dict[str, Any]]:
        """Run pgvector similarity search against profile chunks."""
        return self._svc.match_profile_chunks(
            user_id=user_id,
            query_embedding=query_embedding,
            match_count=match_count,
            similarity_threshold=similarity_threshold,
        )

    # ── Source Resumes ──────────────────────────────────────────────────────

    def create_source_resume(
        self,
        user_id: UUID | str,
        data: SourceResumeCreate | dict[str, Any],
    ) -> SourceResumeRecord:
        """Store an uploaded source resume, deactivating previous active ones."""
        return self._svc.create_source_resume(user_id, data)

    def list_source_resumes(self, user_id: UUID | str) -> list[SourceResumeRecord]:
        """List active source resumes for a user."""
        return self._svc.list_source_resumes(user_id)

    def activate_source_resume(
        self,
        user_id: UUID | str,
        source_resume_id: UUID | str,
    ) -> SourceResumeRecord:
        """Set a source resume as active, deactivating others."""
        return self._svc.activate_source_resume(user_id, source_resume_id)


@lru_cache()
def get_profile_repository() -> ProfileRepository:
    return ProfileRepository()
