from __future__ import annotations

from pydantic import BaseModel, Field


class KeywordPlacementReport(BaseModel):
    """Where high-priority JD keywords appear in the generated resume."""

    keywords_in_target_title: list[str] = Field(default_factory=list)
    keywords_in_summary: list[str] = Field(default_factory=list)
    keywords_in_skills: list[str] = Field(default_factory=list)
    keywords_in_first_experience_bullets: list[str] = Field(default_factory=list)
    keywords_in_projects: list[str] = Field(default_factory=list)
    missing_high_priority_keywords: list[str] = Field(default_factory=list)
    weakly_placed_keywords: list[str] = Field(default_factory=list)


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
    keyword_placement: KeywordPlacementReport = Field(default_factory=KeywordPlacementReport)
    suggestions: list[str] = Field(default_factory=list)
    resume_rewrite_strategy: str = ""
