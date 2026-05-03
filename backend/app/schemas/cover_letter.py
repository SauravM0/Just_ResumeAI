"""
Cover letter schemas — optional output generated after the core resume flow.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .profile import MasterProfile
from .jd import ParsedJD
from .resume import ResumeRecommendation


class CoverLetterRequest(BaseModel):
    """POST /api/v1/cover-letter/generate"""
    session_id: str
    profile: MasterProfile
    parsed_jd: ParsedJD
    recommendation: ResumeRecommendation
    job_title: Optional[str] = Field(
        None,
        description="Target job title (uses parsed_jd.job_title if not provided)"
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
    session_id: str
    cover_letter_text: str
    word_count: int = 0
    warnings: list[str] = Field(default_factory=list)
