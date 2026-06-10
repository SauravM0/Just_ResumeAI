"""
Job Description analysis schemas.
Covers the raw JD input, parsed/structured output from Gemini,
and quality warnings for weak JDs.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .validation import ValidationStatus


# ─── Enums ───────────────────────────────────────────────────────────────────

class JDQualityLevel(str, Enum):
    """How well-structured / informative the JD is."""
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class SeniorityLevel(str, Enum):
    INTERN = "intern"
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    STAFF = "staff"
    PRINCIPAL = "principal"
    DIRECTOR = "director"
    VP = "vp"
    C_LEVEL = "c_level"
    UNKNOWN = "unknown"


# ─── Parsed JD Structure ────────────────────────────────────────────────────

class RequirementPriority(str, Enum):
    MUST_HAVE = "must-have"
    SHOULD_HAVE = "should-have"
    NICE_TO_HAVE = "nice-to-have"


class RequirementPlacement(str, Enum):
    SUMMARY = "summary"
    SKILLS = "skills"
    EXPERIENCE = "experience"
    PROJECTS = "projects"
    EDUCATION = "education"
    ACHIEVEMENTS = "achievements"


class JDRequirement(BaseModel):
    """A single extracted requirement from the JD."""
    text: str
    is_required: bool = True  # Legacy field, kept for compatibility
    priority: RequirementPriority = RequirementPriority.MUST_HAVE
    category: Optional[str] = Field(
        None, description="e.g. 'technical_skill', 'soft_skill', 'experience', 'education'"
    )
    suggested_placement: list[RequirementPlacement] = Field(
        default_factory=list,
        description="Where this requirement should ideally appear in the resume"
    )
    synonyms: list[str] = Field(
        default_factory=list,
        description="Alternative names or synonyms for this requirement"
    )


class JDKeyword(BaseModel):
    """A keyword/phrase extracted from the JD for ATS matching."""
    keyword: str
    frequency: int = Field(default=1, ge=1)
    importance: str = Field(
        default="medium",
        description="'critical', 'high', 'medium', 'low'"
    )


class ParsedJD(BaseModel):
    """Structured output from the JD Analyzer AI stage."""
    job_title: str
    company: Optional[str] = None
    location: Optional[str] = None
    seniority: SeniorityLevel = SeniorityLevel.UNKNOWN
    department: Optional[str] = None
    industry: Optional[str] = None

    # Core extracted data
    requirements: list[JDRequirement] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[JDKeyword] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    tools_platforms: list[str] = Field(default_factory=list)
    programming_languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    cloud_devops_tools: list[str] = Field(default_factory=list)
    domain_platform_terms: list[str] = Field(default_factory=list)
    deployment_environment_terms: list[str] = Field(default_factory=list)
    mobile_platform_terms: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    important_exact_phrases: list[str] = Field(default_factory=list)
    required_experience_years: Optional[int] = None
    required_education: Optional[str] = None

    # Quality assessment
    quality: JDQualityLevel = JDQualityLevel.MODERATE
    quality_warnings: list[str] = Field(
        default_factory=list,
        description="Human-readable warnings about JD quality issues"
    )

    # Raw text preserved for reference
    raw_text: str = ""


# ─── API Contracts ──────────────────────────────────────────────────────────

class JDAnalyzeRequest(BaseModel):
    """POST /api/v1/jd/analyze — user pastes raw JD text."""
    raw_jd_text: str = Field(..., min_length=50, max_length=15000)


class JDAnalyzeResponse(BaseModel):
    """Response from JD analysis endpoint."""
    generation_id: str = Field(..., description="Persistent Supabase generation ID")
    parsed_jd: ParsedJD
    warnings: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus = Field(
        default_factory=ValidationStatus,
        description="Standard validation status for JD intake.",
    )
