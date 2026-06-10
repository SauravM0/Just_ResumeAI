"""Fast resume generation endpoint."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.ai.gemini_client import GeminiClientError
from app.dependencies.auth import get_current_user_id
from app.schemas.profile import MasterProfile
from app.services.fast_resume_service import FastResumeService
from app.services.supabase_service import SupabaseDatabaseError, SupabaseServiceConfigError

router = APIRouter(prefix="/resume", tags=["resume"])


class FastResumeGenerateRequest(BaseModel):
    profile: MasterProfile
    raw_jd_text: str | None = Field(default=None, min_length=50, max_length=15000)
    source_generation_id: str | None = None
    job_title: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    emphasis: str | None = Field(default=None, max_length=1000)
    target_pages: int = Field(default=1, ge=1, le=2)
    save_to_database: bool = True
    ats_optimization_mode: Literal["realistic", "aggressive"] = "aggressive"

    @model_validator(mode="after")
    def require_jd_or_source(self):
        if not self.raw_jd_text and not self.source_generation_id:
            raise ValueError("raw_jd_text is required unless source_generation_id is provided")
        return self


class FastResumeGenerateResponse(BaseModel):
    generation_id: str
    persisted: bool
    resume_json: dict[str, Any]
    ats_score: int
    matched_keywords: list[str]
    missing_keywords: list[str]
    extracted_keywords: list[str]
    confirmed_keywords: list[dict[str, str]] = Field(default_factory=list)
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    score_explanation: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    score_disclaimer: str = "Fast deterministic estimate for comparison, not a guaranteed ATS result."


KeywordConfirmationLevel = Literal["professional", "project", "basic", "learning", "no"]


class KeywordConfirmation(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=120)
    level: KeywordConfirmationLevel


class ConfirmKeywordsRequest(BaseModel):
    keywords: list[KeywordConfirmation] = Field(default_factory=list, max_length=80)


class ConfirmKeywordsResponse(BaseModel):
    generation_id: str
    confirmed_keywords: list[dict[str, str]]
    usable_keywords: list[dict[str, str]]


def get_fast_resume_service() -> FastResumeService:
    return FastResumeService()


@router.post("/fast-generate", response_model=FastResumeGenerateResponse)
async def fast_generate_resume(
    request: FastResumeGenerateRequest,
    user_id: str = Depends(get_current_user_id),
    service: FastResumeService = Depends(get_fast_resume_service),
):
    """Generate resume JSON quickly without PDF, DOCX, recruiter review, RAG, or repair loops."""
    try:
        return await service.generate(
            user_id=user_id,
            profile=request.profile,
            raw_jd_text=request.raw_jd_text,
            source_generation_id=request.source_generation_id,
            job_title=request.job_title,
            company=request.company,
            emphasis=request.emphasis,
            target_pages=request.target_pages,
            save_to_database=request.save_to_database,
            ats_optimization_mode=request.ats_optimization_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GeminiClientError as exc:
        import logging
        logging.getLogger(__name__).error("Gemini Generation Error: %s", str(exc), exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Fast resume generation failed due to Gemini error: {str(exc)}",
        ) from exc


@router.post("/{generation_id}/confirm-keywords", response_model=ConfirmKeywordsResponse)
async def confirm_fast_keywords(
    generation_id: str,
    request: ConfirmKeywordsRequest,
    user_id: str = Depends(get_current_user_id),
    service: FastResumeService = Depends(get_fast_resume_service),
):
    """Persist temporary fast-generation keyword confirmation context."""
    try:
        confirmations = {item.keyword: item.level for item in request.keywords}
        return service.confirm_keywords(
            user_id=user_id,
            generation_id=generation_id,
            confirmations=confirmations,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SupabaseDatabaseError, SupabaseServiceConfigError) as exc:
        raise HTTPException(status_code=503, detail="Could not save keyword confirmations. Please retry.") from exc
