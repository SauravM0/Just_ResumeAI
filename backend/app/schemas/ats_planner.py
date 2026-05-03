from __future__ import annotations

from pydantic import BaseModel, Field


class ATSKeywordPlannerOutput(BaseModel):
    """ATS optimization plan that guides resume generation from the JD."""

    target_resume_title: str
    priority_keywords: list[str] = Field(default_factory=list)
    must_include_skills: list[str] = Field(default_factory=list)
    must_include_tools_platforms: list[str] = Field(default_factory=list)
    must_include_responsibilities: list[str] = Field(default_factory=list)
    suggested_section_ordering: list[str] = Field(default_factory=list)
    suggested_summary_themes: list[str] = Field(default_factory=list)
    suggested_project_emphasis: list[str] = Field(default_factory=list)
    missing_jd_keywords_from_current_draft: list[str] = Field(default_factory=list)
    resume_style_guidance: list[str] = Field(default_factory=list)
