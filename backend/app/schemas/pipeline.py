"""
End-to-end resume generation pipeline schemas.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.jd import ParsedJD
from app.schemas.alignment import ATSAlignmentReport
from app.schemas.profile import MasterProfile
from app.schemas.resume import ResumeRecommendation
from app.schemas.scoring import ATSScore
from app.schemas.validation import ValidationStatus
from app.agents.resume_agent.recruiter_review_agent import RecruiterReview
from app.services.candidate_evidence_service import KeywordTruthReport
from app.services.ats_pre_check import ATSPreCheckResult


EligibilityStatus = Literal["match", "partial_match", "hard_mismatch"]
PipelineStepState = Literal["pending", "success", "failed", "skipped"]
ATSOptimizationMode = Literal["realistic", "aggressive"]


class EligibilityResult(BaseModel):
    """Deprecated compatibility field; the MVP no longer gates resume generation."""

    status: EligibilityStatus = "match"
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
    ats_optimization_mode: ATSOptimizationMode = Field(
        default="aggressive",
        description="'realistic' uses evidence-backed tailoring; 'aggressive' maximizes ATS keyword coverage by injecting JD-aligned skills and claims.",
    )


class PipelinePdfResult(BaseModel):
    requested: bool = False
    compile_success: bool = False
    pdf_url: Optional[str] = None
    docx_fallback_path: Optional[str] = None
    pdf_failed: bool = False
    user_message: Optional[str] = None
    expires_at: Optional[str] = None
    compile_errors: list[str] = Field(default_factory=list)
    compile_warnings: list[str] = Field(default_factory=list)
    inspection_warnings: list[str] = Field(default_factory=list)
    page_count: Optional[int] = None
    target_pages: Optional[int] = None
    compression_applied: bool = False
    compression_actions: list[str] = Field(default_factory=list)
    generated_tex_path: Optional[str] = None
    pdflatex_excerpt: Optional[str] = None
    line_number: Optional[int] = None


class OptimizationAttemptDiagnostics(BaseModel):
    attempt: int
    json_score: ATSScore
    pdf_text_score: ATSScore | None = None
    missing_keywords: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    title_alignment_score: float = 0.0
    skills_coverage_percent: float = 0.0
    section_quality_score: float = 0.0
    page_count: int | None = None
    compile_success: bool = False
    repair_actions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ResumeOptimizationResult(BaseModel):
    target_score: float = 90.0
    target_pages: int = 1
    attempts_used: int = 0
    reached_target: bool = False
    final_score_source: str = "pdf_text"
    final_pdf_text_score: ATSScore | None = None
    final_json_score: ATSScore | None = None
    final_page_count: int | None = None
    final_pdf_path: str | None = None
    final_docx_fallback_path: str | None = None
    pdf_compile_error: str | None = None
    pdf_failed: bool = False
    final_latex_source: str = ""
    final_recommendation: ResumeRecommendation
    recruiter_review: RecruiterReview | None = None
    locked_fields: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[OptimizationAttemptDiagnostics] = Field(default_factory=list)
    score_history: list[float] = Field(default_factory=list)
    strategy_history: list[str] = Field(default_factory=list)
    repair_passes_used: int = 0
    missing_keywords: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    title_alignment_score: float = 0.0
    skills_coverage_percent: float = 0.0
    section_quality_score: float = 0.0
    score_explanation: list[str] = Field(default_factory=list)
    compile_warnings: list[str] = Field(default_factory=list)


class PipelineOptimizedGenerateRequest(PipelineGenerateRequest):
    generate_pdf: bool = True
    target_ats_score: float = Field(default=95.0, ge=0.0, le=100.0)
    max_repair_attempts: int = Field(default=5, ge=1, le=7)


class PipelineOptimizedGenerateResponse(BaseModel):
    generation_id: str
    parsed_jd: ParsedJD
    recommendation: ResumeRecommendation
    latex_source: str
    pdf: PipelinePdfResult
    optimization: ResumeOptimizationResult
    ats_score: ATSScore
    alignment_report: ATSAlignmentReport
    recruiter_review: RecruiterReview | None = None
    steps: list[PipelineStepStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus = Field(default_factory=ValidationStatus)
    retry_count: int = Field(default=0, description="Number of Gemini API retries during this generation")


class PipelineGenerateResponse(BaseModel):
    generation_id: str
    parsed_jd: ParsedJD
    eligibility: EligibilityResult
    recommendation: ResumeRecommendation
    ats_score: ATSScore
    alignment_report: ATSAlignmentReport
    ats_pre_check: ATSPreCheckResult | None = None
    latex_source: str
    pdf: PipelinePdfResult = Field(default_factory=PipelinePdfResult)
    steps: list[PipelineStepStatus] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recruiter_review: RecruiterReview | None = None
    blocked_reasons: list[str] = Field(default_factory=list)
    evidence_report: KeywordTruthReport | None = None
    export_ready: bool = False
    validation_status: ValidationStatus = Field(default_factory=ValidationStatus)


# Rebuild models to resolve ForwardRefs
PipelineOptimizedGenerateRequest.model_rebuild()
PipelineOptimizedGenerateResponse.model_rebuild()
ResumeOptimizationResult.model_rebuild()
PipelineGenerateRequest.model_rebuild()
PipelineGenerateResponse.model_rebuild()
