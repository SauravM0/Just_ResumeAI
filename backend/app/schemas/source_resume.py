"""Source resume intake schemas."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.profile import MasterProfile
from app.services.candidate_evidence_service import EvidenceGraph
from app.services.profile_extraction_service import ExtractionConfidenceReport


class SourceResumeSummary(BaseModel):
    id: UUID
    display_name: str
    original_filename: str
    file_type: str
    content_type: str | None = None
    file_size: int = 0
    is_active: bool = False
    profile_json: MasterProfile | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SourceResumeUploadResponse(BaseModel):
    source_resume: SourceResumeSummary
    extracted_profile: MasterProfile
    evidence_map: EvidenceGraph
    warnings: list[str] = Field(default_factory=list)
    confidence: ExtractionConfidenceReport = Field(default_factory=ExtractionConfidenceReport)
    locked_fields: dict[str, Any] = Field(default_factory=dict)


class SourceResumeListResponse(BaseModel):
    resumes: list[SourceResumeSummary] = Field(default_factory=list)
    active_source_resume_id: UUID | None = None


class SourceResumeProfileRecord(BaseModel):
    """Persistence payload kept separate from generated resume content."""

    profile_json: dict[str, Any]
    evidence_json: dict[str, Any]
