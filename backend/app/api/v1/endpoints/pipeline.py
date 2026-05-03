"""
End-to-end resume generation endpoint.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.dependencies.user import get_current_user_id
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
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import PDFCompileError, compile_pdf
from app.services.scoring_service import compute_ats_score
from app.services.session_service import create_session, save_session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _safe_tex_reference(path: str | None) -> str | None:
    if not path:
        return None
    if get_settings().DEBUG:
        return path
    return Path(path).name


@router.post("/generate", response_model=PipelineGenerateResponse)
async def generate_resume_pipeline(
    request: PipelineGenerateRequest,
    user_id: str = Depends(get_current_user_id),
):
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
        session = create_session(user_id=user_id)
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

        clean_profile = request.profile
        ats_plan = build_ats_keyword_plan(
            parsed_jd=parsed_jd,
            profile=clean_profile,
            emphasis=request.emphasis,
            target_pages=request.target_pages,
        )
        mark("ats_keyword_plan", "success", f"{len(ats_plan.priority_keywords)} priority terms")

        eligibility = check_eligibility(clean_profile, parsed_jd)
        if eligibility.status == "hard_mismatch":
            warnings.append("Resume can be generated, but this JD has hard eligibility mismatch.")
        warnings.extend(eligibility.blocking_issues)
        warnings.extend(eligibility.warnings)
        mark("eligibility_check", "success", eligibility.status)

        try:
            recommendation = await generate_recommendation(
                profile=clean_profile,
                parsed_jd=parsed_jd,
                session_id=session.session_id,
                emphasis=request.emphasis,
                target_pages=request.target_pages,
                additional_alignment_text=request.additional_alignment_text,
                ats_plan=ats_plan,
            )
            mark("generate_recommendation", "success")
        except GeminiClientError as exc:
            logger.warning(
                "[%s] Gemini recommendation failed, using deterministic fallback: %s",
                session.session_id,
                exc,
            )
            recommendation = generate_recommendation_without_ai(
                profile=clean_profile,
                parsed_jd=parsed_jd,
                session_id=session.session_id,
                emphasis=request.emphasis,
                target_pages=request.target_pages,
                additional_alignment_text=request.additional_alignment_text,
                ats_plan=ats_plan,
            )
            warnings.append(f"AI recommendation failed; deterministic fallback used: {exc}")
            mark("generate_recommendation", "success", "fallback_without_ai")
        except Exception as exc:
            logger.exception("[%s] Resume recommendation failed", session.session_id)
            mark("generate_recommendation", "failed", str(exc))
            raise HTTPException(status_code=500, detail="Resume recommendation failed. Please retry.") from exc

        recommendation.warnings = _dedupe(
            ["Resume can be generated, but this JD has hard eligibility mismatch."]
            if eligibility.status == "hard_mismatch"
            else []
        ) + _dedupe(eligibility.blocking_issues + eligibility.warnings + recommendation.warnings)

        ats_plan = build_ats_keyword_plan(
            parsed_jd=parsed_jd,
            profile=clean_profile,
            emphasis=request.emphasis,
            target_pages=request.target_pages,
            current_draft=recommendation,
        )
        ats_score = compute_ats_score(recommendation, parsed_jd, ats_plan=ats_plan)
        alignment_report = build_ats_alignment_report(
            parsed_jd=parsed_jd,
            recommendation=recommendation,
            formatting_score=ats_score.format_score,
        )
        mark("compute_ats_score", "success")
        mark("ats_alignment_report", "success", f"{alignment_report.overall_alignment_percent:.0f}% alignment")

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
                pdf_path, compile_warnings = await compile_pdf(
                    latex_source=latex_source,
                    session_id=session.session_id,
                )
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
                logger.error(
                    "[%s] Pipeline PDF compilation failed. tex=%s line=%s errors=%s excerpt=%s raw=%s",
                    session.session_id,
                    exc.generated_tex_path,
                    exc.line_number,
                    exc.errors,
                    exc.pdflatex_excerpt,
                    (exc.raw_output or "")[-4000:],
                )
                pdf = PipelinePdfResult(
                    requested=True,
                    compile_success=False,
                    compile_errors=exc.response_errors(),
                    compile_warnings=exc.warnings,
                    generated_tex_path=_safe_tex_reference(exc.generated_tex_path),
                    pdflatex_excerpt=exc.pdflatex_excerpt,
                    line_number=exc.line_number,
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
            alignment_report=alignment_report,
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
        raise HTTPException(status_code=500, detail="Pipeline generation failed. Please retry.") from exc


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
