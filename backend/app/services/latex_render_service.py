"""
LaTeX render service — maps resume recommendation data to the fixed LaTeX template.
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.config import get_settings
from app.schemas.resume import ResumeRecommendation, BulletStatus
from app.utils.latex_escape import escape_latex, sanitize_latex_url

logger = logging.getLogger(__name__)


def render_latex(recommendation: ResumeRecommendation) -> str:
    """
    Render the resume recommendation into LaTeX source code using the fixed template.

    Returns:
        LaTeX source string ready for PDF compilation.
    """
    settings = get_settings()
    template_dir = Path(settings.LATEX_TEMPLATE_DIR)

    # Prepare template context with escaped values
    context = _build_template_context(recommendation)

    # Load and render Jinja2 LaTeX template
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,  # We handle escaping manually for LaTeX
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
    )
    template = env.get_template("resume_template.tex")
    latex_source = template.render(**context)

    logger.info(f"[{recommendation.session_id}] LaTeX rendered ({len(latex_source)} chars)")
    return latex_source


def _build_template_context(rec: ResumeRecommendation) -> dict:
    """Build the Jinja2 context for the LaTeX template, with all values escaped."""
    # Only include accepted/edited/locked bullets, not rejected
    def filter_bullets(bullets):
        return [
            b for b in bullets
            if b.status in (BulletStatus.ACCEPTED, BulletStatus.EDITED, BulletStatus.LOCKED, BulletStatus.PENDING)
        ]

    experiences = []
    for exp in rec.experience:
        if not exp.included:
            continue
        experiences.append({
            "title": escape_latex(exp.title),
            "company_line": escape_latex(exp.company + (f" | {exp.location}" if exp.location else "")),
            "date_range": escape_latex(f"{exp.start_date} -- {exp.end_date or 'Present'}"),
            "bullets": [escape_latex(b.text) for b in filter_bullets(exp.bullets)],
        })

    education = []
    for edu in rec.education:
        if not edu.included:
            continue
        education.append({
            "institution": escape_latex(edu.institution),
            "degree_line": escape_latex(
                edu.degree + (f", {edu.field_of_study}" if edu.field_of_study else "")
            ),
            "date_range": escape_latex(
                " -- ".join(part for part in [edu.start_date or "", edu.end_date or ""] if part)
            ),
            "detail_line": escape_latex(
                " | ".join(part for part in [f"GPA: {edu.gpa}" if edu.gpa else "", edu.honors or ""] if part)
            ),
            "coursework": [escape_latex(c) for c in edu.relevant_coursework],
        })

    skills = []
    for sg in rec.skills:
        skills.append({
            "category": escape_latex(sg.category),
            "skills": ", ".join(escape_latex(s) for s in sg.skills),
        })

    projects = []
    for proj in rec.projects:
        if not proj.included:
            continue
        projects.append({
            "name": escape_latex(proj.name),
            "technologies": ", ".join(escape_latex(t) for t in proj.technologies),
            "bullets": [escape_latex(b.text) for b in filter_bullets(proj.bullets)],
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

    return {
        # Contact info for header
        "contact_name": escape_latex(rec.contact.full_name) if rec.contact else "",
        "contact_email": escape_latex(rec.contact.email) if rec.contact else "",
        "contact_phone": escape_latex(rec.contact.phone or "") if rec.contact else "",
        "contact_location": escape_latex(rec.contact.location or "") if rec.contact else "",
        "contact_linkedin": sanitize_latex_url(rec.contact.linkedin_url or "") if rec.contact else "",
        "contact_github": sanitize_latex_url(rec.contact.github_url or "") if rec.contact else "",
        "contact_portfolio": sanitize_latex_url(rec.contact.portfolio_url or "") if rec.contact else "",
        # Resume content
        "summary": escape_latex(rec.summary or ""),
        "target_title": escape_latex(rec.target_title),
        "experiences": experiences,
        "education": education,
        "skills": skills,
        "projects": projects,
        "certifications": certifications,
    }
