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
    EligibilityResult,
    PipelineGenerateRequest,
    PipelineGenerateResponse,
    PipelinePdfResult,
    PipelineStepStatus,
)
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.services.ats_pre_check import validate_ats_readiness
from app.services.keyword_placement_service import inject_missing_keywords, build_master_keyword_list
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import PDFCompileError, compile_pdf
from app.services.resume_budget_service import fit_resume_to_page_budget
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
    Run Profile + JD through analysis, recommendation, ATS, LaTeX,
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

        clean_profile = _flag_weak_profile_bullets(request.profile)
        ats_plan = build_ats_keyword_plan(
            parsed_jd=parsed_jd,
            profile=clean_profile,
            emphasis=request.emphasis,
            target_pages=request.target_pages,
        )
        mark("ats_keyword_plan", "success", f"{len(ats_plan.priority_keywords)} priority terms")

        eligibility = EligibilityResult()

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
            # ── Phase 5: Keyword Injection Post-Processor ─────────────────────────
            # Deterministically inject any JD keywords missing from the resume.
            # This runs after quality gate (so skills are populated) but before
            # strength service (so injected skills get properly categorized).
            # This guarantees 100% keyword coverage by construction.
            recommendation = inject_missing_keywords(
                recommendation=recommendation,
                parsed_jd=parsed_jd,
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
            recommendation = inject_missing_keywords(
                recommendation=recommendation,
                parsed_jd=parsed_jd,
                ats_plan=ats_plan,
            )
            mark("generate_recommendation", "success", "fallback_without_ai")
        except Exception as exc:
            logger.exception("[%s] Resume recommendation failed", session.session_id)
            mark("generate_recommendation", "failed", str(exc))
            raise HTTPException(status_code=500, detail="Resume recommendation failed. Please retry.") from exc

        recommendation.warnings = _dedupe(recommendation.warnings)
        recommendation = fit_resume_to_page_budget(
            recommendation=recommendation,
            parsed_jd=parsed_jd,
            ats_plan=ats_plan,
            target_pages=request.target_pages,
        )

        # ── Pipeline-level always-generate safety net ────────────────────
        recommendation = _enforce_always_generate_contract(
            recommendation=recommendation,
            parsed_jd=parsed_jd,
            clean_profile=clean_profile,
            ats_plan=ats_plan,
            warnings=warnings,
        )

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
            ats_plan=ats_plan,
        )
        ats_pre_check = validate_ats_readiness(recommendation, parsed_jd)
        for warning in [*ats_pre_check.critical_gaps, *ats_pre_check.warnings]:
            logger.warning("[%s] ATS pre-check: %s", session.session_id, warning)
        mark("compute_ats_score", "success")
        mark("ats_pre_check", "success", f"{ats_pre_check.overall_estimated_ats_score:.0%} estimated readiness")
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
            ats_pre_check=ats_pre_check,
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


def _enforce_always_generate_contract(
    recommendation,
    parsed_jd,
    clean_profile,
    ats_plan,
    warnings: list[str],
):
    """
    Pipeline-level safety net: guarantees minimum viable resume content.

    GATE 1: Must have ≥1 experience entry with ≥2 bullets.
    GATE 2: Must have ≥1 skill group with ≥5 skills.
    GATE 3: Summary must be ≥30 words.

    If any gate fails, inject from the available profile/JD material
    rather than returning an incomplete resume.
    """
    from app.services.resume_quality_gate import build_skill_taxonomy
    from app.schemas.resume import ResumeSkillGroup

    rec = recommendation

    # GATE 1 — Experience with bullets
    has_valid_exp = any(
        exp.included and len(exp.bullets) >= 2
        for exp in rec.experience
    )
    if not has_valid_exp:
        warnings.append(
            "Pipeline gate: No experience entry had ≥2 bullets. "
            "Skills + education used as primary content. "
            "Consider adding work experience or projects to the master profile."
        )
        logger.warning("Pipeline Gate 1 fired: no experience with 2+ bullets.")

    # GATE 2 — Skills populated
    total_skills = sum(len(g.skills) for g in rec.skills)
    if total_skills < 5:
        warnings.append("Pipeline gate: Skill groups were thin — injecting JD required skills.")
        logger.warning("Pipeline Gate 2 fired: fewer than 5 skills. Injecting JD terms.")
        rec.skills = build_skill_taxonomy(rec.skills, parsed_jd, clean_profile, target_pages=1)
        total_skills = sum(len(g.skills) for g in rec.skills)
        if total_skills < 5:
            # Emergency fallback: dump all JD required skills into one group.
            emergency_skills = [
                *parsed_jd.required_skills,
                *parsed_jd.programming_languages,
                *parsed_jd.frameworks[:6],
                *parsed_jd.tools_platforms[:6],
            ]
            clean_skills = list(dict.fromkeys(s.strip() for s in emergency_skills if s.strip()))[:25]
            if clean_skills:
                rec.skills = [ResumeSkillGroup(category="Technical Skills", skills=clean_skills)]

    # GATE 3 — Summary length
    summary_words = len((rec.summary or "").split())
    if summary_words < 30:
        warnings.append(
            f"Pipeline gate: Summary was only {summary_words} words. "
            "Add more profile context for a stronger ATS summary."
        )
        logger.warning("Pipeline Gate 3 fired: summary under 30 words (%d).", summary_words)
        if not rec.summary or summary_words < 5:
            title = rec.target_title or parsed_jd.job_title or "Software Developer"
            jd_skills = ", ".join(parsed_jd.required_skills[:6])
            company = parsed_jd.company or "the organization"
            rec = rec.model_copy(update={
                "summary": (
                    f"{title} candidate with a strong foundation in {jd_skills}. "
                    f"Seeking to contribute to {company} through applied technical expertise, "
                    f"delivering reliable solutions aligned with role requirements and team goals."
                )
            })

    return rec


def _flag_weak_profile_bullets(profile):
    """Mark weak PDF-ingested bullets so the composer rewrites them instead of copying."""
    weak_phrases = ("basic technical knowledge", "analytical skills", "showcasing", "demonstrating", "responsible for", "worked on")
    updates = {}
    work_experience = []
    for exp in profile.work_experience:
        text = " ".join(exp.bullets).casefold()
        needs_rewrite = exp.needs_rewrite or any(phrase in text for phrase in weak_phrases) or any(len(b.strip()) < 80 for b in exp.bullets)
        work_experience.append(exp.model_copy(update={"needs_rewrite": needs_rewrite}))
    projects = []
    for project in profile.projects:
        text = " ".join(project.bullets).casefold()
        needs_rewrite = project.needs_rewrite or any(phrase in text for phrase in weak_phrases) or any(len(b.strip()) < 80 for b in project.bullets)
        projects.append(project.model_copy(update={"needs_rewrite": needs_rewrite}))
    updates["work_experience"] = work_experience
    updates["projects"] = projects
    return profile.model_copy(update=updates)
