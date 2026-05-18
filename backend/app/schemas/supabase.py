"""Typed records and payloads for Supabase persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


JsonObject = dict[str, Any]
GenerationStatus = Literal["draft", "completed", "failed", "archived"]
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


class ResumeGenerationCreate(BaseModel):
    profile_id: UUID | None = None
    job_title: str | None = None
    company: str | None = None
    raw_jd_text: str = Field(..., min_length=1)
    parsed_jd_json: JsonObject | None = None
    resume_json: JsonObject | None = None
    ats_score_json: JsonObject | None = None
    alignment_report_json: JsonObject | None = None
    ats_pre_check_json: JsonObject | None = None
    cover_letter_text: str | None = None
    latex_source: str | None = None
    status: GenerationStatus = "draft"


class ResumeGenerationUpdate(BaseModel):
    profile_id: UUID | None = None
    job_title: str | None = None
    company: str | None = None
    raw_jd_text: str | None = None
    parsed_jd_json: JsonObject | None = None
    resume_json: JsonObject | None = None
    ats_score_json: JsonObject | None = None
    alignment_report_json: JsonObject | None = None
    ats_pre_check_json: JsonObject | None = None
    cover_letter_text: str | None = None
    latex_source: str | None = None
    status: GenerationStatus | None = None


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
    alignment_report_json: JsonObject | None = None
    ats_pre_check_json: JsonObject | None = None
    cover_letter_text: str | None = None
    latex_source: str | None = None
    status: str = "draft"
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SettingsUpdateRequest(BaseModel):
    target_resume_pages: int | None = Field(None, ge=1, le=2, description="Preferred number of resume pages (1 or 2)")
    preferred_tone: str | None = Field(None, min_length=1, max_length=50, description="Preferred resume tone, e.g. professional, creative")


class SettingsResponse(BaseModel):
    id: UUID
    user_id: UUID
    target_resume_pages: int = 1
    preferred_tone: str = "professional"
    created_at: str | None = None
    updated_at: str | None = None


class AllowedUserRecord(SupabaseRecord):
    id: UUID
    email: str
    is_active: bool = True
    created_at: datetime | None = None
