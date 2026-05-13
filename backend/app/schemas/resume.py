"""
Resume pipeline schemas — covering the recommendation, review, and rendering stages.
This is the core data flow: Profile + JD → Recommendations → Human Review → LaTeX → PDF.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .alignment import ATSAlignmentReport
from .profile import MasterProfile


# ─── Enums ───────────────────────────────────────────────────────────────────

class BulletStatus(str, Enum):
    """Status of an individual bullet during human review."""
    PENDING = "pending"       # AI-generated, awaiting review
    ACCEPTED = "accepted"     # User accepted as-is
    EDITED = "edited"         # User modified the bullet
    LOCKED = "locked"         # User locked — will not be changed on regeneration
    REJECTED = "rejected"     # User rejected — must not reappear


class SectionType(str, Enum):
    """Resume section identifiers matching the LaTeX template."""
    CONTACT = "contact"
    SUMMARY = "summary"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    SKILLS = "skills"
    PROJECTS = "projects"
    CERTIFICATIONS = "certifications"
    AWARDS = "awards"
    PUBLICATIONS = "publications"
    VOLUNTEER = "volunteer"
    CUSTOM = "custom"


# ─── Resume Bullet ──────────────────────────────────────────────────────────

class ResumeBullet(BaseModel):
    """A single bullet point in a resume section, with review state."""
    id: str = Field(..., description="Unique ID for this bullet")
    text: str
    original_text: Optional[str] = Field(
        None, description="Original AI-generated text before user edits"
    )
    status: BulletStatus = BulletStatus.PENDING
    relevance_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="How relevant this bullet is to the JD (0-1)"
    )
    matched_keywords: list[str] = Field(
        default_factory=list,
        description="JD keywords this bullet addresses"
    )
    source_id: Optional[str] = Field(
        None, description="ID of the master profile item this bullet originated from"
    )


# ─── Resume Section Entries ─────────────────────────────────────────────────

class ResumeExperienceEntry(BaseModel):
    """A single experience entry recommended for the resume."""
    source_id: str = Field(..., description="Links back to MasterProfile.work_experience[].id")
    company: str
    title: str
    location: Optional[str] = None
    start_date: str
    end_date: Optional[str] = None
    is_current: bool = False
    bullets: list[ResumeBullet] = Field(default_factory=list)
    included: bool = Field(default=True, description="Whether user accepted this entry")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)


class ResumeEducationEntry(BaseModel):
    source_id: str
    institution: str
    degree: str
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    gpa: Optional[str] = None
    honors: Optional[str] = None
    relevant_coursework: list[str] = Field(default_factory=list)
    included: bool = True


class ResumeProjectEntry(BaseModel):
    source_id: str
    name: str
    description: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)
    bullets: list[ResumeBullet] = Field(default_factory=list)
    included: bool = True
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)


class ResumeSkillGroup(BaseModel):
    """Grouped skills for the Skills section."""
    category: str = Field(..., description="e.g. 'Programming Languages'")
    skills: list[str] = Field(default_factory=list)


class ResumeCertEntry(BaseModel):
    source_id: str
    name: str
    issuing_org: Optional[str] = None
    date: Optional[str] = None
    included: bool = True


class ResumeAchievementEntry(BaseModel):
    source_id: str
    title: str
    issuer: Optional[str] = None
    date: Optional[str] = None
    description: Optional[str] = None
    included: bool = True


class ResumeCustomSection(BaseModel):
    title: str
    items: list[str] = Field(default_factory=list)
    included: bool = True


# ─── Contact Info for Rendering ──────────────────────────────────────────────

class ResumeContactInfo(BaseModel):
    """Contact info carried through the pipeline for LaTeX rendering."""
    full_name: str = ""
    email: str = ""
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None


# ─── Full Resume Recommendation ─────────────────────────────────────────────

class ResumeRecommendation(BaseModel):
    """
    The complete resume recommendation from the AI pipeline.
    This is what the user reviews before final rendering.
    """
    session_id: str
    target_title: str = Field(..., description="Tailored resume title/headline")
    summary: Optional[str] = Field(None, description="AI-generated professional summary")
    contact: ResumeContactInfo = Field(default_factory=ResumeContactInfo)
    experience: list[ResumeExperienceEntry] = Field(default_factory=list)
    education: list[ResumeEducationEntry] = Field(default_factory=list)
    skills: list[ResumeSkillGroup] = Field(default_factory=list)
    projects: list[ResumeProjectEntry] = Field(default_factory=list)
    certifications: list[ResumeCertEntry] = Field(default_factory=list)
    achievements: list[ResumeAchievementEntry] = Field(default_factory=list)
    awards: list[ResumeAchievementEntry] = Field(default_factory=list)
    custom_sections: list[ResumeCustomSection] = Field(default_factory=list)
    section_order: list[str] = Field(default_factory=list)

    # Metadata
    emphasis: Optional[str] = Field(
        None, description="User-specified emphasis, e.g. 'leadership' or 'backend engineering'"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking system warnings for generation fallback or rendering issues."
    )


# ─── API Contracts ──────────────────────────────────────────────────────────

class ResumeRecommendRequest(BaseModel):
    """POST /api/v1/resume/recommend"""
    session_id: str
    profile: MasterProfile
    emphasis: Optional[str] = None
    additional_alignment_text: Optional[str] = Field(
        default=None,
        max_length=6000,
        description="Optional JD emphasis or keyword guidance for regeneration."
    )
    rejected_item_ids: list[str] = Field(
        default_factory=list,
        description="IDs of previously rejected items — must not reappear"
    )


class ResumeRecommendResponse(BaseModel):
    """Response from recommendation endpoint."""
    recommendation: ResumeRecommendation
    alignment_report: Optional[ATSAlignmentReport] = None


class ResumeRegenerateRequest(BaseModel):
    """POST /api/v1/resume/regenerate — re-run with updated preferences."""
    session_id: str
    profile: MasterProfile
    emphasis: Optional[str] = None
    additional_alignment_text: Optional[str] = Field(
        default=None,
        max_length=6000,
        description="Optional JD emphasis or keyword guidance for regeneration."
    )
    locked_bullet_ids: list[str] = Field(
        default_factory=list,
        description="Bullet IDs the user locked — preserve exactly"
    )
    rejected_item_ids: list[str] = Field(
        default_factory=list,
        description="IDs of rejected items — must not reappear"
    )


class ResumeValidateRequest(BaseModel):
    """POST /api/v1/resume/validate — run ATS validation."""
    session_id: str
    recommendation: ResumeRecommendation


class ResumeRenderLatexRequest(BaseModel):
    """POST /api/v1/resume/render-latex"""
    session_id: str
    recommendation: ResumeRecommendation


class ResumeRenderLatexResponse(BaseModel):
    """LaTeX source code response."""
    latex_source: str
    warnings: list[str] = Field(default_factory=list)


class ResumeRenderPdfRequest(BaseModel):
    """POST /api/v1/resume/render-pdf"""
    session_id: str


class ResumeCompileLatexSourceRequest(BaseModel):
    """POST /api/v1/resume/compile-latex-source"""
    session_id: str
    latex_source: str = Field(..., min_length=1)


class ResumeApproveGeneratePdfRequest(BaseModel):
    """POST /api/v1/resume/approve-generate-pdf"""
    session_id: str
    recommendation: ResumeRecommendation


class ResumeRenderPdfResponse(BaseModel):
    """PDF compilation result."""
    pdf_url: str = Field(..., description="URL to download the compiled PDF")
    compile_success: bool = True
    compile_errors: list[str] = Field(default_factory=list)
    compile_warnings: list[str] = Field(default_factory=list)
    generated_tex_path: Optional[str] = None
    pdflatex_excerpt: Optional[str] = None
    line_number: Optional[int] = None


class ResumeApproveGeneratePdfResponse(BaseModel):
    """Combined LaTeX rendering + PDF compilation result."""
    latex_source: str = ""
    pdf_url: str = ""
    compile_success: bool = True
    compile_errors: list[str] = Field(default_factory=list)
    compile_warnings: list[str] = Field(default_factory=list)
    generated_tex_path: Optional[str] = None
    pdflatex_excerpt: Optional[str] = None
    line_number: Optional[int] = None
