"""
Scoring schemas — ATS score, keyword coverage, readability assessment.
These are computed after the user finishes review, before final render.
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

from .validation import ValidationStatus


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
    """
    Composite ATS readiness score (the main quality metric).
    ...
    """
    overall_score: float = Field(default=0.0, ge=0.0, le=100.0)
    resume_version_id: Optional[str] = Field(None, description="The version of the resume this score was computed for")

    # ─── Composite breakdown categories ──────────────────────────────────
    ats_match_score: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="ATS Match: title alignment, keyword coverage, skill match, page compliance.",
    )
    truthfulness_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Truthfulness: seniority honesty, supported keyword coverage, no unsupported hard skill claims.",
    )
    recruiter_quality_score: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="Recruiter Quality: summary strength, bullet relevance, readability, anti-stuffing.",
    )
    parseability_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Parseability: format quality, section completeness, PDF text extraction.",
    )
    risk_flags_count: int = Field(
        default=0, ge=0,
        description="Number of active risk flags (contamination, placeholders, malformed dates, etc.). Each flag lowers final score.",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Specific risk flags that could block export or cause ATS rejection.",
    )

    # ─── Legacy fields (backward compatible) ─────────────────────────────
    keyword_score: KeywordScore = Field(default_factory=KeywordScore)
    skill_score: SkillScore = Field(default_factory=SkillScore)
    readability_score: ReadabilityScore = Field(default_factory=ReadabilityScore)
    format_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Formatting and parseability score",
    )
    section_score: SectionScore = Field(default_factory=SectionScore)
    responsibility_score: float = Field(default=0.0, ge=0.0, le=100.0)
    title_alignment_score: float = Field(default=0.0, ge=0.0, le=100.0)
    missing_keywords: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable suggestions to improve the score",
    )

    # ─── Honest sub-scores for transparent display ───────────────────────
    keyword_coverage_score: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="What % of JD keywords appear anywhere in the resume (raw match, no evidence check).",
    )
    supported_coverage_score: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="What % of matched keywords are backed by candidate evidence (honest skill claims).",
    )
    formatting_readiness_score: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="Formatting quality: contact info, section completeness, bullet structure, no corrupted chars.",
    )
    seniority_honesty_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Whether the resume target title honestly reflects candidate seniority. Low = title inflation.",
    )
    validation_readiness_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Does the resume pass export validation gate? Low = issues will block PDF/DOCX export.",
    )
    readability_warnings_count: int = Field(
        default=0, ge=0,
        description="Count of readability issues found (bullets missing action verbs, passive voice, etc).",
    )
    export_ready: bool = Field(
        default=False,
        description="True only when validation gate passes in export mode with zero blocking issues.",
    )

    # ─── Quality dimensions ──────────────────────────────────────────────
    seniority_alignment_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="How well resume seniority matches JD seniority level",
    )
    summary_strength_score: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="Quality of professional summary: JD title presence, keyword density, clarity",
    )
    bullet_relevance_score: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="Action + skill + outcome pattern in experience/project bullets",
    )
    project_relevance_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Project technologies and descriptions aligned to JD",
    )
    skills_section_quality_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Skills grouping quality, no soft-skill filler, proper categorization",
    )
    anti_stuffing_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Penalty for unnatural keyword repetition or comma-block stuffing",
    )
    page_compliance_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Adherence to target page count (1 or 2 pages)",
    )
    pdf_extraction_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Quality of text extraction from compiled PDF",
    )
    contamination_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Penalty for JD boilerplate, invalid placeholders, or ATS metadata in resume text",
    )
    date_validity_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Penalty for malformed or missing date fields",
    )

    # ─── Composite output ────────────────────────────────────────────────
    score_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Weighted contribution of each dimension to overall_score (pre-cap)",
    )
    matched_keywords: list[str] = Field(
        default_factory=list,
        description="Flat list of JD keywords found in the resume",
    )
    matched_supported_keywords: list[str] = Field(
        default_factory=list,
        description="Matched JD keywords supported by candidate evidence.",
    )
    unsupported_jd_keywords: list[str] = Field(
        default_factory=list,
        description="JD keywords without candidate evidence for hands-on claims.",
    )
    learning_focus_keywords: list[str] = Field(
        default_factory=list,
        description="Adjacent JD keywords shown honestly as learning focus.",
    )
    missing_critical_keywords: list[str] = Field(
        default_factory=list,
        description="Critical JD keywords not found — blocks high scores",
    )
    missing_preferred_keywords: list[str] = Field(
        default_factory=list,
        description="Preferred/nice-to-have JD keywords not found",
    )
    stuffing_warnings: list[str] = Field(
        default_factory=list,
        description="Specific keyword stuffing or unnatural repetition detected",
    )
    section_improvement_suggestions: list[str] = Field(
        default_factory=list,
        description="Actionable section-level improvements",
    )
    final_pdf_parse_status: str = Field(
        default="not_evaluated",
        description="PDF text extraction status: not_evaluated | success | failed | empty | partial",
    )


ATSScore.model_rebuild()


class ValidateResponse(BaseModel):
    """Response returned by POST /api/v1/resume/validate."""
    generation_id: str
    ats_score: ATSScore
    validation_status: ValidationStatus = Field(
        default_factory=ValidationStatus,
        description="Standard validation status for the scored resume.",
    )
