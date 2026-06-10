from __future__ import annotations

from pydantic import BaseModel, Field
from app.schemas.jd import RequirementPriority, RequirementPlacement


class PlannedRequirement(BaseModel):
    """A prioritized requirement mapped to a specific resume placement."""
    text: str
    priority: RequirementPriority
    placement: list[RequirementPlacement]
    is_supported: bool = False
    synonyms: list[str] = Field(default_factory=list)


class ATSKeywordPlannerOutput(BaseModel):
    """ATS optimization plan that guides resume generation from the JD."""

    target_resume_title: str
    candidate_seniority: str | None = None
    seniority_adjusted: bool = False
    seniority_warnings: list[str] = Field(default_factory=list)
    priority_keywords: list[str] = Field(default_factory=list)
    must_include_skills: list[str] = Field(default_factory=list)
    must_include_tools_platforms: list[str] = Field(default_factory=list)
    must_include_responsibilities: list[str] = Field(default_factory=list)
    
    # Granular requirement planning
    requirement_plan: list[PlannedRequirement] = Field(default_factory=list)
    
    suggested_section_ordering: list[str] = Field(default_factory=list)
    suggested_summary_themes: list[str] = Field(default_factory=list)
    suggested_project_emphasis: list[str] = Field(default_factory=list)
    missing_jd_keywords_from_current_draft: list[str] = Field(default_factory=list)
    resume_style_guidance: list[str] = Field(default_factory=list)
