"""
Resume generations endpoints — retrieve and list user generations.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies.auth import get_current_user
from app.services.generation_service import get_generation, list_generations
from app.schemas.supabase import ResumeGenerationRecord

router = APIRouter(prefix="/generations", tags=["generations"])


@router.get("/{generation_id}", response_model=ResumeGenerationRecord)
async def get_generation_endpoint(
    generation_id: str,
    current_user = Depends(get_current_user),
):
    """
    Retrieve a specific generation by ID.
    """
    generation = get_generation(current_user.user_id, generation_id)
    if generation is None:
        raise HTTPException(status_code=404, detail="Generation not found")
    return generation


@router.get("", response_model=list[ResumeGenerationRecord])
async def list_user_generations(
    current_user = Depends(get_current_user),
    limit: int = 25,
):
    """
    List all generations for the authenticated user.
    """
    return list_generations(current_user.user_id, limit=limit)