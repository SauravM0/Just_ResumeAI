"""Supabase service-role persistence foundation."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import logging
import re
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
    SourceResumeCreate,
    SourceResumeRecord,
    UsageEventRecord,
    UserProfileRecord,
    UserSettingsRecord,
)

logger = logging.getLogger(__name__)
_WARNED_MISSING_RELATIONS: set[str] = set()


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

    def replace_profile_embeddings(
        self,
        user_id: UUID | str,
        rows: list[dict[str, Any]],
    ) -> int:
        """Replace all profile embedding rows for a user."""
        user_id_str = _uuid_str(user_id)
        try:
            self._delete_many("profile_embeddings", filters={"user_id": user_id_str})
        except SupabaseDatabaseError as exc:
            if "profile_embeddings" in str(exc):
                _warn_missing_relation_once(
                    "profile_embeddings",
                    "profile_embeddings is unavailable; skipping embedding persistence",
                )
                return 0
            raise
        if not rows:
            return 0
        prepared_rows = [dict(row, user_id=user_id_str) for row in rows]
        try:
            return len(self._insert_many("profile_embeddings", prepared_rows))
        except SupabaseDatabaseError as exc:
            if "profile_embeddings" in str(exc):
                _warn_missing_relation_once(
                    "profile_embeddings",
                    "profile_embeddings is unavailable; skipping embedding persistence",
                )
                return 0
            raise

    def count_profile_embeddings(self, user_id: UUID | str) -> int:
        """Return the number of stored embedding chunks for a user."""
        try:
            response = self._client.get(
                self._table_url("profile_embeddings"),
                params={
                    "select": "id",
                    "user_id": f"eq.{_uuid_str(user_id)}",
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if _missing_schema_relation(exc.response, "profile_embeddings"):
                _warn_missing_relation_once(
                    "profile_embeddings",
                    "profile_embeddings table is unavailable; RAG will use fallback",
                )
                return 0
            logger.exception("Supabase count_profile_embeddings failed")
            raise SupabaseDatabaseError("Failed to count profile embeddings") from exc
        except Exception as exc:
            logger.exception("Supabase count_profile_embeddings failed")
            raise SupabaseDatabaseError("Failed to count profile embeddings") from exc
        rows = response.json()
        return len(rows) if isinstance(rows, list) else 0

    def match_profile_chunks(
        self,
        *,
        user_id: UUID | str,
        query_embedding: list[float],
        match_count: int = 3,
        similarity_threshold: float = 0.55,
    ) -> list[dict[str, Any]]:
        """Run the pgvector match_profile_chunks RPC for a user's profile chunks."""
        try:
            response = self._client.post(
                f"{self._rest_url}/rpc/match_profile_chunks",
                json={
                    "query_embedding": query_embedding,
                    "match_user_id": _uuid_str(user_id),
                    "match_count": match_count,
                    "similarity_threshold": similarity_threshold,
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if _missing_schema_relation(exc.response, "match_profile_chunks"):
                _warn_missing_relation_once(
                    "match_profile_chunks",
                    "match_profile_chunks RPC is unavailable; RAG will use fallback",
                )
                return []
            logger.exception("Supabase match_profile_chunks failed")
            raise SupabaseDatabaseError("Failed to match profile chunks") from exc
        except Exception as exc:
            logger.exception("Supabase match_profile_chunks failed")
            raise SupabaseDatabaseError("Failed to match profile chunks") from exc
        rows = response.json()
        return rows if isinstance(rows, list) else []

    def create_source_resume(
        self,
        user_id: UUID | str,
        data: SourceResumeCreate | dict[str, Any],
    ) -> SourceResumeRecord:
        user_id_str = _uuid_str(user_id)
        self._update_many(
            "source_resumes",
            {"is_active": False},
            filters={"user_id": user_id_str, "is_active": True, "status": "active"},
        )
        payload = _model_payload(data)
        payload.update({"user_id": user_id_str, "is_active": True, "status": "active"})
        return SourceResumeRecord.model_validate(self._insert_single("source_resumes", payload))

    def list_source_resumes(self, user_id: UUID | str) -> list[SourceResumeRecord]:
        try:
            response = self._client.get(
                self._table_url("source_resumes"),
                params={
                    "select": "*",
                    "user_id": f"eq.{_uuid_str(user_id)}",
                    "status": "eq.active",
                    "order": "created_at.desc",
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase list_source_resumes failed")
            raise SupabaseDatabaseError("Failed to list Supabase source resumes") from exc
        return [SourceResumeRecord.model_validate(row) for row in response.json()]

    def activate_source_resume(
        self,
        user_id: UUID | str,
        source_resume_id: UUID | str,
    ) -> SourceResumeRecord:
        user_id_str = _uuid_str(user_id)
        target = self._select_maybe_single(
            "source_resumes",
            filters={"id": _uuid_str(source_resume_id), "user_id": user_id_str, "status": "active"},
        )
        if target is None:
            raise SupabaseDatabaseError("Source resume not found")
        self._update_many(
            "source_resumes",
            {"is_active": False},
            filters={"user_id": user_id_str, "is_active": True, "status": "active"},
        )
        updated = self._update_single(
            "source_resumes",
            {"is_active": True},
            filters={"id": _uuid_str(source_resume_id), "user_id": user_id_str},
        )
        if updated is None:
            raise SupabaseDatabaseError("Failed to activate source resume")
        return SourceResumeRecord.model_validate(updated)

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
        
        try:
            created = self._insert_single("resume_generations", payload)
        except SupabaseDatabaseError as exc:
            if "409" in str(exc) or "Conflict" in str(exc):
                # Workaround for missing auth trigger: ensure user exists in public.users
                try:
                    self._insert_single("users", {"id": user_id_str})
                except Exception:
                    pass
                created = self._insert_single("resume_generations", payload)
            else:
                raise
                
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

    def list_generations_by_status(
        self,
        status: str,
        *,
        older_than: datetime | None = None,
        limit: int = 50,
    ) -> list[ResumeGenerationRecord]:
        """List generations by status, optionally filtered by updated_at < older_than.

        INTERNAL/ADMIN USE ONLY — no owner scoping.
        Used by the stale generation sweeper.
        """
        params: dict[str, str] = {
            "select": "*",
            "status": f"eq.{status}",
            "order": "updated_at.asc",
            "limit": str(limit),
        }
        if older_than is not None:
            params["updated_at"] = f"lt.{older_than.isoformat()}"
        try:
            response = self._client.get(
                self._table_url("resume_generations"),
                params=params,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase list_generations_by_status failed")
            raise SupabaseDatabaseError("Failed to list generations by status") from exc
        return [ResumeGenerationRecord.model_validate(row) for row in response.json()]

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

    def count_generations_for_user_since(
        self,
        user_id: UUID | str,
        since: datetime,
    ) -> int:
        """Count a user's generations created after a cutoff."""
        try:
            response = self._client.get(
                self._table_url("resume_generations"),
                params={
                    "select": "id",
                    "user_id": f"eq.{_uuid_str(user_id)}",
                    "created_at": f"gte.{since.isoformat()}",
                    "limit": 1000,
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase count_generations_for_user_since failed")
            raise SupabaseDatabaseError("Failed to count Supabase generations") from exc
        rows = response.json()
        return len(rows) if isinstance(rows, list) else 0

    def count_active_generations_for_user(self, user_id: UUID | str) -> int:
        """Count a user's queued/running generations."""
        try:
            response = self._client.get(
                self._table_url("resume_generations"),
                params={
                    "select": "id",
                    "user_id": f"eq.{_uuid_str(user_id)}",
                    "status": "in.(queued,running)",
                    "limit": 1000,
                },
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase count_active_generations_for_user failed")
            raise SupabaseDatabaseError("Failed to count active Supabase generations") from exc
        rows = response.json()
        return len(rows) if isinstance(rows, list) else 0

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
                "aggressive_ats_default": False,
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
        working_payload = dict(payload)
        while True:
            try:
                response = self._client.post(self._table_url(table), json=working_payload)
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                missing_column = _missing_schema_column(exc.response)
                if missing_column and missing_column in working_payload:
                    logger.warning(
                        "Supabase table=%s schema cache is missing column=%s; retrying without it",
                        table,
                        missing_column,
                    )
                    working_payload.pop(missing_column, None)
                    continue
                logger.exception(
                    "Supabase insert failed table=%s status=%s body=%s",
                    table,
                    exc.response.status_code,
                    exc.response.text,
                )
                raise SupabaseDatabaseError(f"Failed to insert Supabase table {table}") from exc
            except Exception as exc:
                logger.exception("Supabase insert failed table=%s", table)
                raise SupabaseDatabaseError(f"Failed to insert Supabase table {table}") from exc

        return _single_response_row(response.json(), table)

    def _insert_many(self, table: str, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not payloads:
            return []
        try:
            response = self._client.post(self._table_url(table), json=payloads)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if _missing_schema_relation(exc.response, table):
                _warn_missing_relation_once(table, f"Supabase relation unavailable table={table}")
                raise SupabaseDatabaseError(f"Supabase relation unavailable table={table}") from exc
            logger.exception("Supabase bulk insert failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to bulk insert Supabase table {table}") from exc
        except Exception as exc:
            logger.exception("Supabase bulk insert failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to bulk insert Supabase table {table}") from exc
        rows = response.json()
        return rows if isinstance(rows, list) else []

    def _upsert_single(
        self,
        table: str,
        payload: dict[str, Any],
        on_conflict: str,
    ) -> dict[str, Any]:
        working_payload = dict(payload)
        while True:
            try:
                response = self._client.post(
                    self._table_url(table),
                    params={"on_conflict": on_conflict},
                    headers={"Prefer": "resolution=merge-duplicates,return=representation"},
                    json=working_payload,
                )
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                missing_column = _missing_schema_column(exc.response)
                if missing_column and missing_column in working_payload:
                    logger.warning(
                        "Supabase table=%s schema cache is missing column=%s; retrying without it",
                        table,
                        missing_column,
                    )
                    working_payload.pop(missing_column, None)
                    continue
                logger.exception(
                    "Supabase upsert failed table=%s status=%s body=%s",
                    table,
                    exc.response.status_code,
                    exc.response.text,
                )
                raise SupabaseDatabaseError(f"Failed to upsert Supabase table {table}") from exc
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
        working_payload = dict(payload)
        if not working_payload:
            return self._select_maybe_single(table, filters)

        while True:
            try:
                response = self._client.patch(
                    self._table_url(table),
                    params=_filter_params(filters),
                    json=working_payload,
                )
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                missing_column = _missing_schema_column(exc.response)
                if missing_column and missing_column in working_payload:
                    logger.warning(
                        "Supabase table=%s schema cache is missing column=%s; retrying without it",
                        table,
                        missing_column,
                    )
                    working_payload.pop(missing_column, None)
                    if not working_payload:
                        return self._select_maybe_single(table, filters)
                    continue
                logger.exception(
                    "Supabase update failed table=%s status=%s body=%s",
                    table,
                    exc.response.status_code,
                    exc.response.text,
                )
                raise SupabaseDatabaseError(f"Failed to update Supabase table {table}") from exc
            except Exception as exc:
                logger.exception("Supabase update failed table=%s", table)
                raise SupabaseDatabaseError(f"Failed to update Supabase table {table}") from exc

        rows = response.json()
        return rows[0] if rows else None

    def _update_many(
        self,
        table: str,
        payload: dict[str, Any],
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            response = self._client.patch(
                self._table_url(table),
                params=_filter_params(filters),
                json=payload,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.exception("Supabase bulk update failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to update Supabase table {table}") from exc
        rows = response.json()
        return rows if isinstance(rows, list) else []

    def _delete_many(
        self,
        table: str,
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        try:
            response = self._client.delete(
                self._table_url(table),
                params=_filter_params(filters),
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if _missing_schema_relation(exc.response, table):
                _warn_missing_relation_once(table, f"Supabase relation unavailable table={table}")
                raise SupabaseDatabaseError(f"Supabase relation unavailable table={table}") from exc
            logger.exception("Supabase delete failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to delete Supabase table {table}") from exc
        except Exception as exc:
            logger.exception("Supabase delete failed table=%s", table)
            raise SupabaseDatabaseError(f"Failed to delete Supabase table {table}") from exc
        rows = response.json()
        return rows if isinstance(rows, list) else []

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


def _missing_schema_column(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if body.get("code") != "PGRST204":
        return None
    message = body.get("message") or ""
    match = re.search(r"Could not find the '([^']+)' column", message)
    return match.group(1) if match else None


def _missing_schema_relation(response: httpx.Response, relation: str) -> bool:
    if response.status_code != 404:
        return False
    try:
        body = response.json()
    except ValueError:
        return relation in response.text
    message = " ".join(str(body.get(key) or "") for key in ("code", "message", "details", "hint"))
    return relation in message and (
        "Could not find" in message
        or "schema cache" in message
        or "PGRST" in message
    )


def _warn_missing_relation_once(relation: str, message: str) -> None:
    if relation in _WARNED_MISSING_RELATIONS:
        return
    _WARNED_MISSING_RELATIONS.add(relation)
    logger.warning("%s", message)


def _filter_params(filters: dict[str, Any]) -> dict[str, str]:
    return {column: f"eq.{_postgrest_value(value)}" for column, value in filters.items()}


def _postgrest_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@lru_cache()
def get_supabase_service() -> SupabaseService:
    return SupabaseService()
