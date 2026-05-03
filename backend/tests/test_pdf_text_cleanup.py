import asyncio
import re
import shutil

import pytest

from app.schemas.resume import (
    ResumeBullet,
    ResumeContactInfo,
    ResumeExperienceEntry,
    ResumeProjectEntry,
    ResumeRecommendation,
    ResumeSkillGroup,
)
from app.services.latex_render_service import render_latex
from app.services.pdf_compile_service import PDFCompileError, compile_pdf


def _empty_itemize_blocks(latex: str) -> list[str]:
    blocks = []
    if r"\begin{document}" in latex:
        latex = latex.split(r"\begin{document}", 1)[1]
    if re.search(r"\\resumeItemListStart\s*\\resumeItemListEnd", latex, re.DOTALL):
        blocks.append("resumeItemList")
    for match in re.finditer(r"\\begin\{itemize\}(?:\[[^\]]*\])?(.*?)\\end\{itemize\}", latex, re.DOTALL):
        if not re.search(r"\\item\b|\\resumeSubheading\b|\\resumeProjectHeading\b", match.group(1)):
            blocks.append("itemize")
    return blocks


def _base_resume(*, experience: list[ResumeExperienceEntry], projects: list[ResumeProjectEntry] | None = None) -> ResumeRecommendation:
    return ResumeRecommendation(
        session_id="test-session",
        target_title="Java Developer",
        summary="\u2022 \u0088 Full stack developer with Java and API experience.",
        contact=ResumeContactInfo(
            full_name="Test User",
            email="test@example.com",
        ),
        experience=experience,
        projects=projects or [],
        skills=[ResumeSkillGroup(category="Languages", skills=["Java", "SQL"])],
        education=[],
        certifications=[],
    )


def test_latex_render_removes_nested_and_corrupt_bullet_symbols():
    rec = _base_resume(
        experience=[
            ResumeExperienceEntry(
                source_id="exp1",
                company="Test Company",
                title="Developer",
                start_date="2024-01",
                end_date="2025-01",
                bullets=[
                    ResumeBullet(
                        id="b1",
                        text="\u2022 \u0088 Integrated REST APIs for real-time data synchronization.",
                        original_text="\u2022 \u0088 Integrated REST APIs for real-time data synchronization.",
                    )
                ],
            )
        ],
    )

    latex = render_latex(rec)

    assert "\u0088" not in latex
    assert "\u2022" not in latex
    assert r"\resumeItem{Integrated REST APIs for real-time data synchronization.}" in latex
    assert r"\resumeItem{\u2022" not in latex


def test_latex_render_splits_merged_bullet_paragraphs():
    rec = _base_resume(
        experience=[
            ResumeExperienceEntry(
                source_id="exp1",
                company="Test Company",
                title="Developer",
                start_date="2024-01",
                end_date="2025-01",
                bullets=[
                    ResumeBullet(
                        id="b1",
                        text="\u2022 Built REST APIs for real-time sync \u2022 Improved database query performance \u2022 Reduced PDF rendering errors",
                    )
                ],
            )
        ],
    )

    latex = render_latex(rec)

    assert latex.count(r"\resumeItem{") == 3
    assert r"\resumeItem{Built REST APIs for real-time sync}" in latex
    assert r"\resumeItem{Improved database query performance}" in latex
    assert r"\resumeItem{Reduced PDF rendering errors}" in latex
    assert "\u2022" not in latex
    assert "\u0088" not in latex


def test_latex_render_skips_empty_experience_and_project_bullet_lists():
    rec = _base_resume(
        experience=[
            ResumeExperienceEntry(
                source_id="exp-empty",
                company="No Bullet Co",
                title="Developer",
                start_date="2024-01",
                end_date="2025-01",
                bullets=[],
            ),
            ResumeExperienceEntry(
                source_id="exp-symbols",
                company="Symbol Co",
                title="Engineer",
                start_date="2023-01",
                end_date="2024-01",
                bullets=[
                    ResumeBullet(id="symbol-1", text="\u2022"),
                    ResumeBullet(id="symbol-2", text="  -  *  "),
                    ResumeBullet(id="symbol-3", text="\u2022 \u2022 Built REST API integrations."),
                ],
            ),
        ],
        projects=[
            ResumeProjectEntry(
                source_id="proj-empty",
                name="Empty Project",
                technologies=[],
                bullets=[],
            )
        ],
    )

    latex = render_latex(rec)

    assert r"\section{Experience}" in latex
    assert "No Bullet Co" in latex
    assert "Empty Project" in latex
    assert "Built REST API integrations" in latex
    assert "\u2022" not in latex
    assert "\u0088" not in latex
    assert _empty_itemize_blocks(latex) == []
    assert "Something's wrong--perhaps a missing item" not in latex

    if shutil.which("pdflatex"):
        pdf_path, warnings = asyncio.run(compile_pdf(latex, "empty-bullet-session"))
        assert pdf_path.endswith(".pdf")
        assert not any("missing item" in warning.lower() for warning in warnings)
    else:
        with pytest.raises(PDFCompileError) as exc_info:
            asyncio.run(compile_pdf(latex, "empty-bullet-session"))
        assert "pdflatex is not installed" in str(exc_info.value)
