"""
Cover letter schemas — optional output generated after the core resume flow.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .profile import MasterProfile


class CoverLetterGenerateRequest(BaseModel):
    """POST /api/v1/cover-letter/{generation_id}/generate"""
    profile: MasterProfile
    job_title: Optional[str] = Field(
        None,
        description="Target job title"
    )
    tone: str = Field(
        default="Professional",
        description="Tone: 'Professional', 'Enthusiastic', 'Concise', 'Bold'"
    )
    additional_context: Optional[str] = Field(
        None,
        description="Any extra context the user wants the cover letter to address"
    )


class CoverLetterResponse(BaseModel):
    """Generated cover letter."""
    generation_id: str
    cover_letter_text: str
    word_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class CoverLetterUpdateRequest(BaseModel):
    """PUT /api/v1/cover-letter/{generation_id}"""
    cover_letter_text: str = Field(..., min_length=1)
