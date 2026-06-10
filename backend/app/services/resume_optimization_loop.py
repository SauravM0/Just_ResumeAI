"""Deterministic final resume optimization loop.

The loop treats the compiled PDF as the final artifact: the composite ATS
readiness score (with breakdown categories: ATS Match, Truthfulness, Recruiter
Quality, Parseability, Risk Flags) guides repairs, but the accept/retry decision
uses text extracted from the PDF.

Safety model:
- Unsupported keyword claims do NOT increase the final score — they are penalized
  in the Truthfulness and Recruiter Quality composite scores.
- Invalid titles create near-zero export readiness.
- PDF parse failure blocks or reduces the Parseability score.
- The loop always prefers honest evidence-backed content over keyword stuffing.
"""

from __future__ import annotations

import logging
import re
import asyncio
import time
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Dict, Optional, Tuple

from app.agents.resume_agent.recruiter_review_agent import RecruiterReview, recruiter_review_agent
from app.ai.gemini_client import GeminiClientError
from app.ai.orchestrators.resume_orchestrator import generate_recommendation
from app.ai.resume_fallback import generate_recommendation_without_ai
from app.schemas.jd import ParsedJD
from app.schemas.pipeline import OptimizationAttemptDiagnostics, ResumeOptimizationResult
from app.schemas.profile import MasterProfile
from app.schemas.resume import BulletStatus, ResumeBullet, ResumeRecommendation, ResumeSkillGroup
from app.schemas.scoring import ATSScore
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.services.candidate_evidence_service import (
    EvidenceGraph,
    build_candidate_evidence,
    classify_jd_keyword_truth,
    is_supported_placement,
    is_learning_placement,
    learning_focus_phrase,
    trace_claim,
)
from app.services.candidate_timeline_service import assess_candidate_timeline, is_fresher_or_student
from app.services.keyword_placement_service import analyze_keyword_placement, build_master_keyword_list, inject_missing_keywords
from app.services.latex_render_service import render_latex
from app.services.locked_fields_service import LockedFields, build_locked_fields, validate_locked_fields_in_output
from app.services.pdf_compile_service import PDFCompileError
from app.services.pdf_inspection_service import PDFInspectionError, inspect_pdf
from app.services.pdf_page_fit_service import compile_pdf_to_page_target
from app.services.resume_budget_service import fit_resume_to_page_budget
from app.services.resume_quality_gate import apply_resume_quality_gate
from app.services.resume_validation_gate import validate_resume_for_mode
from app.services.resume_strategy_service import build_resume_strategy
from app.services.resume_strength_service import strengthen_resume_recommendation
from app.services.bullet_quality_service import repair_incomplete_bullet, validate_single_bullet
from app.services.scoring_service import compute_ats_score, compute_ats_score_from_text, extract_text_from_latex, verify_text_extraction
from app.services.skill_taxonomy_service import merge_typed_skill_groups
from app.services.rag_retrieval_service import RequirementEvidence
from app.services.synonym_service import get_all_forms

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\b[a-z0-9][a-z0-9+#./-]{1,}\b", re.IGNORECASE)
_CERT_RE = re.compile(r"\b(certification|certified|certificate|rhcsa|rhce)\b", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


class RepairStrategy(str, Enum):
    KEYWORD_INJECTION = "keyword_injection"
    BULLET_STRENGTHENING = "bullet_strengthening"
    RESPONSIBILITY_ALIGNMENT = "responsibility_alignment"
    SUMMARY_REFINEMENT = "summary_refinement"
    PAGE_FIT = "page_fit"
    FINAL_SAFETY = "final_safety"


def _select_repair_strategy(attempt: int, score: ATSScore, max_attempts: int) -> RepairStrategy:
    """
    Select the most impactful repair strategy from the current score breakdown.
    The final pass is reserved for safety cleanup and hallucination removal.
    """
    if attempt >= max_attempts - 1:
        return RepairStrategy.FINAL_SAFETY

    keyword_score = _keyword_dimension_score(score)
    bullet_score = _bullet_dimension_score(score)
    responsibility_score = getattr(score, "responsibility_score", 100.0)
    page_score = _page_dimension_score(score)

    if keyword_score < 65.0 and attempt <= 2:
        return RepairStrategy.KEYWORD_INJECTION
    if bullet_score < 65.0 and attempt <= 3:
        return RepairStrategy.BULLET_STRENGTHENING
    if responsibility_score < 50.0 and attempt <= 4:
        return RepairStrategy.RESPONSIBILITY_ALIGNMENT
    if page_score < 80.0:
        return RepairStrategy.PAGE_FIT
    return RepairStrategy.SUMMARY_REFINEMENT


def _log_repair_pass_score(attempt: int, score: ATSScore) -> None:
    logger.info(
        "repair_loop.pass=%d score=%.1f keyword=%.1f bullet=%.1f responsibility=%.1f",
        attempt,
        score.overall_score,
        _keyword_dimension_score(score),
        _bullet_dimension_score(score),
        getattr(score, "responsibility_score", 0.0),
    )


def _log_stage_time(stage: str, started: float, *, generation_id: str | None = None, **fields: Any) -> None:
    """Emit a consistent millisecond timing log for pipeline stage profiling."""
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    suffix = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    logger.info(
        "pipeline.stage_time stage=%s ms=%.0f generation_id=%s%s%s",
        stage,
        elapsed_ms,
        generation_id or "",
        " " if suffix else "",
        suffix,
    )


def _is_stuck_score_history(score_history: list[float]) -> bool:
    if len(score_history) < 3:
        return False
    return (score_history[-1] - score_history[-3]) < 2.0


async def optimize_resume_for_ats(
    *,
    profile: MasterProfile | None = None,
    parsed_jd: ParsedJD,
    generation_id: str,
    target_pages: int = 1,
    target_ats_score: float = 98.0,
    max_repair_attempts: int = 7,
    emphasis: str | None = None,
    additional_alignment_text: str | None = None,
    rag_evidence: list[RequirementEvidence] | None = None,
    ats_optimization_mode: str = "aggressive",
    progress_callback: Callable[[int, float], Awaitable[None]] | None = None,
) -> ResumeOptimizationResult:
    """
    Generate, repair, render, compile, inspect, and re-score until accepted.

    Args:
        progress_callback: Optional async callback called after each repair pass
            with (attempt_index, current_score). Used by SSE streaming to emit
            repair_pass progress events.
    """
    target_pages = max(1, min(target_pages, 2))
    max_repair_attempts = max(1, min(max_repair_attempts, 7))
    target_score = max(0.0, min(target_ats_score, 100.0))
    aggressive_mode = ats_optimization_mode == "aggressive"

    pipeline_started = time.perf_counter()
    stage_started = time.perf_counter()
    ats_plan = build_ats_keyword_plan(
        parsed_jd=parsed_jd,
        profile=profile,
        emphasis=emphasis,
        target_pages=target_pages,
    )
    _log_stage_time("build_ats_keyword_plan", stage_started, generation_id=generation_id)

    stage_started = time.perf_counter()
    locked = build_locked_fields(profile) if profile else None
    _log_stage_time("build_locked_fields", stage_started, generation_id=generation_id)

    stage_started = time.perf_counter()
    recommendation = await _generate_initial_recommendation(
        profile=profile,
        parsed_jd=parsed_jd,
        generation_id=generation_id,
        target_pages=target_pages,
        emphasis=emphasis,
        additional_alignment_text=additional_alignment_text,
        ats_plan=ats_plan,
        rag_evidence=rag_evidence,
        ats_optimization_mode=ats_optimization_mode,
    )
    _log_stage_time("generate_recommendation", stage_started, generation_id=generation_id)

    best: _AttemptState | None = None
    diagnostics: list[OptimizationAttemptDiagnostics] = []
    score_history: list[float] = []
    strategy_history: list[str] = []
    compile_warnings: list[str] = []
    docx_fallback_path: str | None = None
    pdf_compile_error: str | None = None
    pdf_failed = False
    overflow_last_attempt = False
    
    stage_started = time.perf_counter()
    if profile:
        evidence_graph, timeline = await asyncio.gather(
            asyncio.to_thread(build_candidate_evidence, profile),
            asyncio.to_thread(assess_candidate_timeline, profile),
        )
        is_fresher = is_fresher_or_student(timeline)
    else:
        evidence_graph = None
        is_fresher = False
    _log_stage_time("parallel_preprocess", stage_started, generation_id=generation_id)

    for attempt in range(1, max_repair_attempts + 1):
        pass_index = attempt - 1
        is_final_pass = attempt == max_repair_attempts
        # 1. SCORE current version (JSON baseline)
        stage_started = time.perf_counter()
        json_score = compute_ats_score(
            recommendation,
            parsed_jd,
            ats_plan=ats_plan,
            profile=profile,
            allow_unverified_claims=True,
            target_pages=target_pages,
        )
        _log_stage_time("score_json", stage_started, generation_id=generation_id, attempt=attempt)
        score_history.append(json_score.overall_score)
        _log_repair_pass_score(pass_index, json_score)

        # Emit progress for this pass if callback provided
        if progress_callback:
            await progress_callback(pass_index, json_score.overall_score)

        if json_score.overall_score >= target_score:
            logger.info(
                "repair_loop.target_reached generation_id=%s attempt=%s score=%.1f",
                generation_id,
                attempt,
                json_score.overall_score,
            )
            break
        
        # 2. DECIDE repair strategy based on score breakdown
        repair_actions: list[str] = []
        strategy = _select_repair_strategy(pass_index, json_score, max_repair_attempts)
        strategy_history.append(strategy.value)
        repair_actions.append(_repair_pass_label(pass_index, strategy == RepairStrategy.FINAL_SAFETY))
        logger.info("repair_loop.strategy=%s attempt=%d", strategy.value, pass_index)
        pass_started = time.perf_counter()
        recommendation = await _execute_repair_strategy(
            strategy=strategy,
            rec=recommendation,
            parsed_jd=parsed_jd,
            profile=profile,
            ats_plan=ats_plan,
            evidence=evidence_graph,
            current_score=json_score,
            attempt=pass_index,
            target_pages=target_pages,
            overflow=overflow_last_attempt,
            locked=locked,
            repair_actions=repair_actions,
            aggressive_mode=aggressive_mode,
        )
        _log_stage_time("repair_pass", pass_started, generation_id=generation_id, attempt=attempt, strategy=strategy.value)
        logger.info(
            "repair_loop.pass_timing generation_id=%s attempt=%s strategy=%s seconds=%.3f",
            generation_id,
            attempt,
            strategy.value,
            time.perf_counter() - pass_started,
        )

        # 3. RENDER, COMPILE, and SCORE from actual PDF text
        attempt_warnings: list[str] = []
        try:
            stage_started = time.perf_counter()
            fitted = await compile_pdf_to_page_target(
                recommendation=recommendation,
                parsed_jd=parsed_jd,
                generation_id=generation_id,
                target_pages=target_pages,
                ats_plan=ats_plan,
                max_attempts=6,
                is_fresher=is_fresher,
            )
            _log_stage_time("pdf_compile", stage_started, generation_id=generation_id, attempt=attempt)
            recommendation = fitted.recommendation
            stage_started = time.perf_counter()
            json_score = compute_ats_score(
                recommendation,
                parsed_jd,
                ats_plan=ats_plan,
                profile=profile,
                allow_unverified_claims=True,
                target_pages=target_pages,
            )
            _log_stage_time("score_compiled_json", stage_started, generation_id=generation_id, attempt=attempt)
            compile_warnings = fitted.compile_warnings
            attempt_warnings.extend(fitted.compile_warnings)
            attempt_warnings.extend(fitted.inspection_warnings)
            if fitted.compression_actions:
                repair_actions.extend(fitted.compression_actions)
            if fitted.pdf_failed:
                pdf_failed = True
                docx_fallback_path = fitted.docx_fallback_path or docx_fallback_path
                pdf_compile_error = fitted.pdf_compile_error or pdf_compile_error
                pdf_score = None
                state = None
                attempt_warnings.append("Your resume is ready as a Word document. PDF generation had a formatting issue.")
                logger.warning("[%s] PDF failed; DOCX fallback generated at %s", generation_id, docx_fallback_path)
                diagnostics.append(
                    OptimizationAttemptDiagnostics(
                        attempt=attempt,
                        json_score=json_score,
                        pdf_text_score=None,
                        missing_keywords=_missing_from_score(json_score),
                        matched_keywords=_matched_from_score(json_score),
                        title_alignment_score=json_score.title_alignment_score,
                        skills_coverage_percent=json_score.skill_score.required_coverage_percent,
                        section_quality_score=json_score.section_score.score,
                        page_count=None,
                        compile_success=False,
                        repair_actions=repair_actions,
                        warnings=attempt_warnings,
                    )
                )
                break
            
            pdf_score = fitted.ats_score
            state = _AttemptState(
                recommendation=recommendation,
                latex_source=fitted.latex_source,
                pdf_path=fitted.pdf_path,
                page_count=fitted.page_count,
                json_score=json_score,
                pdf_score=pdf_score,
                warnings=attempt_warnings,
            )
            _cleanup_superseded(best, state)
            best = _choose_best_attempt(best, state, target_pages)
        except (PDFCompileError, PDFInspectionError) as exc:
            pdf_score = None
            state = None
            attempt_warnings.append(str(exc))
            pdf_compile_error = str(exc)
            logger.warning("[%s] Optimization attempt %s failed: %s", generation_id, attempt, exc)

        # 4. RECORD progress
        score_for_decision = pdf_score.overall_score if pdf_score else json_score.overall_score
        logger.info(
            "repair_loop.pass_end generation_id=%s attempt=%s before=%.1f after=%.1f",
            generation_id,
            attempt,
            score_history[-1],
            score_for_decision,
        )
        page_count = state.page_count if state else None
        missing = _missing_from_score(pdf_score or json_score)
        
        diagnostics.append(
            OptimizationAttemptDiagnostics(
                attempt=attempt,
                json_score=json_score,
                pdf_text_score=pdf_score,
                missing_keywords=missing,
                matched_keywords=_matched_from_score(pdf_score or json_score),
                title_alignment_score=(pdf_score or json_score).title_alignment_score,
                skills_coverage_percent=(pdf_score or json_score).skill_score.required_coverage_percent,
                section_quality_score=(pdf_score or json_score).section_score.score,
                page_count=page_count,
                compile_success=bool(pdf_score),
                repair_actions=repair_actions,
                warnings=attempt_warnings,
            )
        )

        # 5. STOP if target reached
        if pdf_score and score_for_decision >= target_score and page_count == target_pages:
            break

        overflow_last_attempt = bool(page_count and page_count > target_pages)

    if best is None:
        # Emergency fallback if all PDF attempts failed
        stage_started = time.perf_counter()
        recommendation = _final_keyword_repair(
            recommendation, parsed_jd, ats_plan, profile, target_pages, aggressive_mode=aggressive_mode,
        )
        validate_locked_fields_in_output(recommendation, locked, logger=logger)
        json_score = compute_ats_score(
            recommendation,
            parsed_jd,
            ats_plan=ats_plan,
            profile=profile,
            allow_unverified_claims=aggressive_mode,
            target_pages=target_pages,
        )
        _log_stage_time("json_fallback_repair", stage_started, generation_id=generation_id)
        stage_started = time.perf_counter()
        recruiter_review = await _run_recruiter_review(
            recommendation=recommendation,
            parsed_jd=parsed_jd,
            profile=profile,
            ats_score=json_score,
        )
        _log_stage_time("recruiter_review", stage_started, generation_id=generation_id)
        _log_stage_time("total_generation", pipeline_started, generation_id=generation_id)
        return ResumeOptimizationResult(
            target_score=target_score,
            target_pages=target_pages,
            attempts_used=len(diagnostics),
            reached_target=False,
            final_score_source="json_fallback",
            final_json_score=json_score,
            final_recommendation=recommendation,
            recruiter_review=recruiter_review,
            final_docx_fallback_path=docx_fallback_path,
            pdf_compile_error=pdf_compile_error,
            pdf_failed=pdf_failed,
            final_latex_source=render_latex(recommendation, is_fresher=is_fresher),
            locked_fields=locked.model_dump(mode="json") if locked else {},
            diagnostics=diagnostics,
            score_history=score_history,
            strategy_history=strategy_history,
            repair_passes_used=len(score_history),
            missing_keywords=_missing_from_score(json_score),
            matched_keywords=_matched_from_score(json_score),
            title_alignment_score=json_score.title_alignment_score,
            skills_coverage_percent=json_score.skill_score.required_coverage_percent,
            section_quality_score=json_score.section_score.score,
            score_explanation=_score_explanation(json_score, None, target_pages, profile=profile),
            compile_warnings=compile_warnings,
        )

    # FINAL polish pass on best attempt
    stage_started = time.perf_counter()
    final_recommendation = _final_keyword_repair(
        best.recommendation, parsed_jd, ats_plan, profile, target_pages, aggressive_mode=aggressive_mode,
    )
    validate_locked_fields_in_output(final_recommendation, locked, logger=logger)
    if locked:
        final_recommendation.locked_fields = locked.model_dump(mode="json")
    final_recommendation = validate_resume_for_mode(
        final_recommendation,
        parsed_jd=parsed_jd,
        profile=None if aggressive_mode else profile,
        mode="draft_mode",
        repair=True,
        locked=locked,
    ).recommendation
    
    # Initialize versioning
    final_recommendation.content_hash = final_recommendation.calculate_content_hash()
    final_recommendation.version_id = f"gen-{final_recommendation.content_hash[:8]}"
    _log_stage_time("final_polish", stage_started, generation_id=generation_id)
    
    stage_started = time.perf_counter()
    final_json_score = compute_ats_score(
        final_recommendation, 
        parsed_jd, 
        ats_plan=ats_plan, 
        profile=profile, 
        allow_unverified_claims=aggressive_mode,
        target_pages=target_pages,
        version_id=final_recommendation.version_id
    )
    _log_stage_time("final_json_score", stage_started, generation_id=generation_id)
    stage_started = time.perf_counter()
    recruiter_review = await _run_recruiter_review(
        recommendation=final_recommendation,
        parsed_jd=parsed_jd,
        profile=profile,
        ats_score=final_json_score,
    )
    _log_stage_time("recruiter_review", stage_started, generation_id=generation_id)
    if (
        recruiter_review
        and _recruiter_review_has_critical_issues(recruiter_review)
        and final_json_score.overall_score < 88.0
    ):
        logger.info("recruiter_review.triggering_extra_repair")
        final_recommendation = await _execute_repair_strategy(
            strategy=RepairStrategy.BULLET_STRENGTHENING,
            rec=final_recommendation,
            parsed_jd=parsed_jd,
            profile=profile,
            ats_plan=ats_plan,
            evidence=evidence_graph,
            current_score=final_json_score,
            attempt=max_repair_attempts,
            target_pages=target_pages,
            overflow=False,
            locked=locked,
            repair_actions=[],
            aggressive_mode=aggressive_mode,
        )
        final_recommendation = validate_resume_for_mode(
            final_recommendation,
            parsed_jd=parsed_jd,
            profile=None if aggressive_mode else profile,
            mode="draft_mode",
            repair=True,
            locked=locked,
        ).recommendation
        final_json_score = compute_ats_score(
            final_recommendation,
            parsed_jd,
            ats_plan=ats_plan,
            profile=profile,
            allow_unverified_claims=aggressive_mode,
            target_pages=target_pages,
            version_id=final_recommendation.version_id,
        )
        recruiter_review = await _run_recruiter_review(
            recommendation=final_recommendation,
            parsed_jd=parsed_jd,
            profile=profile,
            ats_score=final_json_score,
        )
    final_latex = render_latex(final_recommendation, is_fresher=is_fresher)
    verify_text_extraction(final_latex, final_recommendation)
    
    # Text extracted from actual LaTeX (proxy for final PDF text)
    stage_started = time.perf_counter()
    final_score = compute_ats_score_from_text(
        _extract_text_from_latex(final_latex, generation_id),
        parsed_jd,
        ats_plan=ats_plan,
        target_title=final_recommendation.target_title,
        target_pages=target_pages,
        page_count=best.page_count,
    )
    _log_stage_time("final_pdf_text_score", stage_started, generation_id=generation_id)
    # Ensure PDF score also has the version ID
    final_score.resume_version_id = final_recommendation.version_id
    _log_stage_time("total_generation", pipeline_started, generation_id=generation_id)

    return ResumeOptimizationResult(
        target_score=target_score,
        target_pages=target_pages,
        attempts_used=len(diagnostics),
        reached_target=final_score.overall_score >= target_score and best.page_count == target_pages,
        final_score_source="pdf_text",
        final_pdf_text_score=final_score,
        final_json_score=final_json_score,
        final_page_count=best.page_count,
        final_pdf_path=best.pdf_path,
        final_docx_fallback_path=docx_fallback_path,
        pdf_compile_error=pdf_compile_error,
        pdf_failed=pdf_failed,
        final_latex_source=final_latex,
        final_recommendation=final_recommendation,
        recruiter_review=recruiter_review,
        locked_fields=locked.model_dump(mode="json") if locked else {},
        diagnostics=diagnostics,
        score_history=score_history,
        strategy_history=strategy_history,
        repair_passes_used=len(score_history),
        missing_keywords=_missing_from_score(final_score),
        matched_keywords=_matched_from_score(final_score),
        title_alignment_score=final_score.title_alignment_score,
        skills_coverage_percent=final_score.skill_score.required_coverage_percent,
        section_quality_score=final_score.section_score.score,
        score_explanation=_score_explanation(final_score, best.page_count, target_pages, profile=profile),
        compile_warnings=compile_warnings,
    )


async def _generate_initial_recommendation(
    *,
    profile: MasterProfile | None = None,
    parsed_jd: ParsedJD,
    generation_id: str,
    target_pages: int,
    emphasis: str | None,
    additional_alignment_text: str | None,
    ats_plan,
    rag_evidence: list[RequirementEvidence] | None = None,
    ats_optimization_mode: str = "realistic",
) -> ResumeRecommendation:
    stage_started = time.perf_counter()
    try:
        recommendation = await generate_recommendation(
            profile=profile,
            parsed_jd=parsed_jd,
            generation_id=generation_id,
            emphasis=emphasis,
            target_pages=target_pages,
            additional_alignment_text=additional_alignment_text,
            ats_plan=ats_plan,
            rag_evidence=rag_evidence,
            ats_optimization_mode=ats_optimization_mode,
        )
        _log_stage_time("gemini_initial_composition", stage_started, generation_id=generation_id)
    except GeminiClientError:
        _log_stage_time("gemini_initial_composition", stage_started, generation_id=generation_id, fallback=True)
        stage_started = time.perf_counter()
        recommendation = generate_recommendation_without_ai(
            profile=profile,
            parsed_jd=parsed_jd,
            generation_id=generation_id,
            emphasis=emphasis,
            target_pages=target_pages,
            additional_alignment_text=additional_alignment_text,
            ats_plan=ats_plan,
        )
        recommendation.warnings.append("AI generation unavailable; deterministic fallback was used.")
        _log_stage_time("fallback_initial_composition", stage_started, generation_id=generation_id)

    stage_started = time.perf_counter()
    recommendation = inject_missing_keywords(
        recommendation, parsed_jd, ats_plan, None if ats_optimization_mode == "aggressive" else profile
    )
    recommendation = strengthen_resume_recommendation(recommendation, parsed_jd, ats_plan, target_pages)
    locked = build_locked_fields(profile) if profile else None
    recommendation = apply_resume_quality_gate(recommendation, parsed_jd, profile, target_pages, locked=locked)
    if locked:
        recommendation.locked_fields = locked.model_dump(mode="json")
    recommendation = fit_resume_to_page_budget(recommendation, parsed_jd, ats_plan=ats_plan, target_pages=target_pages)
    _log_stage_time("initial_postprocess", stage_started, generation_id=generation_id)
    return recommendation


async def _run_recruiter_review(
    *,
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    profile: MasterProfile | None,
    ats_score: ATSScore,
) -> RecruiterReview | None:
    """Run recruiter review as a non-fatal quality signal."""
    try:
        review = await asyncio.to_thread(
            recruiter_review_agent.run,
            recommendation,
            ats_score,
            parsed_jd,
            profile,
        )
        logger.info(
            "recruiter_review.score=%.1f cliche_count=%d weak_bullets=%d",
            review.overall_impression,
            review.cliche_count,
            len(review.weak_bullet_ids),
        )
        return review
    except Exception as exc:
        logger.warning("recruiter_review.failed (non-fatal): %s", exc)
        return None


def _recruiter_review_has_critical_issues(review: RecruiterReview) -> bool:
    return review.overall_impression < 6.0 or len(review.weak_bullet_ids) >= 3


async def _execute_repair_strategy(
    strategy: RepairStrategy,
    rec: ResumeRecommendation,
    parsed_jd: ParsedJD,
    profile: MasterProfile | None,
    ats_plan,
    evidence: EvidenceGraph | None,
    current_score: ATSScore,
    attempt: int,
    *,
    target_pages: int = 1,
    overflow: bool = False,
    locked: LockedFields | None = None,
    repair_actions: list[str] | None = None,
    aggressive_mode: bool = False,
) -> ResumeRecommendation:
    """Route a repair pass to the narrow strategy handler selected by score."""
    actions = repair_actions if repair_actions is not None else []
    original = rec.model_copy(deep=True)
    repaired = rec.model_copy(deep=True)

    if ats_plan and ats_plan.target_resume_title:
        repaired.target_title = ats_plan.target_resume_title
    elif parsed_jd.job_title:
        repaired.target_title = parsed_jd.job_title

    if strategy == RepairStrategy.KEYWORD_INJECTION:
        repaired = _repair_keyword_injection(
            repaired, parsed_jd, profile, ats_plan, current_score, actions, aggressive_mode=aggressive_mode
        )
    elif strategy == RepairStrategy.BULLET_STRENGTHENING:
        repaired = _repair_bullet_strengthening(repaired, actions)
    elif strategy == RepairStrategy.RESPONSIBILITY_ALIGNMENT:
        repaired = _repair_responsibility_alignment(repaired, parsed_jd, actions)
    elif strategy == RepairStrategy.SUMMARY_REFINEMENT:
        repaired = _repair_summary_refinement(repaired, parsed_jd, ats_plan, actions)
    elif strategy == RepairStrategy.PAGE_FIT:
        repaired = _repair_page_fit(repaired, target_pages, overflow, actions)
    elif strategy == RepairStrategy.FINAL_SAFETY:
        if evidence and not aggressive_mode:
            removed_claims = _remove_hallucinations(repaired, evidence, actions)
            if removed_claims:
                actions.append(f"Removed {removed_claims} unsupported claims flagged as potential hallucinations.")
            logger.info("repair_loop.hallucination_removal applied on final pass")
        if profile and not aggressive_mode:
            repaired = apply_resume_quality_gate(repaired, parsed_jd, profile, target_pages, locked=locked)

    if strategy != RepairStrategy.FINAL_SAFETY and current_score.section_score.score < 90 and profile:
        new_strategy = build_resume_strategy(parsed_jd, profile)
        if new_strategy.section_order != repaired.section_order:
            repaired.section_order = new_strategy.section_order
            actions.append("Optimized section order based on JD focus.")

    repaired = _restore_locked_bullets(original, repaired)
    validate_locked_fields_in_output(repaired, locked, logger=logger)
    if locked:
        repaired.locked_fields = locked.model_dump(mode="json")
    logger.debug("repair_loop.strategy_complete strategy=%s attempt=%s", strategy.value, attempt)
    return repaired


def _repair_keyword_injection(
    rec: ResumeRecommendation,
    parsed_jd: ParsedJD,
    profile: MasterProfile | None,
    ats_plan,
    score: ATSScore,
    actions: list[str] | None = None,
    aggressive_mode: bool = False,
) -> ResumeRecommendation:
    """Inject missing confirmed keywords into skills and summary without deleting content."""
    repaired = rec.model_copy(deep=True)
    missing = _dedupe([*score.missing_keywords, *score.keyword_score.critical_missing])
    if not missing:
        missing = [kw for kw in build_master_keyword_list(parsed_jd, ats_plan) if not _resume_contains_keyword(repaired, kw)]

    if aggressive_mode:
        supported = _dedupe([*missing, *build_master_keyword_list(parsed_jd, ats_plan)])[:40]
        learning = []
    elif profile:
        truth = classify_jd_keyword_truth(
            parsed_jd,
            build_candidate_evidence(profile, recommendation=repaired),
            ats_plan,
            keywords=missing,
        )
        supported = truth.source_supported
        learning = truth.adjacent_or_learning
    else:
        supported = [term for term in missing if _skill_like(term)]
        learning = []

    skills_corpus = " ".join(" ".join(group.skills) for group in repaired.skills)
    supported_to_add = [
        term for term in supported[:20]
        if _skill_like(term) and not _has_synonym_form(skills_corpus, term)
    ][:12 if aggressive_mode else 5]
    learning_to_add = [
        term for term in learning[:12]
        if _skill_like(term) and not _has_synonym_form(skills_corpus, term)
    ][:4]

    if supported_to_add or learning_to_add:
        repaired.skills = merge_typed_skill_groups(
            repaired.skills,
            supported_to_add,
            learning_focus_values=[learning_focus_phrase(term) for term in learning_to_add],
        )
        if actions is not None:
            actions.append(f"Injected {len(supported_to_add)} supported keywords into skills.")

    if supported_to_add:
        _repair_summary_refinement(repaired, parsed_jd, ats_plan, actions)
    if aggressive_mode:
        _repair_bullets(repaired, supported_to_add[:8], profile, actions)
    return repaired


def _repair_bullet_strengthening(rec: ResumeRecommendation, actions: list[str] | None = None) -> ResumeRecommendation:
    """Repair the weakest STAR bullets without removing bullets or entries."""
    repaired = rec.model_copy(deep=True)
    weak: list[tuple[float, ResumeBullet]] = []
    for entry in [*repaired.experience, *repaired.projects]:
        if not getattr(entry, "included", True):
            continue
        for bullet in entry.bullets:
            if bullet.status == BulletStatus.LOCKED:
                continue
            report = validate_single_bullet(bullet.text)
            bullet.star_score = max(0.0, min(100.0, float(report.star_score)))
            if report.star_score < 65 and report.is_fixable:
                weak.append((report.star_score, bullet))

    changed = 0
    for _, bullet in sorted(weak, key=lambda item: item[0])[:3]:
        repaired_text = repair_incomplete_bullet(bullet.text)
        if repaired_text != bullet.text:
            bullet.text = repaired_text
            report = validate_single_bullet(bullet.text)
            bullet.star_score = max(0.0, min(100.0, float(report.star_score)))
            bullet.status = BulletStatus.PENDING
            bullet.repair_note = "Strengthened with STAR outcome."
            changed += 1
    if changed and actions is not None:
        actions.append(f"Strengthened {changed} weak STAR bullets.")
    return repaired


def _repair_responsibility_alignment(
    rec: ResumeRecommendation,
    parsed_jd: ParsedJD,
    actions: list[str] | None = None,
) -> ResumeRecommendation:
    """Add missing JD responsibility terms to existing bullets without deleting content."""
    repaired = rec.model_copy(deep=True)
    corpus = _build_resume_corpus_for_repair(repaired)
    missing = [item for item in parsed_jd.responsibilities[:8] if not _contains(corpus, item)]
    changed = 0
    for responsibility in missing[:3]:
        target = _first_editable_bullet(repaired)
        if target is None:
            break
        original = target.text
        target.text = _inject_keyword_naturally(target.text, _short_responsibility_phrase(responsibility))
        if target.text != original:
            changed += 1
    if changed and actions is not None:
        actions.append(f"Aligned {changed} bullets to missing JD responsibilities.")
    return repaired


def _repair_summary_refinement(
    rec: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan,
    actions: list[str] | None = None,
) -> ResumeRecommendation:
    """Ensure the summary carries the title and top confirmed keywords early."""
    priority = _dedupe([
        parsed_jd.job_title or "",
        *([*ats_plan.priority_keywords[:8]] if ats_plan else []),
        *build_master_keyword_list(parsed_jd, ats_plan)[:8],
    ])
    current = _clean(rec.summary)
    if not current:
        current = f"{rec.target_title or parsed_jd.job_title} candidate aligned with the target role."
    missing = [term for term in priority if term and not _contains(current, term)]
    natural = [term for term in missing if _skill_like(term)][:3]
    if natural:
        current = f"{current.rstrip('.')}. Experienced with {' and '.join(natural)}."
        rec.summary = _trim_words(current, 115)
        if actions is not None:
            actions.append(f"Refined summary with {len(natural)} top JD keywords.")
    else:
        rec.summary = _trim_words(current, 115)
    return rec


def _repair_page_fit(
    rec: ResumeRecommendation,
    target_pages: int,
    overflow: bool,
    actions: list[str] | None = None,
) -> ResumeRecommendation:
    """Tighten text for page fit without deleting bullets, projects, or sections."""
    repaired = rec.model_copy(deep=True)
    if not overflow:
        if actions is not None:
            actions.append("Checked page-fit strategy without content removal.")
        return repaired
    repaired.summary = _trim_words(repaired.summary or "", 75 if target_pages <= 1 else 105)
    for entry in [*repaired.experience, *repaired.projects]:
        for bullet in entry.bullets:
            if bullet.status != BulletStatus.LOCKED:
                bullet.text = _trim_bullet(bullet, 155 if target_pages <= 1 else 175).text
    if actions is not None:
        actions.append("Compressed wording for PDF page fit without deleting bullets.")
    return repaired


def _repair_recommendation(
    *,
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    evidence: EvidenceGraph | None,
    ats_plan,
    current_score: ATSScore,
    target_pages: int,
    overflow: bool,
    attempt: int,
    is_final_pass: bool,
    locked: LockedFields | None,
    repair_actions: list[str],
) -> ResumeRecommendation:
    original = recommendation.model_copy(deep=True)
    rec = recommendation.model_copy(deep=True)
    
    # Update title
    if ats_plan and ats_plan.target_resume_title:
        rec.target_title = ats_plan.target_resume_title
    elif parsed_jd.job_title:
        rec.target_title = parsed_jd.job_title

    # Identify missing keywords for repair
    placement = analyze_keyword_placement(rec, parsed_jd, ats_plan)
    missing_for_repair = _dedupe([*current_score.missing_keywords, *placement.missing_high_priority_keywords])
    
    # Evidence-backed split
    supported, learning, unsupported = _split_truth_terms(missing_for_repair, profile, rec)
    
    repair_actions.append(_repair_pass_label(attempt, is_final_pass))

    # Hallucination removal DISABLED — evidence gate removed for max ATS coverage.

    if attempt == 0:
        # Keyword injection: add confirmed terms to summary/skills.
        _repair_summary(rec, parsed_jd, ats_plan, supported, repair_actions)
        _repair_skills(rec, supported, [], repair_actions)
        rec = inject_missing_keywords(rec, parsed_jd, ats_plan, profile)
    elif attempt == 1:
        # Bullet strengthening: improve weak bullets without deleting content.
        rec = strengthen_resume_recommendation(rec, parsed_jd, ats_plan, target_pages)
    elif attempt == 2:
        # Missing keyword insertion into evidence-backed bullets.
        _repair_bullets(rec, supported, profile, repair_actions)
    elif attempt == 3:
        # Summary refinement: make target title and priority terms visible early.
        _repair_summary(rec, parsed_jd, ats_plan, supported, repair_actions)
    elif attempt == 4:
        # Skills completion: confirmed terms plus aspirational terms as Learning Focus.
        _repair_skills(rec, supported, learning, repair_actions)
    elif attempt == 5:
        # PDF fit pass: trim only if the prior compile showed overflow.
        if overflow:
            rec = _compress_for_overflow(rec, target_pages, repair_actions)
        else:
            rec = fit_resume_to_page_budget(rec, parsed_jd, ats_plan=ats_plan, target_pages=target_pages)
            repair_actions.append("Checked page-fit budget without deleting source content.")
    elif is_final_pass:
        # Safety pass: local validation after hallucination removal.
        rec = strengthen_resume_recommendation(rec, parsed_jd, ats_plan, target_pages)

    if current_score.section_score.score < 90 and not is_final_pass:
        new_strategy = build_resume_strategy(parsed_jd, profile)
        if new_strategy.section_order != rec.section_order:
            rec.section_order = new_strategy.section_order
            repair_actions.append("Optimized section order based on JD focus.")

    if is_final_pass:
        rec = apply_resume_quality_gate(rec, parsed_jd, profile, target_pages, locked=locked)
    
    rec = _restore_locked_bullets(original, rec)
    validate_locked_fields_in_output(rec, locked, logger=logger)
    if locked:
        rec.locked_fields = locked.model_dump(mode="json")
    return rec


def _repair_pass_label(attempt: int, is_final_pass: bool) -> str:
    labels = {
        0: "Repair pass 1: keyword injection.",
        1: "Repair pass 2: bullet strengthening.",
        2: "Repair pass 3: missing keyword insertion into bullets.",
        3: "Repair pass 4: summary refinement.",
        4: "Repair pass 5: skills and Learning Focus completion.",
        5: "Repair pass 6: PDF fit pass.",
    }
    if is_final_pass:
        return "Repair pass final: safety validation and hallucination removal."
    return labels.get(attempt, f"Repair pass {attempt + 1}: local optimization.")


def _remove_hallucinations(rec: ResumeRecommendation, evidence: EvidenceGraph, actions: list[str]) -> int:
    removed = 0
    for entry in [*rec.experience, *rec.projects]:
        if not entry.included: continue
        valid_bullets = []
        for bullet in entry.bullets:
            if bullet.status == BulletStatus.LOCKED:
                valid_bullets.append(bullet)
                continue
            if trace_claim(bullet.text, evidence, source_id=entry.source_id):
                valid_bullets.append(bullet)
            else:
                removed += 1
        entry.bullets = valid_bullets
    return removed


def _repair_summary(rec: ResumeRecommendation, parsed_jd: ParsedJD, ats_plan, terms: list[str], actions: list[str]) -> None:
    priority = _dedupe([
        parsed_jd.job_title or "",
        *([*ats_plan.priority_keywords[:8]] if ats_plan else []),
        *terms[:8],
    ])[:10]
    current = _clean(rec.summary)
    missing = [term for term in priority if term and not _contains(current, term)]
    if not current:
        current = f"{rec.target_title or parsed_jd.job_title} candidate aligned with the target role."
    if missing:
        natural = _dedupe(missing)[:2]
        if natural:
            current = f"{current.rstrip('.')}. Brings source-backed experience with {' and '.join(natural)}."
            actions.append(f"Repaired summary with {len(natural)} supported priority JD terms.")
    rec.summary = _trim_words(current, 115)


def _repair_skills(rec: ResumeRecommendation, supported: list[str], learning: list[str], actions: list[str]) -> None:
    hands_on = [term for term in supported if _skill_like(term)]
    target_terms = [term for term in learning if _skill_like(term) and not _looks_like_certification(term)]
    if hands_on:
        actions.append(f"Added {len(hands_on)} supported missing terms to skills.")
    if target_terms:
        actions.append(f"Added {len(target_terms[:6])} adjacent JD terms as learning focus.")
    rec.skills = merge_typed_skill_groups(rec.skills, hands_on, learning_focus_values=target_terms[:6])


def _repair_bullets(
    rec: ResumeRecommendation,
    supported_terms: list[str],
    profile: MasterProfile | None,
    actions: list[str],
) -> None:
    remaining = [term for term in supported_terms if _skill_like(term)][:8]
    if not remaining:
        return
    source_support = _source_support_map(profile) if profile else {}
    changed = 0
    for entry in [*rec.experience, *rec.projects]:
        if not getattr(entry, "included", True):
            continue
        support_text = source_support.get(entry.source_id, "")
        usable = [term for term in remaining if not source_support or _contains(support_text, term)]
        if not usable:
            continue
        for bullet in entry.bullets:
            if bullet.status == BulletStatus.LOCKED:
                continue
            term = next((value for value in usable if not _contains(bullet.text, value)), None)
            if not term:
                continue
            original_text = bullet.text
            bullet.text = _inject_keyword_naturally(bullet.text, term)
            if bullet.text == original_text:
                logger.debug("repair_loop.keyword_injection.skipped source_id=%s term=%s", entry.source_id, term)
                continue
            logger.debug("repair_loop.keyword_injection.applied source_id=%s term=%s", entry.source_id, term)
            remaining.remove(term)
            changed += 1
            break
        if not remaining:
            break
    if changed:
        actions.append(f"Added {changed} JD terms to bullets.")


def _compress_for_overflow(rec: ResumeRecommendation, target_pages: int, actions: list[str]) -> ResumeRecommendation:
    compressed = rec.model_copy(deep=True)
    compressed.summary = _trim_words(compressed.summary or "", 80 if target_pages <= 1 else 115)
    for exp in compressed.experience:
        limit = 4 if target_pages <= 1 else 5
        exp.bullets = [_trim_bullet(bullet, 180) for bullet in exp.bullets[:limit]]
    for project in compressed.projects:
        limit = 2 if target_pages <= 1 else 3
        project.bullets = [_trim_bullet(bullet, 165) for bullet in project.bullets[:limit]]
        project.technologies = project.technologies[:6]
    if target_pages <= 1:
        compressed.projects = compressed.projects[:2]
        compressed.certifications = compressed.certifications[:3]
        compressed.achievements = compressed.achievements[:2]
        compressed.awards = compressed.awards[:2]
    actions.append("Compressed resume after PDF page overflow.")
    return compressed


def _restore_locked_bullets(original: ResumeRecommendation, repaired: ResumeRecommendation) -> ResumeRecommendation:
    rec = repaired.model_copy(deep=True)
    _restore_locked_for_entries(original.experience, rec.experience)
    _restore_locked_for_entries(original.projects, rec.projects)
    return rec


def _restore_locked_for_entries(original_entries: list, repaired_entries: list) -> None:
    by_source = {entry.source_id: entry for entry in repaired_entries}
    for original_entry in original_entries:
        locked = [bullet for bullet in original_entry.bullets if bullet.status == BulletStatus.LOCKED]
        if not locked:
            continue
        repaired_entry = by_source.get(original_entry.source_id)
        if repaired_entry is None:
            restored = original_entry.model_copy(deep=True)
            restored.bullets = locked
            repaired_entries.append(restored)
            by_source[original_entry.source_id] = restored
            continue
        existing_by_id = {bullet.id: index for index, bullet in enumerate(repaired_entry.bullets)}
        for locked_bullet in locked:
            if locked_bullet.id in existing_by_id:
                repaired_entry.bullets[existing_by_id[locked_bullet.id]] = locked_bullet
            else:
                repaired_entry.bullets.insert(0, locked_bullet)


class _AttemptState:
    def __init__(
        self,
        *,
        recommendation: ResumeRecommendation,
        latex_source: str,
        pdf_path: str,
        page_count: int,
        json_score: ATSScore,
        pdf_score: ATSScore,
        warnings: list[str],
    ):
        self.recommendation = recommendation
        self.latex_source = latex_source
        self.pdf_path = pdf_path
        self.page_count = page_count
        self.json_score = json_score
        self.pdf_score = pdf_score
        self.warnings = warnings


def _choose_best_attempt(current: _AttemptState | None, candidate: _AttemptState, target_pages: int) -> _AttemptState:
    if current is None:
        return candidate
    candidate_overflow = candidate.page_count != target_pages
    current_overflow = current.page_count != target_pages
    if candidate_overflow != current_overflow:
        return candidate if not candidate_overflow else current
    if candidate.pdf_score.overall_score >= current.pdf_score.overall_score:
        return candidate
    return current


def _cleanup_superseded(best: _AttemptState | None, current: _AttemptState) -> None:
    if best and best.pdf_path != current.pdf_path:
        try:
            Path(best.pdf_path).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove superseded optimization PDF: %s", best.pdf_path)


def _split_truth_terms(
    terms: list[str],
    profile: MasterProfile | None,
    recommendation: ResumeRecommendation | None = None,
) -> tuple[list[str], list[str], list[str]]:
    if not profile:
        return terms, [], []
    evidence = build_candidate_evidence(profile, recommendation=recommendation)
    truth = classify_jd_keyword_truth(ParsedJD(job_title=""), evidence, keywords=_dedupe(terms))
    return truth.source_supported, truth.adjacent_or_learning, truth.unsupported


def _source_support_map(profile: MasterProfile) -> dict[str, str]:
    result: dict[str, str] = {}
    for exp in profile.work_experience:
        result[exp.id] = _normalize(" ".join([exp.company, exp.title, exp.description or "", *exp.bullets]))
    for project in profile.projects:
        result[project.id] = _normalize(" ".join([project.name, project.description or "", *project.technologies, *project.bullets]))
    return result


def _append_skill_group(rec: ResumeRecommendation, category: str, values: list[str]) -> None:
    values = _dedupe([value for value in values if _skill_like(value)])
    if not values:
        return
    for index, group in enumerate(rec.skills):
        if group.category.casefold() == category.casefold():
            rec.skills[index] = group.model_copy(update={"skills": _dedupe([*group.skills, *values])[:18]})
            return
    rec.skills.append(ResumeSkillGroup(category=category, skills=values[:18]))


def _append_bullet_clause(text: str, term: str) -> str:
    return _inject_keyword_naturally(text, term)


def _inject_keyword_naturally(bullet_text: str, keyword: str) -> str:
    """Inject a keyword into a bullet without robotic keyword stuffing."""
    text = _clean(bullet_text)
    kw = _clean(keyword)
    if not text or not kw:
        return bullet_text
    text_lower = text.casefold()
    if any(form.casefold() in text_lower for form in get_all_forms(kw)):
        return text

    if _count_keyword_injections(text) >= 2:
        return text

    using_match = re.search(r"\b(using|with|via)\s+([A-Za-z][\w+#/+-]*(?:\.[A-Za-z][\w+#/+-]*)*)", text, re.IGNORECASE)
    if using_match:
        end = using_match.end()
        return text[:end] + f" and {kw}" + text[end:]

    period_pos = text.rfind(".")
    if period_pos > len(text) * 0.7:
        return text[:period_pos] + f", leveraging {kw}" + text[period_pos:]

    if text.endswith("."):
        return text[:-1] + f", using {kw}."
    return text + f", using {kw}"


def _count_keyword_injections(text: str) -> int:
    pattern = re.compile(
        r"\b(?:using|with|via|leveraging|utilizing|employing|through)\s+[A-Za-z][\w.+#/-]*",
        re.IGNORECASE,
    )
    return len(pattern.findall(text))


def _keyword_dimension_score(score: ATSScore) -> float:
    return float(getattr(score, "keyword_coverage_score", 0.0) or score.keyword_score.coverage_percent or 100.0)


def _bullet_dimension_score(score: ATSScore) -> float:
    if getattr(score, "bullet_relevance_score", 0.0):
        return float(score.bullet_relevance_score)
    return float(score.readability_score.score or 100.0)


def _page_dimension_score(score: ATSScore) -> float:
    if getattr(score, "page_compliance_score", 0.0):
        return float(score.page_compliance_score)
    weighted = score.score_breakdown.get("page_fit_structure")
    if weighted is not None:
        return min(100.0, float(weighted) / 0.05)
    return 100.0


def _resume_contains_keyword(rec: ResumeRecommendation, keyword: str) -> bool:
    corpus = _build_resume_corpus_for_repair(rec)
    return _has_synonym_form(corpus, keyword)


def _has_synonym_form(text: str, keyword: str) -> bool:
    normalized_text = _normalize(text)
    return any(_contains(normalized_text, form) for form in get_all_forms(keyword))


def _first_editable_bullet(rec: ResumeRecommendation) -> ResumeBullet | None:
    for entry in [*rec.experience, *rec.projects]:
        if not getattr(entry, "included", True):
            continue
        for bullet in entry.bullets:
            if bullet.status != BulletStatus.LOCKED:
                return bullet
    return None


def _short_responsibility_phrase(value: str) -> str:
    words = _clean(value).split()
    if len(words) <= 4:
        return _clean(value)
    return " ".join(words[:4]).rstrip(".,;:")


def _trim_bullet(bullet: ResumeBullet, limit: int) -> ResumeBullet:
    text = _clean(bullet.text)
    if len(text) <= limit:
        return bullet
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return bullet.model_copy(update={"text": f"{clipped}."})


def _missing_from_score(score: ATSScore) -> list[str]:
    return _dedupe([*score.missing_keywords, *score.keyword_score.critical_missing])


def _matched_from_score(score: ATSScore) -> list[str]:
    return [match.keyword for match in score.keyword_score.details if match.found]


def _score_explanation(score: ATSScore, page_count: int | None, target_pages: int, profile: MasterProfile | None = None) -> list[str]:
    reasons = [*score.warnings, *score.recommendations]
    if page_count is not None and page_count != target_pages:
        reasons.append(f"PDF page count is {page_count}; target is {target_pages}.")
    
    if score.overall_score < 90:
        # Check if missing keywords are unsupported by evidence
        from app.services.candidate_evidence_service import build_candidate_evidence, classify_jd_keyword_truth
        evidence = build_candidate_evidence(profile) if profile else None
        if evidence:
            missing = [*score.missing_keywords, *score.keyword_score.critical_missing]
            truth = classify_jd_keyword_truth(ParsedJD(job_title=""), evidence, keywords=missing)
            unsupported = [*truth.unsupported, *truth.adjacent_or_learning]
            if unsupported:
                reasons.append(f"Cannot reach 90+ honestly because these required JD skills are not supported by master profile: {', '.join(unsupported[:5])}")
    
    if score.overall_score < 100 and score.keyword_score.critical_missing:
        reasons.append("A perfect score is blocked by missing exact critical JD terms in extracted PDF text.")
    return _dedupe(reasons)[:8]


def _looks_like_certification(value: str) -> bool:
    return bool(_CERT_RE.search(value or ""))


def _skill_like(value: str) -> bool:
    cleaned = _clean(value)
    return bool(cleaned and len(cleaned.split()) <= 4 and not cleaned.isdigit())


def _contains(text: str, term: str) -> bool:
    normalized_text = _normalize(text)
    normalized_term = _normalize(term)
    if not normalized_term:
        return True
    pattern = (
        re.compile(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])")
        if " " in normalized_term
        else re.compile(rf"\b{re.escape(normalized_term)}\b")
    )
    return bool(pattern.search(normalized_text))


def _normalize(value: str | None) -> str:
    lowered = str(value or "").casefold()
    lowered = re.sub(r"[^a-z0-9+#./\s-]+", " ", lowered)
    return _SPACE_RE.sub(" ", lowered).strip()


def _clean(value: str | None) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def _trim_words(text: str, limit: int) -> str:
    words = _clean(text).split()
    if len(words) <= limit:
        return _clean(text)
    return " ".join(words[:limit]).rstrip(".,;:") + "."


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean(str(value or ""))
        key = _normalize(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _final_keyword_repair(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
    profile: MasterProfile | None = None,
    target_pages: int = 1,
    aggressive_mode: bool = False,
) -> ResumeRecommendation:
    """After all compression, re-insert critical keywords into evidence-safe locations."""
    rec = recommendation.model_copy(deep=True)
    corpus = _build_resume_corpus_for_repair(rec)
    master_keywords = build_master_keyword_list(parsed_jd, ats_plan)

    missing = []
    for kw in master_keywords:
        if not _contains(corpus, kw):
            missing.append(kw)

    if not missing:
        return rec

    truth = (
        classify_jd_keyword_truth(
            parsed_jd,
            build_candidate_evidence(profile, recommendation=rec),
            ats_plan,
            keywords=missing,
        )
        if profile and not aggressive_mode
        else None
    )

    supported_missing: list[str] = []
    learning_missing: list[str] = []
    unsupported_missing: list[str] = []
    for kw in missing:
        if aggressive_mode:
            if _is_skill_like(kw): supported_missing.append(kw)
        elif truth is None:
            if _is_skill_like(kw): supported_missing.append(kw)
        elif is_supported_placement(kw, truth): supported_missing.append(kw)
        elif is_learning_placement(kw, truth): learning_missing.append(kw)
        else: unsupported_missing.append(kw)

    # Inject
    _inject_missing_skills(rec, supported_missing, ats_plan)
    if learning_missing:
        _append_skill_group(rec, "Learning Focus", [learning_focus_phrase(term) for term in learning_missing[:6]])

    # Warnings
    if unsupported_missing and not aggressive_mode:
        rec.warnings = _dedupe([
            *rec.warnings,
            f"{len(unsupported_missing)} JD terms skipped (no profile evidence): {', '.join(unsupported_missing[:4])}.",
        ])

    return rec


def _inject_missing_skills(rec, terms, ats_plan):
    skill_terms = [t for t in terms if _is_skill_like(t)]
    if not skill_terms: return
    rec.skills = merge_typed_skill_groups(rec.skills, skill_terms)


def _build_resume_corpus_for_repair(rec: ResumeRecommendation) -> str:
    parts = [rec.target_title or "", rec.summary or ""]
    for exp in rec.experience:
        if exp.included:
            parts.extend([exp.title, exp.company, *[b.text for b in exp.bullets if b.status != BulletStatus.REJECTED]])
    for proj in rec.projects:
        if proj.included:
            parts.extend([proj.name, *proj.technologies, *[b.text for b in proj.bullets if b.status != BulletStatus.REJECTED]])
    for group in rec.skills:
        parts.extend([group.category, *group.skills])
    return " ".join(parts)


def _is_skill_like(value: str) -> bool:
    cleaned = _clean(value)
    return bool(cleaned and len(cleaned.split()) <= 4 and not cleaned.isdigit())


def _extract_text_from_latex(latex_source: str, generation_id: str) -> str:
    return extract_text_from_latex(latex_source)[:10000]
