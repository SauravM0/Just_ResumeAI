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


class ReadabilityScore(BaseModel):
    """Readability and formatting quality."""
    score: float = Field(default=0.0, ge=0.0, le=100.0)
    avg_bullet_length: float = 0.0
    issues: list[str] = Field(
        default_factory=list,
        description="e.g. 'Bullet too long', 'No action verb', 'Passive voice detected'"
    )


class ATSScore(BaseModel):
    """Composite ATS-friendliness score (the main quality metric)."""
    overall_score: float = Field(default=0.0, ge=0.0, le=100.0)
    keyword_score: KeywordScore = Field(default_factory=KeywordScore)
    readability_score: ReadabilityScore = Field(default_factory=ReadabilityScore)
    format_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Always 100 since we use a fixed ATS-friendly template"
    )
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable suggestions to improve the score"
    )


class ValidateResponse(BaseModel):
    """POST /api/v1/resume/validate response."""
    session_id: str
    ats_score: ATSScore
