"""
Supabase-backed resume generation persistence service.

This is the production persistence layer for resume generations.
All resume generations are permanently stored in the resume_generations table.
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.services.supabase_service import (
    SupabaseDatabaseError,
    get_supabase_service,
)
from app.schemas.supabase import (
    JsonObject,
    ResumeGenerationCreate,
    ResumeGenerationRecord,
    ResumeGenerationUpdate,
)

logger = logging.getLogger(__name__)


class GenerationServiceError(RuntimeError):
    """Base error for generation service failures."""


class GenerationNotFoundError(GenerationServiceError):
    """Raised when a generation is not found or user lacks access."""


def _uuid_str(value: UUID | str) -> str:
    return str(value)


def create_generation(
    user_id: UUID | str,
    raw_jd_text: str,
    profile_id: UUID | str | None = None,
    initial_data: JsonObject | None = None,
    target_pages: int = 1,
) -> ResumeGenerationRecord:
    """
    Create a new resume generation record in Supabase.
    """
    svc = get_supabase_service()
    payload = ResumeGenerationCreate(
        profile_id=_uuid_str(profile_id) if profile_id else None,
        raw_jd_text=raw_jd_text,
        job_title=initial_data.get("job_title") if initial_data else None,
        company=initial_data.get("company") if initial_data else None,
        parsed_jd_json=initial_data.get("parsed_jd_json") if initial_data else None,
        status="draft",
        target_pages=target_pages,
    )
    try:
        return svc.create_generation(_uuid_str(user_id), payload)
    except SupabaseDatabaseError as e:
        logger.exception("Failed to create generation for user %s", user_id)
        raise GenerationServiceError("Failed to create resume generation") from e


def update_generation(
    user_id: UUID | str,
    generation_id: UUID | str,
    update_data: ResumeGenerationUpdate | dict,
) -> ResumeGenerationRecord:
    """
    Update an existing generation record.
    """
    svc = get_supabase_service()
    if not isinstance(update_data, ResumeGenerationUpdate):
        update_data = ResumeGenerationUpdate(**update_data)
    try:
        return svc.update_generation(_uuid_str(user_id), _uuid_str(generation_id), update_data)
    except SupabaseDatabaseError as e:
        logger.exception("Failed to update generation %s", generation_id)
        raise GenerationServiceError("Failed to update resume generation") from e


def get_generation(
    user_id: UUID | str,
    generation_id: UUID | str,
) -> ResumeGenerationRecord | None:
    """
    Retrieve a generation by ID, ensuring user ownership.
    Returns None if not found.
    """
    svc = get_supabase_service()
    return svc.get_generation(_uuid_str(user_id), _uuid_str(generation_id))


def list_generations(
    user_id: UUID | str,
    limit: int = 25,
    offset: int = 0,
) -> list[ResumeGenerationRecord]:
    """
    List all generations for a user, most recent first.
    """
    svc = get_supabase_service()
    return svc.list_generations(_uuid_str(user_id), limit=limit, offset=offset)


def assert_generation_owner(
    user_id: UUID | str,
    generation_id: UUID | str,
) -> ResumeGenerationRecord:
    """
    Assert that a generation exists and belongs to the user.
    Raises GenerationNotFoundError if not found or not owned.
    """
    gen = get_generation(user_id, generation_id)
    if gen is None:
        raise GenerationNotFoundError(
            f"Generation {generation_id} not found or not owned by user"
        )
    return gen


def save_generation_fields(
    user_id: UUID | str,
    generation_id: UUID | str,
    **fields: JsonObject | str | None,
) -> ResumeGenerationRecord:
    """
    Convenience method to save specific fields to a generation.
    Handles JSON serialization for nested objects.
    """
    update_data = ResumeGenerationUpdate()
    for key, value in fields.items():
        if value is not None and hasattr(update_data, key):
            setattr(update_data, key, value)
    return update_generation(user_id, generation_id, update_data)
