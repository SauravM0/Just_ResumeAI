"""
End-to-end resume generation endpoint.
"""

import logging
import time as _time
from pathlib import Path
from typing import Any, Callable, Coroutine

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.application.use_cases.generation_result import (
    GENERATION_STATUS_COMPLETED,
    GENERATION_STATUS_RUNNING,
    current_step_for_status,
    get_generation_result_for_user,
    progress_for_status,
    status_payload,
    update_generation_status,
    utc_now,
)
from app.application.use_cases.generation_runner import (
    cleanup_generation_channel,
    fail_generation,
    log_generation_step,
)
from app.application.use_cases.generation_start import start_generation_use_case
from app.application.use_cases.generation_stream import generation_stream_events
from app.config import get_settings
from app.dependencies.auth import get_current_user
from app.main import limiter
from app.utils.observability import get_request_id
from app.ai.gemini_client import GeminiClientError, get_gemini_client
from app.ai.orchestrators.jd_orchestrator import analyze_jd
from app.schemas.pipeline import (
    EligibilityResult,
    PipelineGenerateRequest,
    PipelineGenerateResponse,
    PipelineOptimizedGenerateRequest,
    PipelineOptimizedGenerateResponse,
    PipelinePdfResult,
    PipelineStepStatus,
)
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.services.jd_cache_service import cache_jd_result, get_cached_jd
from app.services.keyword_placement_service import inject_missing_keywords
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import PDFCompileError
from app.services.pdf_page_fit_service import compile_pdf_to_page_target
from app.services.resume_budget_service import fit_resume_to_page_budget
from app.services.resume_optimization_loop import optimize_resume_for_ats, _final_keyword_repair
from app.services.rag_retrieval_service import retrieve_evidence_for_requirements
from app.services.resume_validation_gate import (
    ResumeValidationError,
    build_validation_status,
    validate_resume_for_export,
)
from app.services.scoring_service import compute_ats_score, compute_ats_score_from_text
from app.services.jd_sanitization_service import (
    INVALID_JD_USER_MESSAGE,
    InvalidJobDescriptionError,
    ResumeContaminationError,
    assert_parsed_jd_safe,
    assert_render_text_safe,
    assert_resume_recommendation_safe,
    recommendation_to_plain_text,
    require_valid_jd_text,
    sanitize_parsed_jd,
)
from app.services.generation_service import (
    GenerationNotFoundError,
    assert_generation_owner,
    create_generation,
    update_generation,
)
from app.services.generation_progress_service import (
    emit_progress,
    has_progress_channel,
    send_complete,
    set_generation_user,
)
from app.services.metrics_service import (
    GenerationTimer,
    record_generation_completed,
    record_generation_failed,
    record_generation_started,
)
from app.services.supabase_service import get_supabase_service
from app.schemas.supabase import ResumeGenerationUpdate
from app.schemas.profile import MasterProfile
from app.schemas.jd import ParsedJD

# ── Progress tracking ─────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_log_generation_step = log_generation_step
_update_generation_status = update_generation_status
_utc_now = utc_now
_fail_generation = fail_generation
_current_step_for_status = current_step_for_status
_progress_for_status = progress_for_status
_status_payload = status_payload


def _safe_tex_reference(path: str | None) -> str | None:
    if not path:
        return None
    if get_settings().DEBUG:
        return path
    return Path(path).name


@router.post("/generate", response_model=PipelineOptimizedGenerateResponse)
@router.post("/generate/optimized", response_model=PipelineOptimizedGenerateResponse)
@limiter.limit("5/hour")
async def generate_optimized_resume_pipeline(
    request: Request,
    body: PipelineOptimizedGenerateRequest,
    current_user=Depends(get_current_user),
):
    """
    Generate a resume through the deterministic final ATS optimization loop.

    The returned score is based on text extracted from the compiled PDF, not
    only the internal recommendation JSON.
    """
    MAX_JD_LENGTH = 15_000
    raw_jd_text = body.raw_jd_text
    if len(raw_jd_text) > MAX_JD_LENGTH:
        raw_jd_text = raw_jd_text[:MAX_JD_LENGTH]
        logger.warning("JD text truncated to %d chars for pipeline generation", MAX_JD_LENGTH)

    steps: list[PipelineStepStatus] = []
    warnings: list[str] = []
    generation_id: str | None = None
    pipeline_start = _time.perf_counter()
    user_id_str = current_user.user_id
    cache_hit = False

    def mark(name: str, status: str, detail: str | None = None) -> None:
        steps.append(PipelineStepStatus(name=name, status=status, detail=detail))

    MIN_JD_LENGTH = 50
    if not raw_jd_text or len(raw_jd_text.strip()) < MIN_JD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Job description is too short ({len(raw_jd_text.strip())} characters). "
                   f"Please provide at least {MIN_JD_LENGTH} characters for meaningful analysis.",
        )

    try:
        sanitization = require_valid_jd_text(raw_jd_text)
    except InvalidJobDescriptionError as exc:
        raise HTTPException(status_code=422, detail=INVALID_JD_USER_MESSAGE) from exc

    clean_jd_text = sanitization.clean_text
    if len(clean_jd_text.strip()) < MIN_JD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Job description is too short after cleanup ({len(clean_jd_text.strip())} characters). "
                f"Please provide at least {MIN_JD_LENGTH} characters of role-specific content."
            ),
        )
    warnings.extend(sanitization.warnings)

    try:
        generation = create_generation(
            user_id=user_id_str,
            raw_jd_text=raw_jd_text,
            target_pages=body.target_pages,
        )
        generation_id = str(generation.id)
        _update_generation_status(user_id_str, generation_id, GENERATION_STATUS_RUNNING)
        record_generation_started(generation_id, user_id_str)
        mark("create_generation", "success")

        try:
            t0 = _time.perf_counter()

            # Try JD cache first (if enabled)
            settings = get_settings()
            parsed_jd = None
            with GenerationTimer("jd_parse", generation_id):
                if settings.ENABLE_JD_CACHE:
                    cached_jd, _ = await get_cached_jd(clean_jd_text)
                    if cached_jd is not None:
                        parsed_jd = cached_jd
                        cache_hit = True
                        logger.info("[%s] jd_cache.hit", generation_id)

                if parsed_jd is None:
                    parsed_jd = sanitize_parsed_jd(
                        await analyze_jd(clean_jd_text),
                        source_text=clean_jd_text,
                        sanitization=sanitization,
                    )
                    # Cache the result for future requests
                    if settings.ENABLE_JD_CACHE:
                        await cache_jd_result(clean_jd_text, parsed_jd)

            assert_parsed_jd_safe(parsed_jd)
            update_generation(
                user_id=user_id_str,
                generation_id=generation_id,
                update_data=ResumeGenerationUpdate(
                    parsed_jd_json=parsed_jd.model_dump(),
                    job_title=parsed_jd.job_title,
                    company=parsed_jd.company,
                ),
            )
            mark("analyze_jd", "success", detail="cached" if cache_hit else None)
            logger.info("[%s] JD analysis took %.2fs (cache=%s)", generation_id, _time.perf_counter() - t0, cache_hit)
        except InvalidJobDescriptionError as exc:
            mark("analyze_jd", "failed", INVALID_JD_USER_MESSAGE)
            update_generation(
                user_id=user_id_str,
                generation_id=generation_id,
                update_data=ResumeGenerationUpdate(status="failed", latex_source=None),
            )
            raise HTTPException(status_code=422, detail=INVALID_JD_USER_MESSAGE) from exc
        except Exception as exc:
            mark("analyze_jd", "failed", str(exc))
            update_generation(
                user_id=user_id_str,
                generation_id=generation_id,
                update_data=ResumeGenerationUpdate(status="failed", latex_source=None),
            )
            raise HTTPException(status_code=502, detail=f"JD analysis failed: {exc}") from exc

        rag_evidence = None
        if get_settings().ENABLE_RAG_EMBEDDINGS:
            try:
                rag_evidence = await retrieve_evidence_for_requirements(
                    user_id=str(user_id_str),
                    parsed_jd=parsed_jd,
                    supabase_service=get_supabase_service(),
                    top_k=3,
                    similarity_threshold=get_settings().SIMILARITY_THRESHOLD,
                )
            except Exception as exc:
                logger.warning("rag.mode=fallback reason=exception error=%s", exc)
                rag_evidence = None

        t_opt = _time.perf_counter()
        optimization = await optimize_resume_for_ats(
            profile=_flag_weak_profile_bullets(body.profile),
            parsed_jd=parsed_jd,
            generation_id=generation_id,
            target_pages=body.target_pages,
            target_ats_score=body.target_ats_score,
            max_repair_attempts=body.max_repair_attempts,
            emphasis=body.emphasis,
            additional_alignment_text=body.additional_alignment_text,
            rag_evidence=rag_evidence,
            ats_optimization_mode=body.ats_optimization_mode,
        )
        logger.info("[%s] ATS optimization loop took %.2fs", generation_id, _time.perf_counter() - t_opt)
        export_validation = validate_resume_for_export(
            optimization.final_recommendation,
            parsed_jd=parsed_jd,
            profile=None if body.ats_optimization_mode == "aggressive" else _flag_weak_profile_bullets(body.profile),
        )
        optimization.final_recommendation = export_validation.recommendation
        _assert_final_resume_safety(
            parsed_jd,
            optimization.final_recommendation,
            optimization.final_latex_source,
        )
        mark(
            "optimize_resume_pdf_text",
            "success" if optimization.final_pdf_text_score else "failed",
            f"{optimization.attempts_used} attempts; score={optimization.final_pdf_text_score.overall_score if optimization.final_pdf_text_score else 'n/a'}",
        )

        if optimization.final_pdf_text_score is None:
            warnings.append("Optimization could not produce an inspectable PDF; returning the best JSON-scored draft.")
        if optimization.pdf_failed and optimization.final_docx_fallback_path:
            warnings.append("Your resume is ready as a Word document. PDF generation had a formatting issue.")

        update_generation(
            user_id=user_id_str,
            generation_id=generation_id,
            update_data=ResumeGenerationUpdate(
                resume_json=optimization.final_recommendation.model_dump(),
                ats_score_json=(
                    optimization.final_pdf_text_score.model_dump()
                    if optimization.final_pdf_text_score
                    else optimization.final_json_score.model_dump() if optimization.final_json_score else None
                ),
                recruiter_review_json=(
                    optimization.recruiter_review.model_dump()
                    if optimization.recruiter_review else None
                ),
                recruiter_impression=(
                    optimization.recruiter_review.overall_impression
                    if optimization.recruiter_review else None
                ),
                alignment_report_json=build_ats_alignment_report(
                    parsed_jd,
                    optimization.final_recommendation,
                    formatting_score=optimization.final_pdf_text_score.format_score if optimization.final_pdf_text_score else None,
                ).model_dump(),
                latex_source=optimization.final_latex_source,
                docx_fallback_path=optimization.final_docx_fallback_path,
                pdf_compile_error=optimization.pdf_compile_error,
                status="completed",
                completed_at=_utc_now(),
            ),
        )
        mark("save_outputs", "success")

        get_supabase_service().log_usage_event(
            user_id=user_id_str,
            event_type="resume_generate_optimized",
            generation_id=generation_id,
            metadata={
                "status": "completed",
                "attempts": optimization.attempts_used,
                "score": optimization.final_pdf_text_score.overall_score if optimization.final_pdf_text_score else None,
                "target_score": body.target_ats_score,
                "ats_optimization_mode": body.ats_optimization_mode,
            },
        )

        pdf = PipelinePdfResult(
            requested=True,
            compile_success=bool(optimization.final_pdf_text_score) and not optimization.pdf_failed,
            compile_warnings=optimization.compile_warnings,
            page_count=optimization.final_page_count,
            target_pages=body.target_pages,
            docx_fallback_path=optimization.final_docx_fallback_path,
            pdf_failed=optimization.pdf_failed,
            user_message=(
                "Your resume is ready as a Word document. PDF generation had a formatting issue."
                if optimization.pdf_failed and optimization.final_docx_fallback_path
                else None
            ),
            compression_applied=any(
                bool(item.repair_actions)
                for item in optimization.diagnostics
            ),
            compression_actions=[
                action
                for item in optimization.diagnostics
                for action in item.repair_actions
                if "Compressed" in action or "compressed" in action
            ],
        )

        all_warnings = _dedupe(warnings + optimization.score_explanation)

        final_ats_score = optimization.final_pdf_text_score or optimization.final_json_score
        if not final_ats_score:
            raise HTTPException(status_code=500, detail="Optimization failed to produce an ATS score.")

        final_alignment_report = build_ats_alignment_report(
            parsed_jd,
            optimization.final_recommendation,
            formatting_score=final_ats_score.format_score,
        )

        total_time = _time.perf_counter() - pipeline_start
        logger.info("[%s] Pipeline total_time=%.2fs score=%s attempts=%d",
                     generation_id, total_time,
                     final_ats_score.overall_score, optimization.attempts_used)
        record_generation_completed(
            generation_id=generation_id,
            user_id=user_id_str,
            final_score=final_ats_score.overall_score,
            original_score=None,
            duration_ms=total_time * 1000,
            repair_passes=optimization.attempts_used,
            jd_cache_hit=cache_hit,
        )

        return PipelineOptimizedGenerateResponse(
            generation_id=generation_id,
            parsed_jd=parsed_jd,
            recommendation=optimization.final_recommendation,
            latex_source=optimization.final_latex_source,
            pdf=pdf,
            optimization=optimization,
            ats_score=final_ats_score,
            alignment_report=final_alignment_report,
            recruiter_review=optimization.recruiter_review,
            steps=steps,
            warnings=all_warnings,
            validation_status=build_validation_status(
                export_validation,
                additional_warnings=all_warnings,
            ),
            retry_count=getattr(
                get_gemini_client(), "last_retry_count", 0
            ),
        )
    except ResumeValidationError as exc:
        _record_failure(generation_id)
        if generation_id:
            record_generation_failed(
                generation_id,
                user_id_str,
                "VALIDATION_ERROR",
                (_time.perf_counter() - pipeline_start) * 1000,
            )
        logger.warning("[%s] Resume export validation blocker fired: %s", generation_id or "no-generation", exc)
        raise HTTPException(status_code=422, detail=_validation_block_detail(exc)) from exc
    except ResumeContaminationError as exc:
        _record_failure(generation_id)
        if generation_id:
            record_generation_failed(
                generation_id,
                user_id_str,
                "CONTAMINATION_ERROR",
                (_time.perf_counter() - pipeline_start) * 1000,
            )
        logger.error("[%s] Optimized resume contamination blocker fired: %s", generation_id or "no-generation", exc)
        raise HTTPException(
            status_code=422,
            detail="Resume generation was blocked because pasted job-description text reached the resume.",
        ) from exc
    except HTTPException as exc:
        if generation_id:
            record_generation_failed(
                generation_id,
                user_id_str,
                _http_error_code(exc),
                (_time.perf_counter() - pipeline_start) * 1000,
            )
        raise
    except Exception as exc:
        logger.exception("[%s] Unexpected optimized pipeline failure", generation_id or "no-generation")
        _record_failure(generation_id)
        if generation_id:
            record_generation_failed(
                generation_id,
                user_id_str,
                "PIPELINE_ERROR",
                (_time.perf_counter() - pipeline_start) * 1000,
            )
        if generation_id:
            try:
                update_generation(
                    user_id=current_user.user_id,
                    generation_id=generation_id,
                    update_data=ResumeGenerationUpdate(status="failed"),
                )
            except Exception:
                logger.warning("[%s] Could not mark optimized generation failed", generation_id)
        raise HTTPException(status_code=500, detail="Optimized resume generation failed. Please retry.") from exc


# ── SSE Streaming Endpoints ────────────────────────────────────────────────


async def _quick_score_profile(
    profile: MasterProfile,
    parsed_jd: ParsedJD,
) -> float | None:
    """Quickly compute a profile-level ATS score from raw profile text."""
    try:
        profile_text_parts = []
        for exp in profile.work_experience:
            profile_text_parts.append(" ".join([exp.title, exp.company, *exp.bullets]))
        for proj in profile.projects:
            profile_text_parts.append(" ".join([proj.name, *proj.bullets]))
        for edu in profile.education:
            profile_text_parts.append(" ".join([edu.degree, edu.institution, *edu.relevant_coursework]))
        raw_text = " ".join(profile_text_parts)[:3000]
        ats_plan = build_ats_keyword_plan(
            parsed_jd=parsed_jd,
            profile=profile,
            target_pages=1,
        )
        score = compute_ats_score_from_text(
            raw_text,
            parsed_jd,
            ats_plan=ats_plan,
            target_title=parsed_jd.job_title,
        )
        return score.overall_score if score else None
    except Exception as exc:
        logger.debug("Quick profile scoring skipped: %s", exc)
        return None


@router.post("/generate/start")
async def start_generation(
    request: Request,
    body: PipelineOptimizedGenerateRequest,
    current_user=Depends(get_current_user),
):
    """
    Start resume generation. Returns generation_id immediately.
    Connect to GET /pipeline/generate/{generation_id}/stream for SSE progress events.
    """
    # Route layer stays HTTP-only; lifecycle startup is handled by the use case.
    return start_generation_use_case(
        body=body,
        user_id=current_user.user_id,
        request_id=get_request_id(request),
        runner_factory=lambda kwargs: _run_generation_pipeline(**kwargs),
    )


    # Launch generation as background task — does NOT block the response


@router.get("/generate/{generation_id}/stream")
async def stream_generation_progress(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """Stream generation progress as Server-Sent Events."""
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Generation not found") from exc

    # Use-case layer owns pre-stream terminal/status handling.
    return EventSourceResponse(generation_stream_events(gen, generation_id))

@router.get("/generate/{generation_id}/result")
async def get_generation_result(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """
    Get the full generation result after SSE streaming completes.
    The background task saves results to the DB; this endpoint retrieves them.
    """
    # Route delegates lifecycle status/result decisions to the use case.
    return get_generation_result_for_user(current_user.user_id, generation_id)

async def _run_generation_pipeline(
    *,
    raw_jd_text: str,
    clean_jd_text: str,
    sanitization: Any,
    profile: MasterProfile,
    user_id: str,
    generation_id: str,
    target_pages: int,
    target_ats_score: float,
    max_repair_attempts: int,
    emphasis: str | None,
    additional_alignment_text: str | None,
    ats_optimization_mode: str = "aggressive",
    request_id: str | None = None,
) -> None:
    """Background task: runs the full generation pipeline with SSE progress events."""
    set_generation_user(generation_id, user_id)
    pipeline_start = _time.perf_counter()
    original_score_val: float | None = None
    cache_hit = False
    record_generation_started(generation_id, user_id)
    logger.info("[%s] background_pipeline.started pages=%s target_score=%s ats_mode=%s",
                generation_id, target_pages, target_ats_score, ats_optimization_mode)

    try:
        _update_generation_status(user_id, generation_id, GENERATION_STATUS_RUNNING)
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="started",
            status="started",
        )
        await emit_progress(generation_id, "started", {
            "generation_id": generation_id,
        })

        # ── Step 1: Parse JD ────────────────────────────────────────────
        jd_parse_start = _time.perf_counter()
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="jd_parsing",
            status="started",
        )
        await emit_progress(generation_id, "jd_parsing", {
            "step": 1, "total": 8, "label": "Parsing job description",
        })

        settings = get_settings()
        parsed_jd = None
        t0 = _time.perf_counter()
        with GenerationTimer("jd_parse", generation_id):
            if settings.ENABLE_JD_CACHE:
                cached_jd, _ = await get_cached_jd(clean_jd_text)
                if cached_jd is not None:
                    parsed_jd = cached_jd
                    cache_hit = True

            if parsed_jd is None:
                parsed_jd = sanitize_parsed_jd(
                    await analyze_jd(clean_jd_text),
                    source_text=clean_jd_text,
                    sanitization=sanitization,
                )
                if settings.ENABLE_JD_CACHE:
                    await cache_jd_result(clean_jd_text, parsed_jd)

        assert_parsed_jd_safe(parsed_jd)

        update_generation(
            user_id=user_id,
            generation_id=generation_id,
            update_data=ResumeGenerationUpdate(
                parsed_jd_json=parsed_jd.model_dump(),
                job_title=parsed_jd.job_title,
                company=parsed_jd.company,
            ),
        )

        await emit_progress(generation_id, "jd_parsed", {
            "step": 1, "total": 8, "label": "Job description analysed",
            "job_title": parsed_jd.job_title or "",
            "keywords_found": len(parsed_jd.required_skills) if parsed_jd.required_skills else 0,
        })
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="jd_parsed",
            status="success",
            duration_ms=(_time.perf_counter() - jd_parse_start) * 1000,
            cache_hit=cache_hit,
        )
        logger.info("[%s] background_pipeline.jd_parsed cache=%s time=%.2fs",
                    generation_id, cache_hit, _time.perf_counter() - t0)

        # ── Step 2: Score original profile ───────────────────────────────
        score_start = _time.perf_counter()
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="scoring_original",
            status="started",
        )
        await emit_progress(generation_id, "scoring_original", {
            "step": 2, "total": 8, "label": "Scoring your current resume",
        })
        original_score_val = await _quick_score_profile(profile, parsed_jd)
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="scoring_original",
            status="success",
            duration_ms=(_time.perf_counter() - score_start) * 1000,
        )
        if original_score_val is not None:
            await emit_progress(generation_id, "original_scored", {
                "step": 2, "total": 8,
                "label": "Your current resume scored",
                "original_score": original_score_val,
            })

        # ── Step 3: RAG evidence (optional) ──────────────────────────────
        evidence_start = _time.perf_counter()
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="building_evidence",
            status="started",
        )
        await emit_progress(generation_id, "building_evidence", {
            "step": 3, "total": 8, "label": "Matching your experience to requirements",
        })
        rag_evidence = None
        if settings.ENABLE_RAG_EMBEDDINGS:
            try:
                rag_evidence = await retrieve_evidence_for_requirements(
                    user_id=str(user_id),
                    parsed_jd=parsed_jd,
                    supabase_service=get_supabase_service(),
                    top_k=3,
                    similarity_threshold=settings.SIMILARITY_THRESHOLD,
                )
            except Exception as exc:
                logger.warning("[%s] rag.mode=fallback error=%s", generation_id, exc)
                rag_evidence = None

        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="building_evidence",
            status="success",
            duration_ms=(_time.perf_counter() - evidence_start) * 1000,
            enabled=settings.ENABLE_RAG_EMBEDDINGS,
        )

        # ── Step 4: Compose & Optimize ───────────────────────────────────
        compose_start = _time.perf_counter()
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="composing",
            status="started",
        )
        await emit_progress(generation_id, "composing", {
            "step": 4, "total": 8, "label": "Writing your resume",
        })
        t_opt = _time.perf_counter()

        async def _repair_pass_callback(attempt: int, score: float) -> None:
            _log_generation_step(
                request_id=request_id,
                generation_id=generation_id,
                user_id=user_id,
                step="repair_pass",
                status="success",
                attempt=attempt + 1,
                score=score,
            )
            await emit_progress(generation_id, "repair_pass", {
                "step": 5, "total": 8,
                "label": f"Optimising — pass {attempt + 1} of {max_repair_attempts}",
                "attempt": attempt + 1,
                "score": score,
            })

        optimization = await optimize_resume_for_ats(
            profile=_flag_weak_profile_bullets(profile),
            parsed_jd=parsed_jd,
            generation_id=generation_id,
            target_pages=target_pages,
            target_ats_score=target_ats_score,
            max_repair_attempts=max_repair_attempts,
            emphasis=emphasis,
            additional_alignment_text=additional_alignment_text,
            rag_evidence=rag_evidence,
            ats_optimization_mode=ats_optimization_mode,
            progress_callback=_repair_pass_callback,
        )
        logger.info("[%s] background_pipeline.optimization time=%.2fs attempts=%d",
                    generation_id, _time.perf_counter() - t_opt, optimization.attempts_used)
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="composing",
            status="success",
            duration_ms=(_time.perf_counter() - compose_start) * 1000,
            attempts=optimization.attempts_used,
        )

        # ── Step 6: Validate export ──────────────────────────────────────
        export_validation = validate_resume_for_export(
            optimization.final_recommendation,
            parsed_jd=parsed_jd,
            profile=None if ats_optimization_mode == "aggressive" else _flag_weak_profile_bullets(profile),
        )
        optimization.final_recommendation = export_validation.recommendation
        _assert_final_resume_safety(
            parsed_jd,
            optimization.final_recommendation,
            optimization.final_latex_source,
        )

        # ── Step 7: PDF compile ──────────────────────────────────────────
        pdf_start = _time.perf_counter()
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="pdf_compile",
            status="started",
        )
        await emit_progress(generation_id, "pdf_compile", {
            "step": 7, "total": 8, "label": "Building your PDF",
        })
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="pdf_compile",
            status="success",
            duration_ms=(_time.perf_counter() - pdf_start) * 1000,
        )

        final_ats_score = optimization.final_pdf_text_score or optimization.final_json_score

        # ── Step 8: Save & Complete ──────────────────────────────────────
        update_generation(
            user_id=user_id,
            generation_id=generation_id,
            update_data=ResumeGenerationUpdate(
                resume_json=optimization.final_recommendation.model_dump(),
                ats_score_json=(
                    optimization.final_pdf_text_score.model_dump()
                    if optimization.final_pdf_text_score
                    else optimization.final_json_score.model_dump() if optimization.final_json_score else None
                ),
                recruiter_review_json=(
                    optimization.recruiter_review.model_dump()
                    if optimization.recruiter_review else None
                ),
                recruiter_impression=(
                    optimization.recruiter_review.overall_impression
                    if optimization.recruiter_review else None
                ),
                latex_source=optimization.final_latex_source,
                docx_fallback_path=optimization.final_docx_fallback_path,
                pdf_compile_error=optimization.pdf_compile_error,
                status=GENERATION_STATUS_COMPLETED,
                updated_at=_utc_now(),
                completed_at=_utc_now(),
            ),
        )

        get_supabase_service().log_usage_event(
            user_id=user_id,
            event_type="resume_generate_streaming",
            generation_id=generation_id,
            metadata={
                "status": "completed",
                "attempts": optimization.attempts_used,
                "score": final_ats_score.overall_score if final_ats_score else None,
                "target_score": target_ats_score,
            },
        )

        final_score_val = final_ats_score.overall_score if final_ats_score else 0.0
        await send_complete(
            generation_id,
            final_score=final_score_val,
            original_score=original_score_val,
        )
        _log_generation_step(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            step="complete",
            status="success",
            duration_ms=(_time.perf_counter() - pipeline_start) * 1000,
            final_score=final_score_val,
        )
        logger.info("[%s] background_pipeline.completed score=%.1f attempts=%d",
                    generation_id, final_score_val, optimization.attempts_used)
        record_generation_completed(
            generation_id=generation_id,
            user_id=user_id,
            final_score=final_score_val,
            original_score=original_score_val,
            duration_ms=(_time.perf_counter() - pipeline_start) * 1000,
            repair_passes=optimization.attempts_used,
            jd_cache_hit=cache_hit,
        )

    except InvalidJobDescriptionError:
        logger.warning("[%s] background_pipeline.error JD_INVALID", generation_id)
        await _fail_generation(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            duration_ms=(_time.perf_counter() - pipeline_start) * 1000,
            error_code="JD_INVALID",
        )
    except GeminiClientError:
        logger.warning("[%s] background_pipeline.error AI_TIMEOUT", generation_id)
        await _fail_generation(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            duration_ms=(_time.perf_counter() - pipeline_start) * 1000,
            error_code="AI_TIMEOUT",
        )
    except Exception:
        logger.exception("[%s] background_pipeline.unexpected_error", generation_id)
        await _fail_generation(
            request_id=request_id,
            generation_id=generation_id,
            user_id=user_id,
            duration_ms=(_time.perf_counter() - pipeline_start) * 1000,
            error_code="PIPELINE_ERROR",
        )
    finally:
        cleanup_generation_channel(generation_id)


@router.get("/generate/{generation_id}/progress")
async def get_generation_progress(
    generation_id: str,
    current_user=Depends(get_current_user),
):
    """Poll endpoint for generation progress (legacy)."""
    try:
        gen = assert_generation_owner(current_user.user_id, generation_id)
    except GenerationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Generation not found") from exc
    return {
        **_status_payload(gen, channel_available=has_progress_channel(generation_id)),
        "step": _current_step_for_status(gen.status),
        "label": "Use SSE stream endpoint for live progress when available.",
        "pct": _progress_for_status(gen.status),
    }


def _record_failure(generation_id: str | None) -> None:
    if generation_id:
        logger.warning("Pipeline failure recorded for generation %s", generation_id)


def _http_error_code(exc: HTTPException) -> str:
    if exc.status_code == 422:
        return "JD_INVALID"
    if exc.status_code == 502:
        return "AI_TIMEOUT"
    if exc.status_code == 500:
        return "PIPELINE_ERROR"
    return f"HTTP_{exc.status_code}"


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


def _validation_block_detail(exc: ResumeValidationError) -> list[str]:
    detail = ["Resume export blocked. Fix the highlighted resume content and try again."]
    detail.extend(
        f"{issue.path}: {issue.message}" if issue.path else issue.message
        for issue in exc.issues[:8]
    )
    return detail


def _assert_final_resume_safety(parsed_jd, recommendation, latex_source: str | None = None) -> None:
    assert_parsed_jd_safe(parsed_jd)
    assert_resume_recommendation_safe(recommendation)
    assert_render_text_safe(
        recommendation_to_plain_text(recommendation),
        artifact="recommendation_plain_text",
    )
    if latex_source is not None:
        assert_render_text_safe(latex_source, artifact="latex_source")


def _enforce_always_generate_contract(
    recommendation,
    parsed_jd,
    clean_profile,
    ats_plan,
    warnings: list[str],
    target_pages: int = 1,
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
        rec.skills = build_skill_taxonomy(rec.skills, parsed_jd, clean_profile, target_pages=target_pages)
        total_skills = sum(len(g.skills) for g in rec.skills)
        if total_skills < 5:
            warnings.append(
                "Pipeline gate: Profile evidence did not support five technical skills; "
                "unsupported JD tools were not promoted to hands-on skills."
            )

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
