"""Compile-and-count PDF fitting for selected resume page targets."""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.resume import ResumeRecommendation
from app.schemas.scoring import ATSScore
from app.services.docx_export_service import export_resume_docx
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import PDFCompileError, compile_pdf
from app.services.pdf_inspection_service import inspect_pdf
from app.services.resume_budget_service import fit_resume_to_page_budget
from app.services.resume_validation_gate import (
    validate_pdf_text_parseability,
    validate_plain_text_for_export,
    validate_resume_for_export,
)
from app.services.scoring_service import compute_ats_score_from_text, extract_text_from_latex

logger = logging.getLogger(__name__)


class PDFPageFitResult(BaseModel):
    recommendation: ResumeRecommendation
    latex_source: str
    pdf_path: str
    page_count: int
    target_pages: int
    ats_score: ATSScore
    compile_warnings: list[str] = Field(default_factory=list)
    inspection_warnings: list[str] = Field(default_factory=list)
    compression_actions: list[str] = Field(default_factory=list)
    compression_applied: bool = False
    attempts_used: int = 0
    docx_fallback_path: str = ""
    pdf_compile_error: str = ""
    pdf_failed: bool = False


async def compile_pdf_to_page_target(
    *,
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    generation_id: str,
    target_pages: int,
    ats_plan: ATSKeywordPlannerOutput | None = None,
    max_attempts: int = 8,
    is_fresher: bool = False,
) -> PDFPageFitResult:
    """
    Compile, inspect actual PDF pages, and compress until page target is met.

    For a one-page target, the resulting PDF must be exactly one page. For
    two-page mode, the result is accepted when it is one or two pages.
    """
    target_pages = max(1, min(target_pages, 2))
    rec = fit_resume_to_page_budget(
        recommendation=recommendation,
        parsed_jd=parsed_jd,
        ats_plan=ats_plan,
        target_pages=target_pages,
    )
    actions: list[str] = []
    best: PDFPageFitResult | None = None

    for attempt in range(1, max_attempts + 1):
        rec = validate_resume_for_export(rec, parsed_jd=parsed_jd).recommendation
        latex_source = render_latex(rec, is_fresher=is_fresher)
        try:
            pdf_path, compile_warnings = await compile_pdf(latex_source=latex_source, generation_id=generation_id)
        except PDFCompileError as exc:
            logger.error("PDF compile failed on page-fit attempt %d/%d: %s", attempt, max_attempts, exc)
            return _build_docx_fallback_result(
                rec=rec,
                parsed_jd=parsed_jd,
                ats_plan=ats_plan,
                generation_id=generation_id,
                latex_source=latex_source,
                target_pages=target_pages,
                attempts_used=attempt,
                compile_warnings=[*exc.response_errors(), *exc.warnings],
                pdf_compile_error=_pdf_compile_error_summary(exc),
                compression_actions=actions,
            )
        inspection = inspect_pdf(pdf_path)
        validate_plain_text_for_export(inspection.text, artifact="pdf_text")
        validate_pdf_text_parseability(rec, inspection.text)
        ats_score = compute_ats_score_from_text(
            inspection.text,
            parsed_jd,
            ats_plan=ats_plan,
            target_title=rec.target_title,
            target_pages=target_pages,
            page_count=inspection.page_count,
        )
        result = PDFPageFitResult(
            recommendation=rec,
            latex_source=latex_source,
            pdf_path=pdf_path,
            page_count=inspection.page_count,
            target_pages=target_pages,
            ats_score=ats_score,
            compile_warnings=compile_warnings,
            inspection_warnings=inspection.warnings,
            compression_actions=list(actions),
            compression_applied=bool(actions),
            attempts_used=attempt,
        )

        if _page_target_satisfied(inspection.page_count, target_pages):
            _cleanup_result(best, keep=result)
            return result

        best = _choose_best_result(best, result, target_pages)
        if inspection.page_count < 1 or inspection.page_count <= target_pages:
            break

        stage = attempt if target_pages == 1 else max(1, attempt - 1)
        rec, action = compress_resume_for_page_overflow(
            rec,
            parsed_jd=parsed_jd,
            ats_plan=ats_plan,
            stage=stage,
            target_pages=target_pages,
        )
        actions.append(action)
        if best.pdf_path != pdf_path:
            _cleanup_path(pdf_path)

    if best is None:
        latex_source = render_latex(rec, is_fresher=is_fresher)
        return _build_docx_fallback_result(
            rec=rec,
            parsed_jd=parsed_jd,
            ats_plan=ats_plan,
            generation_id=generation_id,
            latex_source=latex_source,
            target_pages=target_pages,
            attempts_used=max_attempts,
            compile_warnings=["PDF page fitting failed before producing an inspectable PDF."],
            pdf_compile_error="PDF page fitting failed before producing an inspectable PDF.",
            compression_actions=actions,
        )
    return best


def _build_docx_fallback_result(
    *,
    rec: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
    generation_id: str,
    latex_source: str,
    target_pages: int,
    attempts_used: int,
    compile_warnings: list[str],
    pdf_compile_error: str,
    compression_actions: list[str],
) -> PDFPageFitResult:
    try:
        docx_path = export_resume_docx(rec, generation_id)
        logger.info("docx_fallback.generated path=%s", docx_path)
    except Exception:
        logger.exception("DOCX fallback also failed")
        raise

    ats_score = compute_ats_score_from_text(
        extract_text_from_latex(latex_source),
        parsed_jd,
        ats_plan=ats_plan,
        target_title=rec.target_title,
        target_pages=target_pages,
        page_count=None,
    )
    return PDFPageFitResult(
        recommendation=rec,
        latex_source=latex_source,
        pdf_path="",
        page_count=0,
        target_pages=target_pages,
        ats_score=ats_score,
        compile_warnings=compile_warnings,
        inspection_warnings=["PDF generation failed; DOCX fallback was generated."],
        compression_actions=list(compression_actions),
        compression_applied=bool(compression_actions),
        attempts_used=attempts_used,
        docx_fallback_path=docx_path,
        pdf_compile_error=pdf_compile_error,
        pdf_failed=True,
    )


def _pdf_compile_error_summary(exc: PDFCompileError) -> str:
    parts = [str(exc)]
    if exc.raw_output:
        parts.append(str(exc.raw_output).splitlines()[0][:500])
    elif exc.response_errors():
        parts.append(exc.response_errors()[0][:500])
    return " | ".join(part for part in parts if part)[:1000]


def compress_resume_for_page_overflow(
    recommendation: ResumeRecommendation,
    *,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
    stage: int,
    target_pages: int,
) -> tuple[ResumeRecommendation, str]:
    """
    Apply one ordered compression stage.

    Required order:
    1. Summary length
    2. Skills overflow
    3. Older/less relevant bullets
    4. Secondary project bullets
    5. Achievements descriptions
    6. Education details
    """
    rec = recommendation.model_copy(deep=True)
    if stage <= 1:
        before = _word_count(rec.summary)
        rec.summary = _trim_words(rec.summary or "", 55 if target_pages == 1 else 90)
        return rec, f"Compressed summary from {before} to {_word_count(rec.summary)} words."
    if stage == 2:
        removed = _compress_skills(rec, max_groups=4 if target_pages == 1 else 6, max_per_group=8 if target_pages == 1 else 12)
        return rec, f"Compressed skills overflow; removed or merged {removed} low-priority skills."
    if stage == 3:
        removed = _compress_experience_bullets(rec, target_pages=target_pages)
        return rec, f"Compressed older/less relevant experience bullets; removed {removed} bullets."
    if stage == 4:
        removed = _compress_project_bullets(rec, target_pages=target_pages)
        return rec, f"Compressed secondary project bullets; removed {removed} bullets."
    if stage == 5:
        changed = _compress_achievement_descriptions(rec)
        return rec, f"Compressed achievement descriptions; shortened {changed} descriptions while preserving names."
    if stage == 6:
        changed = _compress_education_details(rec)
        return rec, f"Compressed education details; removed {changed} GPA/honors/coursework details while preserving universities."

    # Final pressure pass: repeat low-risk trims without deleting anchors.
    removed = _compress_experience_bullets(rec, target_pages=target_pages, aggressive=True)
    removed += _compress_project_bullets(rec, target_pages=target_pages, aggressive=True)
    _compress_achievement_descriptions(rec, remove_descriptions=True)
    _compress_education_details(rec, remove_coursework=True)
    return rec, f"Applied final overflow compression; removed {removed} additional bullets and optional details."


def _page_target_satisfied(page_count: int, target_pages: int) -> bool:
    if target_pages == 1:
        return page_count == 1
    return 1 <= page_count <= target_pages


def _choose_best_result(
    current: PDFPageFitResult | None,
    candidate: PDFPageFitResult,
    target_pages: int,
) -> PDFPageFitResult:
    if current is None:
        return candidate
    candidate_over = max(0, candidate.page_count - target_pages)
    current_over = max(0, current.page_count - target_pages)
    if candidate_over != current_over:
        return candidate if candidate_over < current_over else current
    if candidate.ats_score.overall_score >= current.ats_score.overall_score:
        _cleanup_path(current.pdf_path)
        return candidate
    _cleanup_path(candidate.pdf_path)
    return current


def _cleanup_result(result: PDFPageFitResult | None, *, keep: PDFPageFitResult) -> None:
    if result and result.pdf_path != keep.pdf_path:
        _cleanup_path(result.pdf_path)


def _cleanup_path(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove superseded page-fit PDF: %s", path)


def _compress_skills(rec: ResumeRecommendation, *, max_groups: int, max_per_group: int) -> int:
    removed = 0
    groups = [group for group in rec.skills if group.skills]
    groups.sort(key=lambda group: (group.category.casefold() in {"additional skills", "target jd terms"}, group.category.casefold()))
    kept_groups = groups[:max_groups]
    overflow_terms = [skill for group in groups[max_groups:] for skill in group.skills]
    removed += len(overflow_terms)
    for group in kept_groups:
        if len(group.skills) > max_per_group:
            removed += len(group.skills) - max_per_group
            group.skills = group.skills[:max_per_group]
    rec.skills = kept_groups
    return removed


def _compress_experience_bullets(rec: ResumeRecommendation, *, target_pages: int, aggressive: bool = False) -> int:
    removed = 0
    primary_limit = 3 if aggressive and target_pages == 1 else 4 if target_pages == 1 else 5
    secondary_limit = 2 if aggressive and target_pages == 1 else 3 if target_pages == 1 else 4
    for index, exp in enumerate(rec.experience):
        limit = primary_limit if index == 0 else secondary_limit
        if len(exp.bullets) > limit:
            removed += len(exp.bullets) - limit
            exp.bullets = exp.bullets[:limit]
        exp.bullets = [_trim_bullet_text(bullet, 170 if aggressive else 190) for bullet in exp.bullets]
    return removed


def _compress_project_bullets(rec: ResumeRecommendation, *, target_pages: int, aggressive: bool = False) -> int:
    removed = 0
    bullet_limit = 1 if aggressive and target_pages == 1 else 2 if target_pages == 1 else 3
    for project in rec.projects:
        if len(project.bullets) > bullet_limit:
            removed += len(project.bullets) - bullet_limit
            project.bullets = project.bullets[:bullet_limit]
        project.bullets = [_trim_bullet_text(bullet, 150 if aggressive else 175) for bullet in project.bullets]
        project.technologies = project.technologies[:5 if target_pages == 1 else 8]
    return removed


def _compress_achievement_descriptions(rec: ResumeRecommendation, *, remove_descriptions: bool = False) -> int:
    changed = 0
    for item in [*rec.achievements, *rec.awards]:
        if item.description:
            item.description = "" if remove_descriptions else _trim_words(item.description, 14)
            changed += 1
    return changed


def _compress_education_details(
    rec: ResumeRecommendation,
    *,
    remove_coursework: bool = False,
) -> int:
    changed = 0
    for edu in rec.education:
        if edu.relevant_coursework:
            edu.relevant_coursework = [] if remove_coursework else edu.relevant_coursework[:2]
            changed += 1
        if edu.gpa:
            edu.gpa = None
            changed += 1
        if edu.honors:
            edu.honors = None
            changed += 1
    return changed


def _trim_bullet_text(bullet, limit: int):
    text = " ".join((bullet.text or "").split())
    if len(text) <= limit:
        return bullet
    clipped = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    return bullet.model_copy(update={"text": f"{clipped}."})


def _trim_words(text: str, limit: int) -> str:
    words = " ".join((text or "").split()).split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(".,;:") + "."


def _word_count(text: str | None) -> int:
    return len((text or "").split())
