"""Authenticated user settings endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import CurrentUser, get_current_user
from app.schemas.supabase import SettingsResponse, SettingsUpdateRequest
from app.services.supabase_service import SupabaseDatabaseError, SupabaseServiceConfigError, get_supabase_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(current_user: CurrentUser = Depends(get_current_user)):
    try:
        service = get_supabase_service()
        record = service.get_or_create_settings(current_user.user_id)
        return SettingsResponse(
            id=record.id,
            user_id=record.user_id,
            target_resume_pages=record.target_resume_pages,
            preferred_tone=record.preferred_tone,
            aggressive_ats_default=record.aggressive_ats_default,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase settings service is not configured")
        raise HTTPException(status_code=500, detail="Settings storage is not configured") from exc
    except SupabaseDatabaseError as exc:
        logger.exception("Failed to load settings")
        raise HTTPException(status_code=503, detail="Settings storage is unavailable") from exc


@router.put("", response_model=SettingsResponse)
async def update_settings(
    request: SettingsUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        service = get_supabase_service()
        record = service.update_settings(current_user.user_id, request)
        return SettingsResponse(
            id=record.id,
            user_id=record.user_id,
            target_resume_pages=record.target_resume_pages,
            preferred_tone=record.preferred_tone,
            aggressive_ats_default=record.aggressive_ats_default,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase settings service is not configured")
        raise HTTPException(status_code=500, detail="Settings storage is not configured") from exc
    except SupabaseDatabaseError as exc:
        logger.exception("Failed to save settings")
        raise HTTPException(status_code=503, detail="Settings could not be saved") from exc
