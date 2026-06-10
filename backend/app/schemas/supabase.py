"""Typed records and payloads for Supabase persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


JsonObject = dict[str, Any]
GenerationStatus = Literal["draft", "queued", "running", "completed", "failed", "cancelled", "archived"]
GeneratedFileType = Literal["pdf", "docx", "tex", "other"]


class SupabaseRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")


class UserProfileRecord(SupabaseRecord):
    id: UUID
    user_id: UUID
    profile_json: JsonObject = Field(default_factory=dict)
    profile_completion_score: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SourceResumeCreate(BaseModel):
    display_name: str = Field(..., min_length=1)
    original_filename: str = Field(..., min_length=1)
    file_type: str = Field(..., min_length=1)
    content_type: str | None = None
    file_size: int = Field(default=0, ge=0)
    extracted_text: str = ""
    profile_json: JsonObject = Field(default_factory=dict)
    evidence_json: JsonObject = Field(default_factory=dict)


class SourceResumeRecord(SupabaseRecord):
    id: UUID
    user_id: UUID
    display_name: str
    original_filename: str
    file_type: str
    content_type: str | None = None
    file_size: int = 0
    extracted_text: str = ""
    profile_json: JsonObject = Field(default_factory=dict)
    evidence_json: JsonObject = Field(default_factory=dict)
    is_active: bool = False
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ResumeGenerationCreate(BaseModel):
    profile_id: UUID | None = None
    job_title: str | None = None
    company: str | None = None
    raw_jd_text: str = Field(..., min_length=1)
    parsed_jd_json: JsonObject | None = None
    resume_json: JsonObject | None = None
    ats_score_json: JsonObject | None = None
    recruiter_review_json: JsonObject | None = None
    recruiter_impression: float | None = None
    alignment_report_json: JsonObject | None = None
    ats_pre_check_json: JsonObject | None = None
    cover_letter_text: str | None = None
    latex_source: str | None = None
    docx_fallback_path: str | None = None
    pdf_compile_error: str | None = None
    status: GenerationStatus = "draft"
    target_pages: int = Field(default=1, ge=1, le=2)
    last_validated_version_id: Optional[str] = None
    last_exported_version_id: Optional[str] = None


class ResumeGenerationUpdate(BaseModel):
    profile_id: UUID | None = None
    job_title: str | None = None
    company: str | None = None
    raw_jd_text: str | None = None
    parsed_jd_json: JsonObject | None = None
    resume_json: JsonObject | None = None
    ats_score_json: JsonObject | None = None
    recruiter_review_json: JsonObject | None = None
    recruiter_impression: float | None = None
    alignment_report_json: JsonObject | None = None
    ats_pre_check_json: JsonObject | None = None
    cover_letter_text: str | None = None
    latex_source: str | None = None
    docx_fallback_path: str | None = None
    pdf_compile_error: str | None = None
    status: GenerationStatus | None = None
    target_pages: int | None = None
    last_validated_version_id: Optional[str] = None
    last_exported_version_id: Optional[str] = None
    updated_at: datetime | None = None
    current_step: str | None = None
    progress_percentage: int | None = None
    failure_reason: str | None = None
    failure_code: str | None = None
    progress_json: JsonObject | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None


ResumeGenerationCreate.model_rebuild()
ResumeGenerationUpdate.model_rebuild()


class ResumeGenerationRecord(SupabaseRecord):
    id: UUID
    user_id: UUID
    profile_id: UUID | None = None
    job_title: str | None = None
    company: str | None = None
    raw_jd_text: str
    parsed_jd_json: JsonObject | None = None
    resume_json: JsonObject | None = None
    ats_score_json: JsonObject | None = None
    recruiter_review_json: JsonObject | None = None
    recruiter_impression: float | None = None
    alignment_report_json: JsonObject | None = None
    ats_pre_check_json: JsonObject | None = None
    cover_letter_text: str | None = None
    latex_source: str | None = None
    docx_fallback_path: str | None = None
    pdf_compile_error: str | None = None
    status: str = "draft"
    target_pages: int = 1
    last_validated_version_id: Optional[str] = None
    last_exported_version_id: Optional[str] = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    current_step: str | None = None
    progress_percentage: int | None = None
    failure_reason: str | None = None
    failure_code: str | None = None
    progress_json: JsonObject | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None


class GeneratedFileCreate(BaseModel):
    file_type: GeneratedFileType
    storage_path: str = Field(..., min_length=1)
    expires_at: datetime


class GeneratedFileRecord(SupabaseRecord):
    id: UUID
    user_id: UUID
    generation_id: UUID
    file_type: str
    storage_path: str
    expires_at: datetime
    deleted_at: datetime | None = None
    created_at: datetime | None = None


class UsageEventRecord(SupabaseRecord):
    id: UUID
    user_id: UUID
    event_type: str
    generation_id: UUID | None = None
    metadata_json: JsonObject = Field(default_factory=dict)
    created_at: datetime | None = None


class UserSettingsRecord(SupabaseRecord):
    id: UUID
    user_id: UUID
    target_resume_pages: int = 1
    preferred_tone: str = "professional"
    aggressive_ats_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SettingsUpdateRequest(BaseModel):
    target_resume_pages: int | None = Field(None, ge=1, le=2, description="Preferred number of resume pages (1 or 2)")
    preferred_tone: str | None = Field(None, min_length=1, max_length=50, description="Preferred resume tone, e.g. professional, creative")
    aggressive_ats_default: bool | None = Field(
        None,
        description="When true, new resumes default to aggressive ATS optimization after the user's consent.",
    )


class SettingsResponse(BaseModel):
    id: UUID
    user_id: UUID
    target_resume_pages: int = 1
    preferred_tone: str = "professional"
    aggressive_ats_default: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class AllowedUserRecord(SupabaseRecord):
    id: UUID
    email: str
    is_active: bool = True
    created_at: datetime | None = None
