"""
Scoring schemas — ATS score, keyword coverage, readability assessment.
These are computed after the user finishes review, before final render.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class KeywordMatch(BaseModel):
    """How well a specific JD keyword is covered in the resume."""
    keyword: str
    found: bool = False
    location: str = Field(
        default="",
        description="Where it was found: 'summary', 'experience', 'skills', etc."
    )


class KeywordScore(BaseModel):
    """Overall keyword coverage score."""
    total_keywords: int = 0
    matched_keywords: int = 0
    coverage_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    critical_missing: list[str] = Field(
        default_factory=list,
        description="Critical JD keywords not found in resume"
    )
    details: list[KeywordMatch] = Field(default_factory=list)


class SkillScore(BaseModel):
    """Required and preferred skills coverage score."""
    required_total: int = 0
    required_matched: int = 0
    required_coverage_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    preferred_total: int = 0
    preferred_matched: int = 0
    preferred_coverage_percent: float = Field(default=0.0, ge=0.0, le=100.0)


class ReadabilityScore(BaseModel):
    """Readability and formatting quality."""
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    avg_bullet_length: float = 0.0
    issues: list[str] = Field(
        default_factory=list,
        description="e.g. 'Bullet too long', 'No action verb', 'Passive voice detected'"
    )


class SectionScore(BaseModel):
    """Section completeness score."""
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    missing_sections: list[str] = Field(default_factory=list)
    has_contact: bool = True
    has_summary: bool = True
    has_experience: bool = True
    has_skills: bool = True
    has_education: bool = True


class ATSScore(BaseModel):
    """Composite ATS-friendliness score (the main quality metric)."""
    overall_score: float = Field(default=0.0, ge=0.0, le=100.0)
    keyword_score: KeywordScore = Field(default_factory=KeywordScore)
    skill_score: SkillScore = Field(default_factory=SkillScore)
    readability_score: ReadabilityScore = Field(default_factory=ReadabilityScore)
    format_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Formatting and parseability score"
    )
    section_score: SectionScore = Field(default_factory=SectionScore)
    responsibility_score: float = Field(default=0.0, ge=0.0, le=100.0)
    title_alignment_score: float = Field(default=0.0, ge=0.0, le=100.0)
    missing_keywords: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable suggestions to improve the score"
    )


class ValidateResponse(BaseModel):
    """POST /api/v1/resume/validate response."""
    generation_id: str
    ats_score: ATSScore
