"""
Job Description analysis schemas.
Covers the raw JD input, parsed/structured output from Gemini,
and quality warnings for weak JDs.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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

class JDRequirement(BaseModel):
    """A single extracted requirement from the JD."""
    text: str
    is_required: bool = True  # True = must-have, False = nice-to-have
    category: Optional[str] = Field(
        None, description="e.g. 'technical_skill', 'soft_skill', 'experience', 'education'"
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
    session_id: str = Field(..., description="Unique session for this JD analysis flow")
    parsed_jd: ParsedJD
    warnings: list[str] = Field(default_factory=list)
