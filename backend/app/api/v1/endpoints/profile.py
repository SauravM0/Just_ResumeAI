"""Authenticated master profile endpoints."""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import CurrentUser, get_current_user
from app.schemas.profile import ContactInfo, MasterProfile, ProfileResponse, ProfileUpdateRequest
from app.services.supabase_service import SupabaseDatabaseError, SupabaseServiceConfigError, get_supabase_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("/me", response_model=ProfileResponse)
async def get_my_profile(current_user: CurrentUser = Depends(get_current_user)):
    """Return the authenticated user's one master profile, creating an empty one if needed."""
    try:
        service = get_supabase_service()
        record = service.get_or_create_profile(current_user.user_id)
        profile = _profile_from_json(record.profile_json)
        if profile is None:
            profile = _empty_profile(current_user.email)
            record = service.update_profile(
                current_user.user_id,
                profile.model_dump(mode="json"),
                profile_completion_score=calculate_profile_completion_score(profile),
            )
        return _profile_response(record, profile, status="ready")
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase profile service is not configured")
        raise HTTPException(status_code=500, detail="Profile storage is not configured") from exc
    except SupabaseDatabaseError as exc:
        logger.exception("Failed to load Supabase profile")
        raise HTTPException(status_code=503, detail="Profile storage is unavailable") from exc


@router.put("/me", response_model=ProfileResponse)
async def update_my_profile(
    request: ProfileUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Upsert the authenticated user's single master profile."""
    profile = request.profile_json
    score = calculate_profile_completion_score(profile)
    try:
        record = get_supabase_service().update_profile(
            current_user.user_id,
            profile.model_dump(mode="json"),
            profile_completion_score=score,
        )
        return _profile_response(record, profile, status="saved")
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase profile service is not configured")
        raise HTTPException(status_code=500, detail="Profile storage is not configured") from exc
    except SupabaseDatabaseError as exc:
        logger.exception("Failed to save Supabase profile")
        raise HTTPException(status_code=503, detail="Profile could not be saved") from exc


def _empty_profile(email: str | None) -> MasterProfile:
    return MasterProfile(
        id=str(uuid4()),
        version=1,
        contact=ContactInfo(full_name="", email=email or ""),
        work_experience=[],
        education=[],
        skills=[],
        projects=[],
        certifications=[],
        publications=[],
        volunteer=[],
        awards=[],
        custom_sections={},
    )


def _profile_from_json(value: dict) -> MasterProfile | None:
    if not value:
        return None
    return MasterProfile.model_validate(value)


def _profile_response(record, profile: MasterProfile, status: str) -> ProfileResponse:
    return ProfileResponse(
        id=record.id,
        user_id=record.user_id,
        profile_json=profile,
        profile_completion_score=record.profile_completion_score,
        status=status,
        created_at=record.created_at.isoformat() if record.created_at else None,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
    )


def calculate_profile_completion_score(profile: MasterProfile) -> int:
    checks = [
        bool(profile.contact.full_name.strip()),
        bool(profile.contact.email.strip()),
        bool(profile.work_experience),
        any(exp.bullets for exp in profile.work_experience),
        bool(profile.education),
        bool(profile.skills),
        bool(profile.projects),
        bool(profile.summary and profile.summary.strip()),
    ]
    return round((sum(checks) / len(checks)) * 100)
