"""
History endpoints for resume generations.
Provides permanent history backed by Supabase resume_generations table.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import get_current_user
from app.services.generation_service import (
    list_generations,
    update_generation,
    assert_generation_owner,
    GenerationNotFoundError,
)
from app.services.storage_service import summarize_generation_files
from app.schemas.supabase import ResumeGenerationUpdate

router = APIRouter(prefix="/history", tags=["history"])


def _get_file_expiry_info(user_id: str, generation_id: str) -> dict:
    """Exports are downloaded directly, so no generated file metadata is stored."""
    return summarize_generation_files([])


@router.get("", response_model=list[dict])
async def get_history(
    current_user = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    """
    List user's resume generations with summary info.
    Returns generation_id, job_title, company, created_at, status, and ATS score summary.
    """
    generations = list_generations(current_user.user_id, limit=limit, offset=offset)
    
    # Transform for summary view
    result = []
    for gen in generations:
        ats_score = gen.ats_score_json or {}
        file_expiry = _get_file_expiry_info(str(current_user.user_id), str(gen.id))
        file_expiry["regenerate_available"] = bool(gen.resume_json and gen.parsed_jd_json)
        result.append({
            "generation_id": str(gen.id),
            "job_title": gen.job_title,
            "company": gen.company,
            "created_at": gen.created_at.isoformat() if gen.created_at else None,
            "updated_at": gen.updated_at.isoformat() if gen.updated_at else None,
            "status": gen.status,
            "ats_score_summary": {
                "overall_score": ats_score.get("overall_score"),
                "keyword_coverage": ats_score.get("keyword_score", {}).get("coverage_percent"),
            },
            "has_pdf": bool(file_expiry.get("pdf_available")),
            "has_cover_letter": bool(gen.cover_letter_text),
            "file_expiry_info": file_expiry,
        })
    
    return result


@router.get("/{generation_id}", response_model=dict)
async def get_history_detail(
    generation_id: str,
    current_user = Depends(get_current_user),
):
    """
    Get full details for a specific generation.
    """
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")
    
    file_expiry = _get_file_expiry_info(str(current_user.user_id), generation_id)
    file_expiry["regenerate_available"] = bool(gen.resume_json and gen.parsed_jd_json)
    
    return {
        "generation_id": str(gen.id),
        "job_title": gen.job_title,
        "company": gen.company,
        "raw_jd_text": gen.raw_jd_text,
        "parsed_jd_json": gen.parsed_jd_json,
        "resume_json": gen.resume_json,
        "ats_score_json": gen.ats_score_json,
        "alignment_report_json": gen.alignment_report_json,
        "ats_pre_check_json": gen.ats_pre_check_json,
        "recruiter_review_json": gen.recruiter_review_json,
        "cover_letter_text": gen.cover_letter_text,
        "latex_source": gen.latex_source,
        "docx_fallback_path": gen.docx_fallback_path,
        "pdf_compile_error": gen.pdf_compile_error,
        "status": gen.status,
        "created_at": gen.created_at.isoformat() if gen.created_at else None,
        "updated_at": gen.updated_at.isoformat() if gen.updated_at else None,
        "has_pdf": bool(file_expiry.get("pdf_available")),
        "has_cover_letter": bool(gen.cover_letter_text),
        "file_expiry_info": file_expiry,
    }


@router.patch("/{generation_id}", response_model=dict)
async def update_history(
    generation_id: str,
    update_data: dict,
    current_user = Depends(get_current_user),
):
    """
    Update a generation. Supports:
    - status, cover_letter_text, latex_source (legacy)
    - resume_json (for visual editor saves)
    """
    try:
        assert_generation_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")
    
    allowed_fields = ["status", "cover_letter_text", "latex_source", "resume_json", "ats_score_json"]
    filtered_data = {k: v for k, v in update_data.items() if k in allowed_fields}
    
    if not filtered_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    
    gen = update_generation(
        current_user.user_id,
        generation_id,
        ResumeGenerationUpdate(**filtered_data),
    )
    
    return {
        "generation_id": str(gen.id),
        "status": gen.status,
        "updated_at": gen.updated_at.isoformat() if gen.updated_at else None,
    }


@router.delete("/{generation_id}", response_model=dict)
async def delete_history(
    generation_id: str,
    current_user = Depends(get_current_user),
):
    """
    Delete a generation. This is a soft delete by setting status to 'archived'.
    """
    try:
        assert_generation_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")
    
    gen = update_generation(
        current_user.user_id,
        generation_id,
        ResumeGenerationUpdate(status="archived"),
    )
    
    return {
        "generation_id": str(gen.id),
        "status": gen.status,
        "message": "Generation archived successfully",
    }
