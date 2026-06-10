"""Persistence helpers for uploaded source resumes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.schemas.source_resume import SourceResumeSummary
from app.schemas.supabase import SourceResumeCreate, SourceResumeRecord
from app.services.supabase_service import get_supabase_service


@dataclass(frozen=True)
class SourceResumeDocument:
    original_filename: str
    file_type: str
    content_type: str | None
    file_size: int
    extracted_text: str
    profile_json: dict[str, Any]
    evidence_json: dict[str, Any]


class SourceResumeService:
    def create(self, user_id: UUID | str, document: SourceResumeDocument) -> SourceResumeRecord:
        return get_supabase_service().create_source_resume(
            user_id,
            SourceResumeCreate(
                display_name=document.original_filename,
                original_filename=document.original_filename,
                file_type=document.file_type,
                content_type=document.content_type,
                file_size=document.file_size,
                extracted_text=document.extracted_text,
                profile_json=document.profile_json,
                evidence_json=document.evidence_json,
            ),
        )

    def list(self, user_id: UUID | str) -> list[SourceResumeRecord]:
        return get_supabase_service().list_source_resumes(user_id)

    def activate(self, user_id: UUID | str, source_resume_id: UUID | str) -> SourceResumeRecord:
        return get_supabase_service().activate_source_resume(user_id, source_resume_id)


def source_resume_summary(record: SourceResumeRecord) -> SourceResumeSummary:
    return SourceResumeSummary(
        id=record.id,
        display_name=record.display_name,
        original_filename=record.original_filename,
        file_type=record.file_type,
        content_type=record.content_type,
        file_size=record.file_size,
        is_active=record.is_active,
        profile_json=record.profile_json or None,
        created_at=record.created_at.isoformat() if record.created_at else None,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
    )


source_resume_service = SourceResumeService()
