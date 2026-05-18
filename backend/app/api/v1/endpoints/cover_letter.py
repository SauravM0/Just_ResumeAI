"""
Cover letter generation endpoint using generation_id.
Cover letters are saved to resume_generations.cover_letter_text.
"""

from fastapi import APIRouter, Depends, HTTPException
import logging

from app.dependencies.auth import get_current_user
from app.schemas.cover_letter import CoverLetterGenerateRequest, CoverLetterResponse, CoverLetterUpdateRequest
from app.schemas.supabase import ResumeGenerationUpdate
from app.ai.gemini_client import get_gemini_client, GeminiClientError
from app.services.generation_service import (
    get_generation,
    assert_generation_owner,
    update_generation,
    GenerationNotFoundError,
)
from app.services.supabase_service import get_supabase_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cover-letter", tags=["cover-letter"])

COVER_LETTER_SYSTEM_PROMPT = """You are an expert cover letter writer.

RULES:
1. Write in the specified tone - professional, confident, and tailored to the job.
2. Address the company by name if provided, otherwise use a professional generic greeting.
3. Highlight the most relevant experiences from the resume that match the job requirements.
4. Keep it to 3-4 paragraphs, 250-400 words.
5. Do NOT mention ATS scores, match reports, evidence, truthfulness, or internal metrics.
6. Reference specific achievements that align with the job responsibilities.
7. Mention key skills and keywords from the job description naturally.
8. Return ONLY the response as JSON with fields: cover_letter_text, word_count."""


@router.post("/{generation_id}/generate", response_model=CoverLetterResponse)
async def generate_cover_letter(
    generation_id: str,
    request: CoverLetterGenerateRequest,
    current_user = Depends(get_current_user),
):
    """
    Generate a tailored cover letter based on the generation's resume and JD.
    Saves the result to resume_generations.cover_letter_text.
    """
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")

    if not gen.resume_json:
        raise HTTPException(status_code=400, detail="No resume found for this generation")

    profile = request.profile
    parsed_jd = gen.parsed_jd_json
    resume_json = gen.resume_json

    if not parsed_jd:
        raise HTTPException(status_code=400, detail="No job description found for this generation")

    try:
        client = get_gemini_client()

        company_name = parsed_jd.get("company") or "the company"
        job_title = request.job_title or parsed_jd.get("job_title") or "the role"

        experience = resume_json.get("experience", [])
        exp_summary = "; ".join(
            f"{e.get('title', 'Role')} at {e.get('company', 'Company')}" 
            for e in experience[:3] if e.get("included", True)
        )
        
        resume_summary = resume_json.get("summary") or ""
        
        skills_groups = resume_json.get("skills", [])
        skills = ", ".join(
            s for sg in skills_groups for s in sg.get("skills", [])[:8]
        )
        
        kw_list = parsed_jd.get("keywords", []) or []
        jd_keywords = ", ".join(k["keyword"] if isinstance(k, dict) else k for k in kw_list[:10])
        
        responsibilities = "; ".join(parsed_jd.get("responsibilities", [])[:5]) if parsed_jd.get("responsibilities") else ""

        candidate_name = profile.contact.full_name or "Candidate"
        prompt = f"""Write a compelling cover letter for this job application.

TARGET ROLE: {job_title}
COMPANY: {company_name}
CANDIDATE: {candidate_name}
RESUME HEADLINE: {resume_json.get('target_title', '')}
RESUME SUMMARY: {resume_summary}
KEY EXPERIENCE: {exp_summary}
KEY SKILLS (from resume): {skills}
JD KEYWORDS (from job posting): {jd_keywords}
JD RESPONSIBILITIES: {responsibilities}
TONE: {request.tone}
{f'ADDITIONAL CONTEXT: {request.additional_context}' if request.additional_context else ''}

Write a compelling, personalized cover letter that:
- Opens with a strong hook mentioning the specific role and company
- Highlights 2-3 key experiences/skills that match the job requirements
- Mentions relevant keywords from the job posting naturally
- Connects the candidate's background to the company's needs
- Closes with a call to action
- Does NOT mention ATS scores, match reports, evidence, truthfulness, or any internal metrics"""

        from pydantic import BaseModel, Field

        class CLOutput(BaseModel):
            cover_letter_text: str
            word_count: int = 0

        result = await client.generate_structured(
            prompt=prompt,
            response_model=CLOutput,
            system_instruction=COVER_LETTER_SYSTEM_PROMPT,
        )

        cover_letter_text = result.cover_letter_text
        word_count = result.word_count or len(cover_letter_text.split())

        update_generation(
            current_user.user_id,
            generation_id,
            ResumeGenerationUpdate(cover_letter_text=cover_letter_text),
        )

        svc = get_supabase_service()
        svc.log_usage_event(
            current_user.user_id,
            "cover_letter_generate",
            metadata={
                "job_title": job_title,
                "company": company_name,
                "word_count": word_count,
            },
            generation_id=generation_id,
        )

        return CoverLetterResponse(
            generation_id=generation_id,
            cover_letter_text=cover_letter_text,
            word_count=word_count,
            warnings=[],
        )

    except GeminiClientError as e:
        logger.error(f"Cover letter generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI generation failed: {str(e)}")
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")
    except Exception as e:
        logger.error(f"Unexpected error in cover letter: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{generation_id}", response_model=CoverLetterResponse)
async def get_cover_letter(
    generation_id: str,
    current_user = Depends(get_current_user),
):
    """Get the cover letter for a generation."""
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")

    if not gen.cover_letter_text:
        raise HTTPException(status_code=404, detail="No cover letter found for this generation")

    word_count = len(gen.cover_letter_text.split())

    return CoverLetterResponse(
        generation_id=generation_id,
        cover_letter_text=gen.cover_letter_text,
        word_count=word_count,
        warnings=[],
    )


@router.put("/{generation_id}", response_model=CoverLetterResponse)
async def update_cover_letter(
    generation_id: str,
    request: CoverLetterUpdateRequest,
    current_user = Depends(get_current_user),
):
    """Update (save) the cover letter text for a generation."""
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError:
        raise HTTPException(status_code=404, detail="Generation not found")

    updated = update_generation(
        current_user.user_id,
        generation_id,
        ResumeGenerationUpdate(cover_letter_text=request.cover_letter_text),
    )

    word_count = len(updated.cover_letter_text.split()) if updated.cover_letter_text else 0

    return CoverLetterResponse(
        generation_id=generation_id,
        cover_letter_text=updated.cover_letter_text,
        word_count=word_count,
        warnings=[],
    )
