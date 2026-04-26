"""
End-to-end resume generation endpoint.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.ai.gemini_client import GeminiClientError
from app.ai.orchestrators.jd_orchestrator import analyze_jd
from app.ai.orchestrators.resume_orchestrator import generate_recommendation
from app.ai.resume_fallback import generate_recommendation_without_ai
from app.schemas.pipeline import (
    PipelineGenerateRequest,
    PipelineGenerateResponse,
    PipelinePdfResult,
    PipelineStepStatus,
)
from app.services.eligibility_service import check_eligibility
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import PDFCompileError, compile_pdf
from app.services.scoring_service import compute_ats_score
from app.services.session_service import create_session, save_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/generate", response_model=PipelineGenerateResponse)
async def generate_resume_pipeline(request: PipelineGenerateRequest):
    """
    Run Profile + JD through analysis, eligibility, recommendation, ATS, LaTeX,
    and optional PDF compilation in one explicit flow.
    """
    steps: list[PipelineStepStatus] = []
    warnings: list[str] = []
    session = None

    def mark(name: str, status: str, detail: str | None = None) -> None:
        steps.append(PipelineStepStatus(name=name, status=status, detail=detail))

    try:
        session = create_session()
        mark("create_session", "success")

        try:
            parsed_jd = await analyze_jd(request.raw_jd_text)
            session.parsed_jd = parsed_jd
            save_session(session)
            mark("analyze_jd", "success")
        except Exception as exc:
            logger.exception("[%s] JD analysis failed", session.session_id)
            mark("analyze_jd", "failed", str(exc))
            raise HTTPException(status_code=502, detail=f"JD analysis failed: {exc}") from exc

        eligibility = check_eligibility(request.profile, parsed_jd)
        if eligibility.status == "hard_mismatch":
            warnings.append("Resume can be generated, but this JD has hard eligibility mismatch.")
        warnings.extend(eligibility.blocking_issues)
        warnings.extend(eligibility.warnings)
        mark("eligibility_check", "success", eligibility.status)

        try:
            recommendation = await generate_recommendation(
                profile=request.profile,
                parsed_jd=parsed_jd,
                session_id=session.session_id,
                emphasis=request.emphasis,
            )
            mark("generate_recommendation", "success")
        except GeminiClientError as exc:
            logger.warning(
                "[%s] Gemini recommendation failed, using deterministic fallback: %s",
                session.session_id,
                exc,
            )
            recommendation = generate_recommendation_without_ai(
                profile=request.profile,
                parsed_jd=parsed_jd,
                session_id=session.session_id,
                emphasis=request.emphasis,
            )
            warnings.append(f"AI recommendation failed; deterministic fallback used: {exc}")
            mark("generate_recommendation", "success", "fallback_without_ai")
        except Exception as exc:
            logger.exception("[%s] Resume recommendation failed", session.session_id)
            mark("generate_recommendation", "failed", str(exc))
            raise HTTPException(status_code=500, detail=f"Resume recommendation failed: {exc}") from exc

        recommendation.warnings = _dedupe(
            ["Resume can be generated, but this JD has hard eligibility mismatch."]
            if eligibility.status == "hard_mismatch"
            else []
        ) + _dedupe(eligibility.blocking_issues + eligibility.warnings + recommendation.warnings)

        ats_score = compute_ats_score(recommendation, parsed_jd)
        mark("compute_ats_score", "success")

        try:
            latex_source = render_latex(recommendation)
            mark("render_latex", "success")
        except Exception as exc:
            logger.exception("[%s] LaTeX rendering failed", session.session_id)
            mark("render_latex", "failed", str(exc))
            raise HTTPException(status_code=500, detail=f"LaTeX rendering failed: {exc}") from exc

        session.recommendation = recommendation
        session.latex_source = latex_source
        save_session(session)
        mark("save_outputs", "success")

        pdf = PipelinePdfResult(requested=request.generate_pdf)
        if request.generate_pdf:
            try:
                pdf_path, compile_warnings = await compile_pdf(latex_source, session.session_id)
                pdf_filename = pdf_path.split("/")[-1].split("\\")[-1]
                pdf = PipelinePdfResult(
                    requested=True,
                    compile_success=True,
                    pdf_url=f"/api/v1/resume/download/{pdf_filename}",
                    compile_warnings=compile_warnings,
                )
                mark("compile_pdf", "success")
            except PDFCompileError as exc:
                message = "; ".join(exc.errors) if exc.errors else str(exc)
                warning = f"LaTeX generated successfully, PDF compile failed: {message}"
                warnings.append(warning)
                pdf = PipelinePdfResult(
                    requested=True,
                    compile_success=False,
                    compile_errors=exc.errors or [str(exc)],
                )
                mark("compile_pdf", "failed", message)
            except Exception as exc:
                logger.exception("[%s] Unexpected PDF compilation failure", session.session_id)
                warning = f"LaTeX generated successfully, PDF compile failed: {exc}"
                warnings.append(warning)
                pdf = PipelinePdfResult(
                    requested=True,
                    compile_success=False,
                    compile_errors=[str(exc)],
                )
                mark("compile_pdf", "failed", str(exc))
        else:
            mark("compile_pdf", "skipped", "generate_pdf=false")

        all_warnings = _dedupe(warnings + recommendation.warnings + parsed_jd.quality_warnings)

        return PipelineGenerateResponse(
            session_id=session.session_id,
            parsed_jd=parsed_jd,
            eligibility=eligibility,
            recommendation=recommendation,
            ats_score=ats_score,
            latex_source=latex_source,
            pdf=pdf,
            steps=steps,
            warnings=all_warnings,
        )

    except HTTPException:
        raise
    except Exception as exc:
        session_id = session.session_id if session else "no-session"
        logger.exception("[%s] Unexpected pipeline failure", session_id)
        raise HTTPException(status_code=500, detail=f"Pipeline generation failed: {exc}") from exc


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
