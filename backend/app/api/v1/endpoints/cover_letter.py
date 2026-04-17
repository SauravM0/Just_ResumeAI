"""
Cover letter generation endpoint.
"""

from fastapi import APIRouter, HTTPException
import logging

from app.schemas.cover_letter import CoverLetterRequest, CoverLetterResponse
from app.ai.gemini_client import get_gemini_client, GeminiClientError
from app.services.session_service import get_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cover-letter", tags=["cover-letter"])

COVER_LETTER_SYSTEM_PROMPT = """You are an expert cover letter writer.

RULES:
1. Write in the specified tone.
2. Address the specific job and company.
3. Highlight the most relevant experiences from the resume.
4. Keep it to 3-4 paragraphs, 250-400 words.
5. Be genuine, not generic.
6. Reference specific achievements from the candidate's profile.
7. Return ONLY the response as JSON with fields: cover_letter_text, word_count."""


class _CoverLetterOutput(CoverLetterResponse):
    """Internal model for Gemini output parsing (includes inherited fields)."""
    pass


@router.post("/generate", response_model=CoverLetterResponse)
async def generate_cover_letter(request: CoverLetterRequest):
    """
    Generate a tailored cover letter based on the resume recommendation and JD.
    Should only be called after the core resume flow is complete.
    """
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        client = get_gemini_client()

        # Build context from resume and JD
        exp_summary = "; ".join(
            f"{e.title} at {e.company}" for e in request.recommendation.experience[:3]
        )
        skills = ", ".join(
            s for sg in request.recommendation.skills for s in sg.skills[:5]
        )

        prompt = f"""Write a cover letter for this application.

JOB: {request.parsed_jd.job_title} at {request.parsed_jd.company or 'the company'}
CANDIDATE: {request.profile.contact.full_name}
RESUME HEADLINE: {request.recommendation.target_title}
KEY EXPERIENCE: {exp_summary}
KEY SKILLS: {skills}
TONE: {request.tone}
{f'ADDITIONAL CONTEXT: {request.additional_context}' if request.additional_context else ''}

Write a compelling, personalized cover letter."""

        from pydantic import BaseModel, Field

        class CLOutput(BaseModel):
            cover_letter_text: str
            word_count: int = 0

        result = await client.generate_structured(
            prompt=prompt,
            response_model=CLOutput,
            system_instruction=COVER_LETTER_SYSTEM_PROMPT,
        )

        return CoverLetterResponse(
            session_id=request.session_id,
            cover_letter_text=result.cover_letter_text,
            word_count=result.word_count or len(result.cover_letter_text.split()),
        )

    except GeminiClientError as e:
        logger.error(f"Cover letter generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI generation failed: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in cover letter: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
