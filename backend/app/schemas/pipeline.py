"""
End-to-end resume generation pipeline schemas.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.jd import ParsedJD
from app.schemas.alignment import ATSAlignmentReport
from app.schemas.profile import MasterProfile
from app.schemas.resume import ResumeRecommendation
from app.schemas.scoring import ATSScore


EligibilityStatus = Literal["match", "partial_match", "hard_mismatch"]
PipelineStepState = Literal["pending", "success", "failed", "skipped"]


class EligibilityResult(BaseModel):
    status: EligibilityStatus
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    matched_points: list[str] = Field(default_factory=list)


class PipelineStepStatus(BaseModel):
    name: str
    status: PipelineStepState
    detail: Optional[str] = None


class PipelineGenerateRequest(BaseModel):
    profile: MasterProfile
    raw_jd_text: str = Field(..., min_length=50, max_length=15000)
    target_pages: int = Field(default=1, ge=1, le=2)
    allow_two_pages_for_senior: bool = True
    generate_pdf: bool = False
    emphasis: Optional[str] = None
    additional_alignment_text: Optional[str] = Field(
        default=None,
        max_length=6000,
        description="Optional JD emphasis or keyword guidance."
    )


class PipelinePdfResult(BaseModel):
    requested: bool = False
    compile_success: bool = False
    pdf_url: Optional[str] = None
    compile_errors: list[str] = Field(default_factory=list)
    compile_warnings: list[str] = Field(default_factory=list)
    generated_tex_path: Optional[str] = None
    pdflatex_excerpt: Optional[str] = None
    line_number: Optional[int] = None


class PipelineGenerateResponse(BaseModel):
    session_id: str
    parsed_jd: ParsedJD
    eligibility: EligibilityResult
    recommendation: ResumeRecommendation
    ats_score: ATSScore
    alignment_report: ATSAlignmentReport
    latex_source: str
    pdf: PipelinePdfResult = Field(default_factory=PipelinePdfResult)
    steps: list[PipelineStepStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
