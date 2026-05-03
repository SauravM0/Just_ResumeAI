"""
Cover letter generation endpoint.
"""

from fastapi import APIRouter, Depends, HTTPException
import logging

from app.dependencies.user import get_current_user_id
from app.schemas.cover_letter import CoverLetterRequest, CoverLetterResponse
from app.ai.gemini_client import get_gemini_client, GeminiClientError
from app.services.session_service import get_session

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


class _CoverLetterOutput(CoverLetterResponse):
    """Internal model for Gemini output parsing (includes inherited fields)."""
    pass


@router.post("/generate", response_model=CoverLetterResponse)
async def generate_cover_letter(
    request: CoverLetterRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Generate a tailored cover letter based on the resume recommendation and JD.
    Uses JD optimization to align cover letter with job requirements.
    """
    session = get_session(request.session_id, user_id=user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    try:
        client = get_gemini_client()

        company_name = request.parsed_jd.company or "the company"
        job_title = request.job_title or request.parsed_jd.job_title or "the role"

        exp_summary = "; ".join(
            f"{e.title} at {e.company}" for e in request.recommendation.experience[:3]
        )
        
        resume_summary = request.recommendation.summary or ""
        
        skills = ", ".join(
            s for sg in request.recommendation.skills for s in sg.skills[:8]
        )

        jd_keywords = ", ".join(request.parsed_jd.keywords[:10]) if request.parsed_jd.keywords else ""
        
        responsibilities = "; ".join(request.parsed_jd.responsibilities[:5]) if request.parsed_jd.responsibilities else ""

        prompt = f"""Write a compelling cover letter for this job application.

TARGET ROLE: {job_title}
COMPANY: {company_name}
CANDIDATE: {request.profile.contact.full_name}
RESUME HEADLINE: {request.recommendation.target_title}
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