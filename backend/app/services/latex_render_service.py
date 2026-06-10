"""
LaTeX render service - maps resume recommendation data to the canonical main.tex template.
Respects the full section_order from the recommendation.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.config import get_settings
from app.schemas.resume import (
    ResumeBullet,
    ResumeExperienceEntry,
    ResumeProjectEntry,
    ResumeRecommendation,
    ResumeSkillGroup,
    BulletStatus,
)
from app.services.jd_sanitization_service import (
    assert_render_text_safe,
    assert_resume_recommendation_safe,
    recommendation_to_plain_text,
)
from app.services.resume_validation_gate import validate_latex_for_export, validate_resume_for_export
from app.services.skill_taxonomy_service import sanitize_resume_skill_groups
from app.utils.latex_escape import (
    escape_latex,
    normalize_unicode_for_resume_export,
    sanitize_latex_url,
)

logger = logging.getLogger(__name__)
CANONICAL_LATEX_TEMPLATE = "main.tex"

_ALLOWED_BULLET_STATUSES = {
    BulletStatus.ACCEPTED,
    BulletStatus.EDITED,
    BulletStatus.LOCKED,
    BulletStatus.NEEDS_REPAIR,
    BulletStatus.PENDING,
}

_LEADING_BULLET_RE = re.compile(
    r"^(?:\s*(?:\\item\b|\\resumeItem\s*|\(?[a-z0-9]+\)|[0-9]+[.)]|[-*+.^]+|[\u02c6\u2022\u25cf\u25aa\u25a0\u00b7])\s*)+",
    re.IGNORECASE,
)
_BULLET_GLYPH_RE = re.compile(r"[\u02c6\u2022\u25cf\u25aa\u25a0\u00b7]")
_BULLET_SPLIT_RE = re.compile(r"(?:^|\s+)[\u2022\u25cf\u25aa\u25a0\u00b7]+\s+")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_SYMBOL_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)
_MOJIBAKE_REPLACEMENTS = {
    "\u00e2\u20ac\u00a2": "\u2022",
    "\u00e2\u20ac\u201d": "-",
    "\u00e2\u20ac\u201c": "-",
    "\u00c2\u02c6": " ",
    "\u00c2\u0088": " ",
    "\u00c2": " ",
}


def sanitize_recommendation(recommendation: ResumeRecommendation) -> ResumeRecommendation:
    """
    Final sanitization pass before LaTeX rendering.

    Ensures the recommendation cannot produce invalid LaTeX:
    - Removes empty/corrupted bullets
    - Removes nested bullet symbols
    - Skips entries with no valid bullets
    - Skips empty sections
    - Guarantees no empty itemize environment is generated

    This must run before render_latex in every code path that renders LaTeX.
    """
    import copy

    rec = copy.deepcopy(recommendation)

    if rec.summary is not None:
        cleaned = _clean_pdf_text(rec.summary)
        if not _is_valid_bullet_text(cleaned):
            rec.summary = None
        else:
            rec.summary = cleaned

    cleaned_experience: list[ResumeExperienceEntry] = []
    for exp in rec.experience:
        if not exp.included:
            continue
        valid_bullets: list[ResumeBullet] = []
        for bullet in exp.bullets:
            if bullet.status not in _ALLOWED_BULLET_STATUSES:
                continue
            for fragment in _split_bullet_fragments(bullet.text):
                text = _clean_pdf_text(fragment)
                if _is_valid_bullet_text(text):
                    new_bullet = copy.deepcopy(bullet)
                    new_bullet.text = text
                    valid_bullets.append(new_bullet)
        if valid_bullets:
            exp.bullets = valid_bullets
            cleaned_experience.append(exp)

    rec.experience = cleaned_experience

    cleaned_projects: list[ResumeProjectEntry] = []
    for proj in rec.projects:
        if not proj.included:
            continue
        valid_proj_bullets: list[ResumeBullet] = []
        for bullet in proj.bullets:
            if bullet.status not in _ALLOWED_BULLET_STATUSES:
                continue
            for fragment in _split_bullet_fragments(bullet.text):
                text = _clean_pdf_text(fragment)
                if _is_valid_bullet_text(text):
                    new_bullet = copy.deepcopy(bullet)
                    new_bullet.text = text
                    valid_proj_bullets.append(new_bullet)
        description = _clean_pdf_text(proj.description)
        if valid_proj_bullets or _is_valid_bullet_text(description):
            proj.bullets = valid_proj_bullets
            proj.description = description
            cleaned_projects.append(proj)

    rec.projects = cleaned_projects

    rec.skills = sanitize_resume_skill_groups(rec.skills)
    rec.achievements = [
        item for item in rec.achievements
        if item.included and _is_valid_bullet_text(_clean_pdf_text(item.title))
    ]
    rec.awards = [
        item for item in rec.awards
        if item.included and _is_valid_bullet_text(_clean_pdf_text(item.title))
    ]
    rec.custom_sections = [
        section for section in rec.custom_sections
        if section.included and _is_valid_bullet_text(_clean_pdf_text(section.title))
        and _clean_inline_values(section.items)
    ]

    return rec


def get_section_order(is_fresher: bool) -> list[str]:
    """
    Return recommended visible section order.

    Freshers lead with education/projects; experienced candidates lead with
    track record.
    """
    if is_fresher:
        return [
            "contact",
            "target_title",
            "summary",
            "education",
            "skills",
            "projects",
            "experience",
            "achievements",
            "certifications",
        ]
    return [
        "contact",
        "target_title",
        "summary",
        "experience",
        "projects",
        "skills",
        "education",
        "achievements",
        "certifications",
    ]


def render_latex(recommendation: ResumeRecommendation, *, is_fresher: bool = False) -> str:
    """
    Render the resume recommendation into LaTeX source code using the fixed template.

    Returns:
        LaTeX source string ready for PDF compilation.
    """
    recommendation = validate_resume_for_export(recommendation).recommendation
    recommendation = sanitize_recommendation(recommendation)
    assert_resume_recommendation_safe(recommendation)
    assert_render_text_safe(
        recommendation_to_plain_text(recommendation),
        artifact="recommendation_plain_text",
    )
    settings = get_settings()
    template_dir = Path(settings.LATEX_TEMPLATE_DIR)
    context = _build_template_context(recommendation, is_fresher=is_fresher)

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
    )
    template = env.get_template(CANONICAL_LATEX_TEMPLATE)
    latex_source = template.render(**context)
    validate_latex_for_export(latex_source)
    assert_render_text_safe(latex_source, artifact="latex_source")

    logger.info("[%s] LaTeX rendered (%s chars)", recommendation.generation_id, len(latex_source))
    return latex_source


def _repair_mojibake(value: str) -> str:
    for bad, replacement in _MOJIBAKE_REPLACEMENTS.items():
        value = value.replace(bad, replacement)
    if not any(marker in value for marker in ("\u00c3", "\u00c2", "\u00e2", "\u0088")):
        return value
    try:
        repaired = value.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
    except UnicodeError:
        return value
    return repaired or value


def _normalize_pdf_text(value: str | None) -> str:
    text = normalize_unicode_for_resume_export(_repair_mojibake(value or ""))
    text = text.replace("\\u0088", " ")
    text = text.replace("\u0088", " ")
    text = _CONTROL_CHAR_RE.sub(" ", text)
    return text


def _split_bullet_fragments(value: str | None) -> list[str]:
    text = _normalize_pdf_text(value)
    parts = [part.strip() for part in _BULLET_SPLIT_RE.split(text)]
    return [part for part in parts if part] or [text]


def _clean_pdf_text(value: str | None) -> str:
    text = _normalize_pdf_text(value)
    text = _BULLET_GLYPH_RE.sub(" ", text)

    previous = None
    while previous != text:
        previous = text
        text = _LEADING_BULLET_RE.sub("", text)

    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n-*#;:^")


def _is_valid_bullet_text(text: str) -> bool:
    if not text:
        return False
    if _SYMBOL_ONLY_RE.fullmatch(text):
        return False
    return bool(re.search(r"[A-Za-z0-9]", text))


def _clean_bullet_texts(bullets) -> list[str]:
    cleaned: list[str] = []
    for bullet in bullets:
        if bullet.status not in _ALLOWED_BULLET_STATUSES:
            continue
        for fragment in _split_bullet_fragments(bullet.text):
            text = _clean_pdf_text(fragment)
            if _is_valid_bullet_text(text):
                cleaned.append(escape_latex(text))
    return cleaned


def _clean_inline_values(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = _clean_pdf_text(value)
        if _is_valid_bullet_text(text):
            cleaned.append(escape_latex(text))
    return cleaned


def _build_template_context(rec: ResumeRecommendation, *, is_fresher: bool = False) -> dict:
    """Build the Jinja2 context for the LaTeX template, with all values escaped."""
    experiences = []
    for exp in rec.experience:
        if not exp.included:
            continue
        bullets = _clean_bullet_texts(exp.bullets)
        if not bullets:
            continue
        experiences.append({
            "title": escape_latex(exp.title),
            "company": escape_latex(exp.company),
            "location": escape_latex(exp.location or ""),
            "date_range": escape_latex(_date_range(exp.start_date, exp.end_date or "Present")),
            "bullets": bullets,
        })

    education = []
    for edu in rec.education:
        if not edu.included:
            continue
        education.append({
            "institution": escape_latex(edu.institution),
            "location": "",
            "degree_line": escape_latex(
                edu.degree + (f", {edu.field_of_study}" if edu.field_of_study else "")
            ),
            "date_range": escape_latex(_date_range(edu.start_date, edu.end_date)),
            "detail_line": escape_latex(
                " | ".join(part for part in [f"GPA: {edu.gpa}" if edu.gpa else "", edu.honors or ""] if part)
            ),
            "coursework": _clean_inline_values(edu.relevant_coursework),
        })

    skills = []
    for sg in rec.skills:
        clean_skills = _clean_inline_values(sg.skills)
        if clean_skills:
            skills.append({
                "category": escape_latex(sg.category),
                "skills": ", ".join(clean_skills),
            })

    projects = []
    for proj in rec.projects:
        if not proj.included:
            continue
        proj_bullets = _clean_bullet_texts(proj.bullets)
        if not proj_bullets and proj.description:
            description = _clean_pdf_text(proj.description)
            if _is_valid_bullet_text(description):
                proj_bullets = [escape_latex(description)]
        if not proj_bullets:
            continue
        projects.append({
            "name": escape_latex(proj.name),
            "technologies": ", ".join(_clean_inline_values(proj.technologies)),
            "bullets": proj_bullets,
        })

    certifications = []
    for cert in rec.certifications:
        if not cert.included:
            continue
        certifications.append({
            "name": escape_latex(cert.name),
            "issuer": escape_latex(cert.issuing_org or ""),
            "date": escape_latex(cert.date or ""),
        })

    achievements = []
    for item in [*rec.achievements, *rec.awards]:
        if not item.included:
            continue
        title = _clean_pdf_text(item.title)
        if not _is_valid_bullet_text(title):
            continue
        achievements.append({
            "title": escape_latex(title),
            "issuer": escape_latex(item.issuer or ""),
            "date": escape_latex(item.date or ""),
            "description": escape_latex(_clean_pdf_text(item.description or "")),
        })

    custom_sections = []
    for section in rec.custom_sections:
        items = _clean_inline_values(section.items)
        if section.included and items:
            custom_sections.append({
                "title": escape_latex(_clean_pdf_text(section.title)),
                "items": items,
            })

    section_order = _canonical_section_order(
        get_section_order(is_fresher) if is_fresher else rec.section_order,
        is_fresher=is_fresher,
    )

    return {
        "contact_name": escape_latex(rec.contact.full_name) if rec.contact else "",
        "contact_email": escape_latex(rec.contact.email) if rec.contact else "",
        "contact_phone": escape_latex(rec.contact.phone or "") if rec.contact else "",
        "contact_location": escape_latex(rec.contact.location or "") if rec.contact else "",
        "contact_linkedin": sanitize_latex_url(rec.contact.linkedin_url or "") if rec.contact else "",
        "contact_github": sanitize_latex_url(rec.contact.github_url or "") if rec.contact else "",
        "contact_portfolio": sanitize_latex_url(rec.contact.portfolio_url or "") if rec.contact else "",
        "summary": escape_latex(_clean_pdf_text(rec.summary)) if rec.summary and _is_valid_bullet_text(_clean_pdf_text(rec.summary)) else "",
        "target_title": escape_latex(_clean_pdf_text(rec.target_title)),
        "experiences": experiences,
        "education": education,
        "skills": skills,
        "projects": projects,
        "certifications": certifications,
        "achievements": achievements,
        "custom_sections": custom_sections,
        "section_order_list": section_order,
    }


def _canonical_section_order(section_order: list[str], *, is_fresher: bool = False) -> list[str]:
    """Collapse legacy aliases into the single canonical main.tex section list."""
    raw_order = section_order if section_order else get_section_order(is_fresher)
    aliases = {
        "technical skills": "skills",
        "skill": "skills",
        "awards": "achievements",
        "awards & achievements": "achievements",
    }
    canonical: list[str] = []
    for section in raw_order:
        key = aliases.get(section.strip().lower(), section.strip().lower())
        if key in {"contact", "target_title"} or key in canonical:
            continue
        canonical.append(key)

    required = [
        section
        for section in get_section_order(is_fresher)
        if section not in {"contact", "target_title"}
    ]
    for section in required:
        if section not in canonical:
            canonical.append(section)
    return canonical


def _date_range(start_date: str | None, end_date: str | None) -> str:
    return " to ".join(part for part in [start_date or "", end_date or ""] if part)
