"""Authenticated master profile endpoints."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.dependencies.auth import CurrentUser, get_current_user
from app.schemas.profile import ContactInfo, MasterProfile, ProfileResponse, ProfileUpdateRequest
from app.schemas.source_resume import SourceResumeListResponse, SourceResumeSummary, SourceResumeUploadResponse
from app.services.candidate_evidence_service import build_candidate_evidence
from app.services.embedding_service import embed_and_store_profile
from app.services.profile_extraction_service import (
    ResumeProfileExtractionError,
    extract_profile_from_resume_text,
)
from app.services.resume_parser_service import ResumeParserError, parse_resume_bytes, source_resume_file_type
from app.services.source_resume_service import (
    SourceResumeDocument,
    source_resume_service,
    source_resume_summary,
)
from app.services.supabase_service import SupabaseDatabaseError, SupabaseServiceConfigError, get_supabase_service
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/profile", tags=["profile"])
MAX_SOURCE_RESUME_BYTES = 10 * 1024 * 1024


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
        service = get_supabase_service()
        record = service.update_profile(
            current_user.user_id,
            profile.model_dump(mode="json"),
            profile_completion_score=score,
        )
        _schedule_profile_embedding(str(current_user.user_id), profile, service)
        return _profile_response(record, profile, status="saved")
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase profile service is not configured")
        raise HTTPException(status_code=500, detail="Profile storage is not configured") from exc
    except SupabaseDatabaseError as exc:
        logger.exception("Failed to save Supabase profile")
        raise HTTPException(status_code=503, detail="Profile could not be saved") from exc


@router.get("/embeddings/status")
async def get_profile_embedding_status(current_user: CurrentUser = Depends(get_current_user)):
    """Return stored RAG chunk count for the authenticated user's profile."""
    try:
        count = get_supabase_service().count_profile_embeddings(current_user.user_id)
        return {
            "enabled": get_settings().ENABLE_RAG_EMBEDDINGS,
            "chunk_count": count,
        }
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase profile embeddings service is not configured")
        raise HTTPException(status_code=500, detail="Profile embedding storage is not configured") from exc
    except SupabaseDatabaseError as exc:
        logger.exception("Failed to load profile embedding status")
        raise HTTPException(status_code=503, detail="Profile embedding status is unavailable") from exc


@router.post("/source-resumes", response_model=SourceResumeUploadResponse)
async def upload_source_resume(
    resume_file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Extract an uploaded resume into a reviewable candidate profile preview."""
    data = await resume_file.read(MAX_SOURCE_RESUME_BYTES + 1)
    if len(data) > MAX_SOURCE_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Source resume must be 10 MB or smaller.")

    filename = resume_file.filename or "uploaded-resume"
    try:
        extracted_text = parse_resume_bytes(
            data,
            filename=filename,
            content_type=resume_file.content_type,
        )
        extraction = await extract_profile_from_resume_text(extracted_text)
        evidence = build_candidate_evidence(extraction.profile)
        document = SourceResumeDocument(
            original_filename=filename,
            file_type=source_resume_file_type(filename),
            content_type=resume_file.content_type,
            file_size=len(data),
            extracted_text=extraction.cleaned_text,
            profile_json=extraction.profile.model_dump(mode="json"),
            evidence_json=evidence.model_dump(mode="json"),
        )
        try:
            record = source_resume_service.create(current_user.user_id, document)
            source_resume = source_resume_summary(record)
            logger.info(
                "source_resume.upload.completed user_id=%s source_resume_id=%s",
                current_user.user_id,
                record.id,
            )
        except SupabaseDatabaseError:
            logger.warning(
                "source_resumes table unavailable; saving uploaded resume extraction to master profile",
                exc_info=True,
            )
            profile_record = get_supabase_service().update_profile(
                current_user.user_id,
                extraction.profile.model_dump(mode="json"),
                profile_completion_score=calculate_profile_completion_score(extraction.profile),
            )
            source_resume = SourceResumeSummary(
                id=profile_record.id,
                display_name=filename,
                original_filename=filename,
                file_type=document.file_type,
                content_type=document.content_type,
                file_size=document.file_size,
                is_active=True,
                profile_json=extraction.profile,
                created_at=profile_record.created_at.isoformat() if profile_record.created_at else None,
                updated_at=profile_record.updated_at.isoformat() if profile_record.updated_at else None,
            )
            extraction.warnings.append(
                "Source resume history storage is not configured; extracted profile was saved as your master profile."
            )
        return SourceResumeUploadResponse(
            source_resume=source_resume,
            extracted_profile=extraction.profile,
            evidence_map=evidence,
            warnings=extraction.warnings,
            confidence=extraction.confidence,
            locked_fields=extraction.locked_fields,
        )
    except (ResumeParserError, ResumeProfileExtractionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase source resume service is not configured")
        raise HTTPException(status_code=500, detail="Source resume storage is not configured") from exc


@router.get("/source-resumes", response_model=SourceResumeListResponse)
async def list_source_resumes(current_user: CurrentUser = Depends(get_current_user)):
    try:
        records = source_resume_service.list(current_user.user_id)
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase source resume service is not configured")
        raise HTTPException(status_code=500, detail="Source resume storage is not configured") from exc
    except SupabaseDatabaseError as exc:
        logger.warning("Source resume storage is unavailable; returning empty source resume list", exc_info=True)
        return SourceResumeListResponse(resumes=[], active_source_resume_id=None)

    active = next((record.id for record in records if record.is_active), None)
    return SourceResumeListResponse(
        resumes=[source_resume_summary(record) for record in records],
        active_source_resume_id=active,
    )


@router.post("/source-resumes/{source_resume_id}/activate", response_model=SourceResumeListResponse)
async def activate_source_resume(
    source_resume_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    try:
        source_resume_service.activate(current_user.user_id, source_resume_id)
        records = source_resume_service.list(current_user.user_id)
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase source resume service is not configured")
        raise HTTPException(status_code=500, detail="Source resume storage is not configured") from exc
    except SupabaseDatabaseError as exc:
        logger.exception("Failed to activate source resume")
        raise HTTPException(status_code=404, detail="Source resume could not be activated") from exc

    return SourceResumeListResponse(
        resumes=[source_resume_summary(record) for record in records],
        active_source_resume_id=next((record.id for record in records if record.is_active), None),
    )


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


def _schedule_profile_embedding(user_id: str, profile: MasterProfile, supabase_service) -> None:
    if not get_settings().ENABLE_RAG_EMBEDDINGS:
        return
    try:
        asyncio.create_task(_embed_profile_background(user_id, profile, supabase_service))
    except RuntimeError:
        logger.debug("background_embed.skipped no_running_loop user=%s", user_id)


async def _embed_profile_background(user_id: str, profile: MasterProfile, supabase_service) -> None:
    """Background task: embed profile after save without blocking the API response."""
    try:
        count = await embed_and_store_profile(user_id, profile, supabase_service)
        logger.info("background_embed.complete user=%s chunks=%d", user_id, count)
    except Exception as exc:
        logger.error("background_embed.failed user=%s error=%s", user_id, exc)


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
