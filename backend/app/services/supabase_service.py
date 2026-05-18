"""Supabase service-role persistence foundation."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import logging
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings
from app.schemas.supabase import (
    AllowedUserRecord,
    GeneratedFileCreate,
    GeneratedFileRecord,
    JsonObject,
    ResumeGenerationCreate,
    ResumeGenerationRecord,
    ResumeGenerationUpdate,
    SettingsUpdateRequest,
    UsageEventRecord,
    UserProfileRecord,
    UserSettingsRecord,
)

logger = logging.getLogger(__name__)


class SupabaseServiceError(RuntimeError):
    """Base error for Supabase service failures."""


class SupabaseServiceConfigError(SupabaseServiceError):
    """Raised when required backend-only Supabase config is missing."""


class SupabaseDatabaseError(SupabaseServiceError):
    """Raised when a Supabase database operation fails."""


class SupabaseService:
    """Thin typed wrapper around Supabase service-role database operations."""

    def __init__(self, client: httpx.Client | None = None):
        settings = get_settings()
        self._rest_url = self._build_rest_url(settings.SUPABASE_URL)
        self._client = client or self._build_client(settings.SUPABASE_SERVICE_ROLE_KEY)

    def get_or_create_profile(self, user_id: UUID | str) -> UserProfileRecord:
        user_id_str = _uuid_str(user_id)
        existing = self._select_maybe_single(
            "user_profiles",
            filters={"user_id": user_id_str},
        )
        if existing:
            return UserProfileRecord.model_validate(existing)

        created = self._insert_single(
            "user_profiles",
            {
                "user_id": user_id_str,
                "profile_json": {},
                "profile_completion_score": 0,
            },
        )
        return UserProfileRecord.model_validate(created)

    def update_profile(
        self,
        user_id: UUID | str,
        profile_json: JsonObject,
        profile_completion_score: int | None = None,
    ) -> UserProfileRecord:
        user_id_str = _uuid_str(user_id)
        payload: dict[str, Any] = {
            "user_id": user_id_str,
            "profile_json": profile_json,
        }
        if profile_completion_score is not None:
            payload["profile_completion_score"] = profile_completion_score

        updated = self._upsert_single(
            "user_profiles",
            payload,
            on_conflict="user_id",
        )
        if updated is None:
            raise SupabaseDatabaseError("Failed to update Supabase profile")
        return UserProfileRecord.model_validate(updated)

    def create_generation(
        self,
        user_id: UUID | str,
        data: ResumeGenerationCreate | dict[str, Any],
    ) -> ResumeGenerationRecord:
        user_id_str = _uuid_str(user_id)
        payload = _model_payload(data)
        profile_id = payload.get("profile_id")
        if profile_id is not None:
            profile = self._select_maybe_single(
                "user_profiles",
                filters={"id": _uuid_str(profile_id), "user_id": user_id_str},
            )
            if profile is None:
                raise SupabaseDatabaseError("Profile not found for generation owner")
        payload["user_id"] = user_id_str
        created = self._insert_single("resume_generations", payload)
        return ResumeGenerationRecord.model_validate(created)

    def update_generation(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        data: ResumeGenerationUpdate | dict[str, Any],
    ) -> ResumeGenerationRecord:
        updated = self._update_single(
            "resume_generations",
            _model_payload(data),
            filters={"user_id": _uuid_str(user_id), "id": _uuid_str(generation_id)},
        )
        if updated is None:
            raise SupabaseDatabaseError("Supabase generation not found or not updated")
        return ResumeGenerationRecord.model_validate(updated)

    def get_generation(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
    ) -> ResumeGenerationRecord | None:
        row = self._select_maybe_single(
            "resume_generations",
            filters={"user_id": _uuid_str(user_id), "id": _uuid_str(generation_id)},
        )
        return ResumeGenerationRecord.model_validate(row) if row else None

    def list_generations(
        self,
        user_id: UUID | str,
        limit: int = 25,
        offset: int = 0,
    ) -> list[ResumeGenerationRecord]:
        try:
            response = self._client.get(
                self._table_url("resume_generations"),
                params={
                    "select": "*",
                    "user_id": f"eq.{_uuid_str(user_id)}",
                    "order": "created_at.desc",
                    "limit": limit,
                    "offset": offset,
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase list_generations failed")
            raise SupabaseDatabaseError("Failed to list Supabase generations") from exc

        return [ResumeGenerationRecord.model_validate(row) for row in response.json()]

    def create_file_record(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
        data: GeneratedFileCreate | dict[str, Any],
    ) -> GeneratedFileRecord:
        if self.get_generation(user_id, generation_id) is None:
            raise SupabaseDatabaseError("Generation not found for file owner")
        payload = _model_payload(data)
        payload["user_id"] = _uuid_str(user_id)
        payload["generation_id"] = _uuid_str(generation_id)
        payload["deleted_at"] = None
        created = self._upsert_single("generated_files", payload, on_conflict="storage_path")
        return GeneratedFileRecord.model_validate(created)

    def log_usage_event(
        self,
        user_id: UUID | str,
        event_type: str,
        metadata: JsonObject | None = None,
        generation_id: UUID | str | None = None,
    ) -> UsageEventRecord:
        payload: dict[str, Any] = {
            "user_id": _uuid_str(user_id),
            "event_type": event_type,
            "metadata_json": metadata or {},
        }
        if generation_id is not None:
            payload["generation_id"] = _uuid_str(generation_id)

        created = self._insert_single("usage_events", payload)
        return UsageEventRecord.model_validate(created)

    def get_generation_files(
        self,
        user_id: UUID | str,
        generation_id: UUID | str,
    ) -> list[GeneratedFileRecord]:
        """Get all generated files for a specific generation."""
        try:
            response = self._client.get(
                self._table_url("generated_files"),
                params={
                    "select": "*",
                    "user_id": f"eq.{_uuid_str(user_id)}",
                    "generation_id": f"eq.{_uuid_str(generation_id)}",
                    "deleted_at": "is.null",
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase get_generation_files failed")
            raise SupabaseDatabaseError("Failed to get generated files") from exc

        return [GeneratedFileRecord.model_validate(row) for row in response.json()]

    def mark_file_deleted(
        self,
        file_id: UUID | str,
        deleted_at: datetime,
        user_id: UUID | str | None = None,
    ) -> None:
        filters: dict[str, Any] = {"id": _uuid_str(file_id)}
        if user_id is not None:
            filters["user_id"] = _uuid_str(user_id)
        self._update_single(
            "generated_files",
            {"deleted_at": deleted_at.isoformat()},
            filters,
        )

    def get_or_create_settings(self, user_id: UUID | str) -> UserSettingsRecord:
        user_id_str = _uuid_str(user_id)
        existing = self._select_maybe_single(
            "user_settings",
            filters={"user_id": user_id_str},
        )
        if existing:
            return UserSettingsRecord.model_validate(existing)

        created = self._insert_single(
            "user_settings",
            {
                "user_id": user_id_str,
                "target_resume_pages": 1,
                "preferred_tone": "professional",
            },
        )
        return UserSettingsRecord.model_validate(created)

    def update_settings(
        self,
        user_id: UUID | str,
        data: SettingsUpdateRequest | dict[str, Any],
    ) -> UserSettingsRecord:
        user_id_str = _uuid_str(user_id)
        payload = _model_payload(data)
        payload["user_id"] = user_id_str
        updated = self._upsert_single("user_settings", payload, on_conflict="user_id")
        if updated is None:
            raise SupabaseDatabaseError("Failed to upsert Supabase settings")
        return UserSettingsRecord.model_validate(updated)

    def get_allowed_user(self, email: str) -> AllowedUserRecord | None:
        """Return an active allowlist row for backend-only access checks."""
        normalized_email = email.strip().lower()
        if not normalized_email:
            return None

        row = self._select_maybe_single(
            "allowed_users",
            filters={"email": normalized_email, "is_active": True},
        )
        return AllowedUserRecord.model_validate(row) if row else None

    def is_allowed_user(self, email: str) -> bool:
        """Check whether an email is active in the backend-only allowlist."""
        return self.get_allowed_user(email) is not None

    @staticmethod
    def _build_rest_url(url: str) -> str:
        if not url:
            raise SupabaseServiceConfigError("SUPABASE_URL is required")
        return f"{url.rstrip('/')}/rest/v1"

    @staticmethod
    def _build_client(service_role_key: str) -> httpx.Client:
        if not service_role_key:
            raise SupabaseServiceConfigError("SUPABASE_SERVICE_ROLE_KEY is required")
        return httpx.Client(
            headers={
                "apikey": service_role_key,
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            timeout=20.0,
        )

    def _select_maybe_single(
        self,
        table: str,
        filters: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            response = self._client.get(
                self._table_url(table),
                params={
                    "select": "*",
                    "limit": 1,
                    **_filter_params(filters),
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase select failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to read Supabase table {table}") from exc

        rows = response.json()
        return rows[0] if rows else None

    def _insert_single(self, table: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._client.post(self._table_url(table), json=payload)
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase insert failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to insert Supabase table {table}") from exc

        return _single_response_row(response.json(), table)

    def _upsert_single(
        self,
        table: str,
        payload: dict[str, Any],
        on_conflict: str,
    ) -> dict[str, Any]:
        try:
            response = self._client.post(
                self._table_url(table),
                params={"on_conflict": on_conflict},
                headers={"Prefer": "resolution=merge-duplicates,return=representation"},
                json=payload,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase upsert failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to upsert Supabase table {table}") from exc

        return _single_response_row(response.json(), table)

    def _update_single(
        self,
        table: str,
        payload: dict[str, Any],
        filters: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not payload:
            return self._select_maybe_single(table, filters)

        try:
            response = self._client.patch(
                self._table_url(table),
                params=_filter_params(filters),
                json=payload,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase update failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to update Supabase table {table}") from exc

        rows = response.json()
        return rows[0] if rows else None

    def _table_url(self, table: str) -> str:
        return f"{self._rest_url}/{table}"


def _single_response_row(data: Any, table: str) -> dict[str, Any]:
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict):
        return data
    raise SupabaseDatabaseError(f"Supabase table {table} returned no rows")


def _uuid_str(value: UUID | str) -> str:
    return str(value)


def _model_payload(data: Any) -> dict[str, Any]:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json", exclude_none=True)
    return {key: value for key, value in dict(data).items() if value is not None}


def _filter_params(filters: dict[str, Any]) -> dict[str, str]:
    return {column: f"eq.{_postgrest_value(value)}" for column, value in filters.items()}


def _postgrest_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@lru_cache()
def get_supabase_service() -> SupabaseService:
    return SupabaseService()
