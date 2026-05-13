"""
Master Profile schemas — the single source of truth for user data.
These schemas mirror the IndexedDB structure on the frontend.
The backend receives a profile payload per-request; it never persists it.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────

class SkillLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class DegreeType(str, Enum):
    HIGH_SCHOOL = "high_school"
    ASSOCIATE = "associate"
    BACHELOR = "bachelor"
    MASTER = "master"
    DOCTORATE = "doctorate"
    CERTIFICATION = "certification"
    OTHER = "other"


# ─── Nested Models ───────────────────────────────────────────────────────────

class ContactInfo(BaseModel):
    """User contact details for resume header."""
    full_name: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=200)
    phone: Optional[str] = Field(None, max_length=30)
    location: Optional[str] = Field(None, max_length=150)
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None


class WorkExperience(BaseModel):
    """A single work experience entry in the master profile."""
    id: str = Field(..., description="Client-generated UUID")
    company: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    location: Optional[str] = None
    start_date: str = Field(..., description="ISO date string YYYY-MM or YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="ISO date string or null for current")
    is_current: bool = False
    description: Optional[str] = Field(None, description="Role summary")
    bullets: list[str] = Field(default_factory=list, description="Achievement bullets")
    needs_rewrite: bool = Field(default=False, description="True when source bullets are weak raw material that AI should rewrite")
    tags: list[str] = Field(default_factory=list, description="User-assigned tags, e.g. 'leadership'")


class Education(BaseModel):
    """A single education entry."""
    id: str
    institution: str = Field(..., min_length=1)
    degree: str
    degree_type: DegreeType = DegreeType.BACHELOR
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    honors: Optional[str] = None
    relevant_coursework: list[str] = Field(default_factory=list)


class Project(BaseModel):
    """A single project entry."""
    id: str
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    url: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    needs_rewrite: bool = Field(default=False, description="True when source bullets are weak raw material that AI should rewrite")
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class Skill(BaseModel):
    """A single skill with optional proficiency level."""
    name: str = Field(..., min_length=1)
    level: Optional[SkillLevel] = None
    category: Optional[str] = Field(None, description="e.g. 'Programming Languages', 'Frameworks'")


class Certification(BaseModel):
    """A certification or license."""
    id: str
    name: str = Field(..., min_length=1)
    issuing_org: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    credential_id: Optional[str] = None
    url: Optional[str] = None


class Publication(BaseModel):
    """An academic or professional publication."""
    id: str
    title: str = Field(..., min_length=1)
    publisher: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None


class VolunteerExperience(BaseModel):
    """Volunteer work / community involvement."""
    id: str
    organization: str = Field(..., min_length=1)
    role: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)


class Award(BaseModel):
    """Award or honor."""
    id: str
    title: str = Field(..., min_length=1)
    issuer: Optional[str] = None
    date: Optional[str] = None
    description: Optional[str] = None


# ─── Master Profile ─────────────────────────────────────────────────────────

class MasterProfile(BaseModel):
    """
    The complete master profile.
    Primary storage is client-side IndexedDB.
    Sent to backend per-request for AI processing.
    """
    id: str = Field(..., description="Client-generated UUID for the profile")
    version: int = Field(default=1, description="Schema version for forward compatibility")
    contact: ContactInfo
    summary: Optional[str] = Field(None, max_length=2000, description="Professional summary")
    work_experience: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    volunteer: list[VolunteerExperience] = Field(default_factory=list)
    awards: list[Award] = Field(default_factory=list)
    custom_sections: dict[str, list[str]] = Field(
        default_factory=dict,
        description="User-defined sections, e.g. {'Languages': ['English', 'Spanish']}"
    )
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ─── API Request/Response wrappers ──────────────────────────────────────────

class ProfilePayload(BaseModel):
    """Wrapper for sending profile data to the backend."""
    profile: MasterProfile
