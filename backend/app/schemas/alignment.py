from __future__ import annotations

from pydantic import BaseModel, Field


class ATSAlignmentReport(BaseModel):
    """JD-to-generated-resume ATS alignment report."""

    overall_alignment_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    keyword_coverage_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    formatting_score: float = Field(default=100.0, ge=0.0, le=100.0)
    section_completeness_score: float = Field(default=0.0, ge=0.0, le=100.0)
    jd_title_detected: str = ""
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    role_responsibilities: list[str] = Field(default_factory=list)
    important_ats_keywords: list[str] = Field(default_factory=list)
    keywords_included: list[str] = Field(default_factory=list)
    keywords_missing: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    resume_rewrite_strategy: str = ""
