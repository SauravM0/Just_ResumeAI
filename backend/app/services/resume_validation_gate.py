"""
Deterministic resume validation and repair gate.

The gate is intentionally LLM-independent. Draft mode returns the best editable
resume with warnings. Export mode raises on unresolved fatal issues so bad
content cannot silently become a PDF/DOCX/LaTeX artifact.
"""

from __future__ import annotations

import re
import logging
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import (
    BulletStatus,
    ResumeAchievementEntry,
    ResumeBullet,
    ResumeCertEntry,
    ResumeCustomSection,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeProjectEntry,
    ResumeRecommendation,
    ResumeSkillGroup,
)
from app.schemas.validation import ValidationSeverity, ValidationStatus
from app.services.candidate_timeline_service import downgrade_target_title
from app.services.locked_fields_service import LockedFields, validate_locked_fields_in_output
from app.services.skill_taxonomy_service import sanitize_resume_skill_groups
from app.services.bullet_quality_service import (
    check_repeated_structures,
    has_jd_boilerplate,
    repair_incomplete_bullet,
    validate_single_bullet,
)
from app.utils.latex_escape import normalize_unicode_for_resume_export, strip_latex_commands

logger = logging.getLogger(__name__)


class ResumeValidationMode(str, Enum):
    DRAFT = "draft_mode"
    EXPORT = "export_mode"


class ResumeValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ResumeValidationIssue(BaseModel):
    code: str
    message: str
    severity: ResumeValidationSeverity = ResumeValidationSeverity.WARNING
    path: str = Field(default="", description="Dotted path to the affected resume field.")
    repaired: bool = False
    blocks_export: bool = False


class ResumeValidationGateResult(BaseModel):
    mode: ResumeValidationMode
    recommendation: ResumeRecommendation
    issues: list[ResumeValidationIssue] = Field(default_factory=list)
    repaired: bool = False
    draft_ready: bool = True
    export_ready: bool = False

    @property
    def can_proceed(self) -> bool:
        return self.export_ready if self.mode == ResumeValidationMode.EXPORT else self.draft_ready

    @property
    def errors(self) -> list[ResumeValidationIssue]:
        return [issue for issue in self.issues if issue.severity == ResumeValidationSeverity.ERROR]

    @property
    def warnings(self) -> list[ResumeValidationIssue]:
        return [issue for issue in self.issues if issue.severity == ResumeValidationSeverity.WARNING]


class ResumeValidationError(RuntimeError):
    """Raised when export-mode validation finds unresolved fatal issues."""

    def __init__(self, issues: list[ResumeValidationIssue]):
        self.issues = issues
        message = "Resume export blocked by validation gate."
        if issues:
            message = f"{message} {issues[0].message}"
        super().__init__(message)


_ModeInput = ResumeValidationMode | Literal["draft", "export", "draft_mode", "export_mode"]

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_INVISIBLE_EXPORT_CHAR_RE = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_PRIVATE_USE_CHAR_RE = re.compile(r"[\ue000-\uf8ff]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LEADING_BULLET_RE = re.compile(
    r"^(?:\s*(?:\\item\b|\\resumeItem\s*|\(?[a-z0-9]+\)|[0-9]+[.)]|[-*+.^]+|[\u2022\u25cf\u25aa\u25a0\u00b7])\s*)+",
    re.IGNORECASE,
)
_SYMBOL_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*", re.IGNORECASE)
_TERMINAL_RE = re.compile(r"[.!?]$")
_CONNECTOR_END_RE = re.compile(r"\b(?:to|in|in a|using|with|for|by|through|via|and|or)\.?$", re.IGNORECASE)
_CONTAMINATION_RE = re.compile(
    r"\b(?:invalid job description content|job description content|we are seeking|the ideal candidate|ideal candidate|responsibilities include|equal opportunity employer|equal opportunity|apply now|job description|about us)\b",
    re.IGNORECASE,
)
_RAW_METADATA_RE = re.compile(r"\b(?:ats keywords|tags|metadata|job id|ref id)\s*:", re.IGNORECASE)
_KNOWN_HYPHEN_SKILLS = {"ci-cd", "ci/cd", "end-to-end", "full-stack", "front-end", "back-end"}
_URL_SLUG_RE = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+){3,}\b", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:n/?a|na|none|null|tbd|todo|placeholder|untitled role|resume candidate)\s*$",
    re.IGNORECASE,
)
_CORRUPTED_TEXT_RE = re.compile(r"(?:\ufffd|â|Ã|Â|�|\\u00(?:8[0-9a-f]|9[0-9a-f]))", re.IGNORECASE)
_CORRUPTED_DATE_SEPARATOR_RE = re.compile(r"(?:â|Ã|Â|�|–|—|\\u201[34])")
_ACTION_VERBS = {
    "achieved", "administered", "analyzed", "architected", "automated", "built", "collaborated",
    "configured", "created", "delivered", "deployed", "designed", "developed", "diagnosed", "drove",
    "enhanced", "implemented", "improved", "integrated", "led", "managed", "migrated",
    "optimized", "reduced", "resolved", "shipped", "streamlined", "tested", "validated",
}
_SENIORITY_TERMS = {"senior", "sr", "lead", "principal", "staff", "manager", "architect"}
_JUNIOR_TERMS = {"intern", "trainee", "junior", "fresher", "student", "entry"}
_SKILL_CATEGORY_MAP = {
    "python": "Programming Languages",
    "java": "Programming Languages",
    "javascript": "Programming Languages",
    "typescript": "Programming Languages",
    "c++": "Programming Languages",
    "c#": "Programming Languages",
    "sql": "Programming Languages",
    "react": "Frontend Frameworks",
    "react.js": "Frontend Frameworks",
    "node.js": "Backend Frameworks",
    "nodejs": "Backend Frameworks",
    "fastapi": "Backend Frameworks",
    "django": "Backend Frameworks",
    "flask": "Backend Frameworks",
    "postgresql": "Databases",
    "mysql": "Databases",
    "mongodb": "Databases",
    "docker": "Cloud & DevOps",
    "kubernetes": "Cloud & DevOps",
    "aws": "Cloud & DevOps",
    "azure": "Cloud & DevOps",
    "gcp": "Cloud & DevOps",
    "git": "Tools",
    "jira": "Tools",
    "postman": "Tools",
    "ms word": "Tools",
    "microsoft word": "Tools",
    "word": "Tools",
    "excel": "Tools",
    "ms excel": "Tools",
    "powerpoint": "Tools",
    "ms powerpoint": "Tools",
    "rag": "AI/ML",
    "llm": "AI/ML",
    "machine learning": "AI/ML",
}


def validate_resume_gate(
    recommendation: ResumeRecommendation,
    mode: _ModeInput = ResumeValidationMode.DRAFT,
    *,
    parsed_jd: ParsedJD | None = None,
    profile: MasterProfile | None = None,
    repair: bool = True,
    locked: LockedFields | None = None,
) -> ResumeValidationGateResult:
    validation_mode = _normalize_mode(mode)
    issues: list[ResumeValidationIssue] = []
    rec = recommendation.model_copy(deep=True)
    locked = _coerce_locked_fields(locked, rec)

    _repair_top_level_text(rec, issues)
    rec.skills = _repair_skills(rec.skills, issues)
    _validate_skill_categories(rec, issues)
    rec.experience = _repair_experience(rec.experience, validation_mode, repair, issues)
    rec.projects = _repair_projects(rec.projects, validation_mode, repair, issues)
    rec.education = _repair_education(rec.education, issues)
    rec.certifications = _repair_certifications(rec.certifications, issues)
    rec.achievements = _repair_achievements(rec.achievements, "achievements", issues)
    rec.awards = _repair_achievements(rec.awards, "awards", issues)
    rec.custom_sections = _repair_custom_sections(rec.custom_sections, issues)
    rec.section_order = _canonical_section_order(rec.section_order, issues)

    _validate_printable_fields(rec, validation_mode, issues)
    _validate_title(rec, profile, validation_mode, repair, issues)
    _validate_unsupported_claims(rec, parsed_jd, profile, validation_mode, issues)
    _validate_locked_fields(rec, locked, issues)
    _validate_required_fields(rec, validation_mode, issues)

    warning_text = [
        f"{issue.message} ({issue.path})".strip()
        for issue in issues
        if issue.severity != ResumeValidationSeverity.INFO
    ]
    rec.warnings = _dedupe_strings([*rec.warnings, *warning_text])

    repaired = any(issue.repaired for issue in issues)
    export_ready = not any(issue.blocks_export for issue in issues)
    result = ResumeValidationGateResult(
        mode=validation_mode,
        recommendation=rec,
        issues=issues,
        repaired=repaired,
        draft_ready=True,
        export_ready=export_ready,
    )
    if validation_mode == ResumeValidationMode.EXPORT and not result.export_ready:
        raise ResumeValidationError([issue for issue in issues if issue.blocks_export])
    return result


def build_validation_status(
    result: ResumeValidationGateResult,
    *,
    additional_warnings: list[str] | None = None,
    additional_repair_actions: list[str] | None = None,
    additional_user_actions: list[str] | None = None,
) -> ValidationStatus:
    """
    Convert a ResumeValidationGateResult into the standard ValidationStatus.
    """
    blocked_reasons: list[str] = []
    warnings: list[str] = list(additional_warnings or [])
    repair_actions: list[str] = list(additional_repair_actions or [])
    user_actions: list[str] = list(additional_user_actions or [])

    for issue in result.issues:
        text = f"{issue.path}: {issue.message}" if issue.path else issue.message
        
        if issue.blocks_export:
            blocked_reasons.append(text)
        else:
            warnings.append(text)
            
        if issue.repaired:
            if "removed" in issue.code.lower():
                repair_actions.append(f"Removed: {issue.message}")
            else:
                repair_actions.append(f"Fixed: {issue.message}")
        
        # Mapping specific codes to user actions
        if issue.code == "untraceable_claim":
            user_actions.append(f"Review bullet accuracy: {issue.path}")
        elif issue.code == "metric_hallucination":
            user_actions.append(f"Verify metric source or remove: {issue.path}")
        elif issue.code in ("thin_bullet", "missing_action_verb", "missing_object_or_result"):
            user_actions.append(f"Strengthen bullet phrasing: {issue.path}")

    # Fallback for errors that didn't mark blocks_export
    if not result.export_ready and not blocked_reasons:
        for issue in result.issues:
            if issue.severity == ResumeValidationSeverity.ERROR:
                blocked_reasons.append(f"{issue.path}: {issue.message}" if issue.path else issue.message)

    if blocked_reasons:
        severity = ValidationSeverity.BLOCKED
    elif warnings:
        severity = ValidationSeverity.WARNING
    else:
        severity = ValidationSeverity.PASS

    return ValidationStatus(
        export_ready=result.export_ready,
        severity=severity,
        blocked_reasons=_dedupe_strings(blocked_reasons),
        warnings=_dedupe_strings(warnings),
        repair_actions=_dedupe_strings(repair_actions),
        user_actions=_dedupe_strings(user_actions),
    )


def validate_resume_for_mode(
    recommendation: ResumeRecommendation,
    *,
    parsed_jd: ParsedJD | None = None,
    profile: MasterProfile | None = None,
    mode: _ModeInput = ResumeValidationMode.DRAFT,
    repair: bool = True,
    locked: LockedFields | None = None,
) -> ResumeValidationGateResult:
    return validate_resume_gate(
        recommendation,
        mode=mode,
        parsed_jd=parsed_jd,
        profile=profile,
        repair=repair,
        locked=locked,
    )


def validate_resume_for_draft(
    recommendation: ResumeRecommendation,
    *,
    parsed_jd: ParsedJD | None = None,
    profile: MasterProfile | None = None,
    locked: LockedFields | None = None,
) -> ResumeValidationGateResult:
    return validate_resume_gate(
        recommendation,
        ResumeValidationMode.DRAFT,
        parsed_jd=parsed_jd,
        profile=profile,
        repair=True,
        locked=locked,
    )


def validate_resume_for_export(
    recommendation: ResumeRecommendation,
    *,
    parsed_jd: ParsedJD | None = None,
    profile: MasterProfile | None = None,
    locked: LockedFields | None = None,
) -> ResumeValidationGateResult:
    return validate_resume_gate(
        recommendation,
        ResumeValidationMode.EXPORT,
        parsed_jd=parsed_jd,
        profile=profile,
        repair=True,
        locked=locked,
    )


def latex_to_plain_text(latex_source: str) -> str:
    """Return a best-effort text view of rendered LaTeX for export checks."""
    text = strip_latex_commands(latex_source or "")
    text = re.sub(r"(?m)^\s*%.*$", " ", text)
    text = re.sub(r"[{}$&_^~]+", " ", text)
    return _clean_text(text)


def validate_latex_for_export(latex_source: str) -> str:
    """Block generated LaTeX or extracted text that is unsafe to export."""
    issues: list[ResumeValidationIssue] = []
    _validate_render_text(latex_source, "latex_source", issues)
    plain_text = latex_to_plain_text(latex_source)
    _validate_render_text(plain_text, "latex_plain_text", issues)
    if issues:
        raise ResumeValidationError(issues)
    return plain_text


def validate_plain_text_for_export(text: str, *, artifact: str) -> None:
    """Block final extracted export text that is unsafe to download."""
    issues: list[ResumeValidationIssue] = []
    _validate_render_text(text or "", artifact, issues)
    if issues:
        raise ResumeValidationError(issues)


def validate_pdf_text_parseability(recommendation: ResumeRecommendation, text: str) -> None:
    """Block PDF export if ATS-critical structured fields did not survive extraction."""
    issues: list[ResumeValidationIssue] = []
    validate_plain_text_for_export(text, artifact="pdf_text")
    normalized_text = _normalized_pdf_match_text(text)

    _require_pdf_text(normalized_text, recommendation.contact.full_name, "pdf_missing_contact_name", "Extracted PDF text is missing the candidate name.", "pdf_text.contact.full_name", issues)
    _require_pdf_text(normalized_text, recommendation.target_title, "pdf_missing_target_title", "Extracted PDF text is missing the resume title.", "pdf_text.target_title", issues)
    _require_pdf_text(normalized_text, recommendation.contact.email, "pdf_missing_contact_email", "Extracted PDF text is missing the contact email.", "pdf_text.contact.email", issues)
    if recommendation.contact.phone:
        _require_pdf_text(normalized_text, recommendation.contact.phone, "pdf_missing_contact_phone", "Extracted PDF text is missing the contact phone.", "pdf_text.contact.phone", issues)

    for heading in _expected_pdf_section_headings(recommendation):
        _require_pdf_text(
            normalized_text,
            heading,
            "pdf_missing_section_heading",
            f"Extracted PDF text is missing the {heading} section heading.",
            f"pdf_text.sections.{_key(heading).replace(' ', '_')}",
            issues,
        )

    for path, date_range in _expected_pdf_date_ranges(recommendation):
        _require_pdf_text(
            normalized_text,
            date_range,
            "pdf_unreadable_date_range",
            f"Extracted PDF text is missing readable date text for {path}.",
            f"pdf_text.{path}",
            issues,
        )

    if issues:
        raise ResumeValidationError(issues)


def _normalized_pdf_match_text(value: str | None) -> str:
    normalized = normalize_unicode_for_resume_export(value)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.casefold().strip()


def _require_pdf_text(
    extracted_text: str,
    expected: str | None,
    code: str,
    message: str,
    path: str,
    issues: list[ResumeValidationIssue],
) -> None:
    expected_text = _normalized_pdf_match_text(expected)
    if not expected_text:
        return
    if expected_text not in extracted_text:
        _issue(
            issues,
            code,
            message,
            path,
            severity=ResumeValidationSeverity.ERROR,
            blocks_export=True,
        )


def _expected_pdf_section_headings(rec: ResumeRecommendation) -> list[str]:
    headings: list[str] = []
    if rec.summary:
        headings.append("Summary")
    if any(group.skills for group in rec.skills):
        headings.append("Skills")
    if any(exp.included and exp.bullets for exp in rec.experience):
        headings.append("Experience")
    if any(project.included and (project.bullets or project.description) for project in rec.projects):
        headings.append("Projects")
    if any(edu.included for edu in rec.education):
        headings.append("Education")
    if any(cert.included and cert.name for cert in rec.certifications):
        headings.append("Certifications")
    if any(item.included and item.title for item in [*rec.achievements, *rec.awards]):
        headings.append("Awards & Achievements")
    headings.extend(section.title for section in rec.custom_sections if section.included and section.title and section.items)
    return headings


def _expected_pdf_date_ranges(rec: ResumeRecommendation):
    for index, exp in enumerate(rec.experience):
        if exp.included and exp.bullets:
            yield f"experience.{index}.date_range", _pdf_date_range(exp.start_date, exp.end_date or "Present")
    for index, edu in enumerate(rec.education):
        if edu.included:
            date_range = _pdf_date_range(edu.start_date, edu.end_date)
            if date_range:
                yield f"education.{index}.date_range", date_range
    for section_name, entries in (
        ("certifications", rec.certifications),
        ("achievements", rec.achievements),
        ("awards", rec.awards),
    ):
        for index, entry in enumerate(entries):
            if entry.included and entry.date:
                yield f"{section_name}.{index}.date", entry.date


def _pdf_date_range(start_date: str | None, end_date: str | None) -> str:
    return " to ".join(part for part in [start_date or "", end_date or ""] if part)


def _normalize_mode(mode: _ModeInput) -> ResumeValidationMode:
    if isinstance(mode, ResumeValidationMode):
        return mode
    value = str(mode).strip().lower()
    if value in {"draft", "draft_mode"}:
        return ResumeValidationMode.DRAFT
    if value in {"export", "export_mode"}:
        return ResumeValidationMode.EXPORT
    raise ValueError(f"Unsupported resume validation mode: {mode!r}")


def _repair_top_level_text(rec: ResumeRecommendation, issues: list[ResumeValidationIssue]) -> None:
    rec.generation_id = _repair_string(rec.generation_id, "generation_id", issues)
    rec.target_title = _repair_string(rec.target_title, "target_title", issues)
    rec.summary = _repair_optional_string(rec.summary, "summary", issues) or None
    rec.contact.full_name = _repair_string(rec.contact.full_name, "contact.full_name", issues)
    rec.contact.email = _repair_string(rec.contact.email, "contact.email", issues)
    rec.contact.phone = _repair_optional_string(rec.contact.phone, "contact.phone", issues) or None
    rec.contact.location = _repair_optional_string(rec.contact.location, "contact.location", issues) or None
    rec.contact.linkedin_url = _repair_optional_string(rec.contact.linkedin_url, "contact.linkedin_url", issues) or None
    rec.contact.github_url = _repair_optional_string(rec.contact.github_url, "contact.github_url", issues) or None
    rec.contact.portfolio_url = _repair_optional_string(rec.contact.portfolio_url, "contact.portfolio_url", issues) or None


def _repair_experience(
    entries: list[ResumeExperienceEntry],
    mode: ResumeValidationMode,
    repair: bool,
    issues: list[ResumeValidationIssue],
) -> list[ResumeExperienceEntry]:
    repaired_entries: list[ResumeExperienceEntry] = []
    seen_entries: set[str] = set()
    seen_bullets: set[str] = set()
    for index, entry in enumerate(entries):
        path = f"experience.{index}"
        if not entry.included:
            continue
        entry.company = _repair_string(entry.company, f"{path}.company", issues)
        entry.title = _repair_string(entry.title, f"{path}.title", issues)
        entry.location = _repair_optional_string(entry.location, f"{path}.location", issues) or None
        entry.start_date = _repair_date(entry.start_date, f"{path}.start_date", issues)
        entry.end_date = _repair_optional_date(entry.end_date, f"{path}.end_date", issues)
        entry_key = _key("|".join([entry.company, entry.title, entry.start_date, entry.end_date or ""]))
        if entry_key in seen_entries:
            _issue(issues, "duplicate_experience_removed", "Removed duplicate experience entry.", path, repaired=True)
            continue
        seen_entries.add(entry_key)
        entry.bullets = _repair_bullets(entry.bullets, f"{path}.bullets", seen_bullets, mode, repair, issues)
        if not entry.bullets and not _has_any_text(entry.company, entry.title):
            _issue(issues, "empty_experience_removed", "Removed empty experience entry.", path, repaired=True)
            continue
        repaired_entries.append(entry)
    return repaired_entries


def _repair_projects(
    entries: list[ResumeProjectEntry],
    mode: ResumeValidationMode,
    repair: bool,
    issues: list[ResumeValidationIssue],
) -> list[ResumeProjectEntry]:
    repaired_entries: list[ResumeProjectEntry] = []
    seen_entries: set[str] = set()
    seen_bullets: set[str] = set()
    for index, project in enumerate(entries):
        path = f"projects.{index}"
        if not project.included:
            continue
        project.name = _repair_string(project.name, f"{path}.name", issues)
        project.description = _repair_optional_string(project.description, f"{path}.description", issues) or None
        project.technologies = _dedupe_repaired_strings(project.technologies, f"{path}.technologies", issues)
        project.bullets = _repair_bullets(project.bullets, f"{path}.bullets", seen_bullets, mode, repair, issues)
        entry_key = _key(project.name)
        if entry_key in seen_entries:
            _issue(issues, "duplicate_project_removed", "Removed duplicate project entry.", path, repaired=True)
            continue
        seen_entries.add(entry_key)
        if not _has_any_text(project.name, project.description, *project.technologies) and not project.bullets:
            _issue(issues, "empty_project_removed", "Removed empty project entry.", path, repaired=True)
            continue
        repaired_entries.append(project)
    return repaired_entries


def _repair_bullets(
    bullets: list[ResumeBullet],
    path: str,
    seen_bullets: set[str],
    mode: ResumeValidationMode,
    repair: bool,
    issues: list[ResumeValidationIssue],
    *,
    evidence_text: str | None = None,
) -> list[ResumeBullet]:
    repaired_list: list[ResumeBullet] = []
    bullet_texts_for_structure: list[str] = []

    for index, bullet in enumerate(bullets):
        bullet_path = f"{path}.{index}"
        if bullet.status == BulletStatus.REJECTED:
            _issue(issues, "rejected_bullet_removed", "Removed rejected bullet.", bullet_path, repaired=True)
            continue
            
        text = _clean_bullet_text(bullet.text)
        if not _is_meaningful_text(text):
            _issue(issues, "empty_bullet_removed", "Removed empty or symbol-only bullet.", bullet_path, repaired=True)
            continue
            
        key = _key(text)
        if key in seen_bullets:
            _issue(issues, "duplicate_bullet_removed", "Removed duplicate bullet.", bullet_path, repaired=True)
            continue

        # Use bullet quality service for deep analysis + repair
        quality = validate_single_bullet(text, evidence_text=evidence_text)
        
        # JD Boilerplate/Contamination — WARNING only, never delete
        if has_jd_boilerplate(text) or any(i.code == "jd_boilerplate" for i in quality.issues):
            _issue(
                issues,
                "contaminated_bullet_warning",
                "Bullet may contain JD boilerplate or hiring language.",
                bullet_path,
                repaired=False,
                blocks_export=False,
            )

        repaired_text = quality.text
        
        # RECORD REPAIRS
        if quality.repaired:
            for qi in quality.issues:
                if qi.repaired:
                    _issue(issues, qi.code, qi.message, f"{bullet_path}.text", repaired=True)

        # CHECK FOR REMAINING ISSUES — all are warnings, never delete bullets
        bullet_issues = _bullet_issues(repaired_text, bullet_path)
        issues.extend(bullet_issues)

        # NON-BLOCKING: Weak phrasing, action verbs, etc.
        # We NO LONGER delete bullets just for being weak if they are supported.
        weak = [i for i in bullet_issues if not i.blocks_export]
        issues.extend(weak)
        
        repaired_list.append(bullet.model_copy(update={"text": repaired_text, "original_text": bullet.original_text or text}))
        seen_bullets.add(key)
        bullet_texts_for_structure.append(repaired_text)

    # Check for repeated sentence structures
    repeated_indices = check_repeated_structures(bullet_texts_for_structure)
    for rep_idx in repeated_indices:
        if rep_idx < len(repaired_list):
            _issue(
                issues,
                "repeated_structure_bullet",
                "Bullet uses a repeated sentence structure — consider rewriting for variety.",
                f"{path}.{rep_idx}",
            )

    return repaired_list


def _bullet_issues(text: str, path: str) -> list[ResumeValidationIssue]:
    """All bullet issues are warnings only — never block export or delete bullets."""
    issues: list[ResumeValidationIssue] = []
    if _CONTAMINATION_RE.search(text) or _RAW_METADATA_RE.search(text):
        _issue(
            issues,
            "jd_boilerplate_contamination",
            "Bullet contains job-description boilerplate or ATS metadata.",
            path,
            severity=ResumeValidationSeverity.WARNING,
            blocks_export=False,
        )
    if "ajax-asynchronous-javascript-and-xml" in text.casefold() or _has_unknown_hyphen_slug(text):
        _issue(
            issues,
            "url_slug_fragment",
            "Bullet contains URL slug fragments.",
            path,
            severity=ResumeValidationSeverity.WARNING,
            blocks_export=False,
        )
    words = _meaningful_words(text)
    if len(words) < 5:
        _issue(issues, "thin_bullet", "Bullet is too short to be meaningful.", path)
    if _CONNECTOR_END_RE.search(text):
        _issue(issues, "truncated_connector", "Bullet ends with a dangling connector.", path)
    if not _TERMINAL_RE.search(text):
        _issue(issues, "missing_terminal_punctuation", "Bullet needs terminal punctuation.", path)
    if not any(word.casefold() in _ACTION_VERBS for word in words[:4]):
        _issue(issues, "missing_action_verb", "Bullet needs an action verb.", path)
    if len(words) >= 5 and not _has_object_or_result(text):
        _issue(issues, "missing_object_or_result", "Bullet needs an object or result.", path)
    if _looks_like_keyword_list(text):
        _issue(
            issues,
            "keyword_list_bullet",
            "Bullet is a keyword list rather than an accomplishment.",
            path,
            severity=ResumeValidationSeverity.WARNING,
            blocks_export=False,
        )
    return issues


def _repair_truncated_bullet(text: str) -> str:
    # Use the quality service's more comprehensive repair
    return repair_incomplete_bullet(text, evidence_text=None)


def _repair_skills(groups: list[ResumeSkillGroup], issues: list[ResumeValidationIssue]) -> list[ResumeSkillGroup]:
    repaired_groups: list[ResumeSkillGroup] = []
    seen_categories: dict[str, ResumeSkillGroup] = {}
    for index, group in enumerate(groups):
        path = f"skills.{index}"
        category = _repair_string(group.category, f"{path}.category", issues) or "Skills"
        skills = _dedupe_repaired_strings(group.skills, f"{path}.skills", issues)
        safe_skills = [skill for skill in skills if not _skill_is_contaminated(skill, f"{path}.skills", issues)]
        if not safe_skills:
            _issue(issues, "empty_skill_group_removed", "Removed empty skill group.", path, repaired=True)
            continue
        category_key = _key(category)
        if category_key in seen_categories:
            existing = seen_categories[category_key]
            existing.skills = _dedupe_strings([*existing.skills, *safe_skills])
            _issue(issues, "duplicate_skill_group_merged", "Merged duplicate skill group.", path, repaired=True)
            continue
        repaired = group.model_copy(update={"category": category, "skills": safe_skills})
        seen_categories[category_key] = repaired
        repaired_groups.append(repaired)
    sanitized = sanitize_resume_skill_groups(repaired_groups)
    if sanitized != repaired_groups:
        _issue(issues, "skill_taxonomy_sanitized", "Sanitized skill groups with recruiter-safe taxonomy.", "skills", repaired=True)
    return sanitized


def _validate_skill_categories(rec: ResumeRecommendation, issues: list[ResumeValidationIssue]) -> None:
    bucketed: dict[str, list[str]] = {}
    changed = False
    for group in rec.skills:
        for skill in group.skills:
            expected = _expected_category(skill) or group.category
            if expected != group.category and _expected_category(skill):
                changed = True
                _issue(
                    issues,
                    "invalid_skill_category_repaired",
                    f"Moved {skill} to {expected}.",
                    "skills",
                    repaired=True,
                )
            bucketed.setdefault(expected, []).append(skill)
    if not changed:
        return
    rec.skills = [
        ResumeSkillGroup(category=category, skills=_dedupe_strings(skills))
        for category, skills in bucketed.items()
        if skills
    ]


def _validate_title(
    rec: ResumeRecommendation,
    profile: MasterProfile | None,
    mode: ResumeValidationMode,
    repair: bool,
    issues: list[ResumeValidationIssue],
) -> None:
    if not _valid_title_text(rec.target_title):
        _issue(
            issues,
            "invalid_target_title",
            "Target title is empty, placeholder text, or contaminated.",
            "target_title",
            severity=ResumeValidationSeverity.ERROR if mode == ResumeValidationMode.EXPORT else ResumeValidationSeverity.WARNING,
            blocks_export=True,
        )
        return
    title = rec.target_title.casefold()
    if not any(term in title.split() for term in _SENIORITY_TERMS):
        return
    profile_text = _profile_corpus(profile)
    has_junior_signal = any(term in profile_text for term in _JUNIOR_TERMS)
    has_senior_signal = any(term in profile_text for term in _SENIORITY_TERMS)
    if profile and has_junior_signal and not has_senior_signal:
        downgraded = downgrade_target_title(rec.target_title)
        if repair and downgraded != rec.target_title:
            rec.target_title = downgraded
            _issue(
                issues,
                "unsupported_seniority_title_repaired",
                "Downgraded unsupported seniority in target title.",
                "target_title",
                repaired=True,
            )
            return
        _issue(
            issues,
            "unsupported_seniority_title",
            "Target title asserts unsupported seniority for the profile.",
            "target_title",
            severity=ResumeValidationSeverity.ERROR if mode == ResumeValidationMode.EXPORT else ResumeValidationSeverity.WARNING,
            blocks_export=True,
        )


def _validate_unsupported_claims(
    rec: ResumeRecommendation,
    parsed_jd: ParsedJD | None,
    profile: MasterProfile | None,
    mode: ResumeValidationMode,
    issues: list[ResumeValidationIssue],
) -> None:
    if not profile:
        return
        
    from app.services.candidate_evidence_service import build_candidate_evidence, trace_claim, classify_jd_keyword_truth
    evidence_graph = build_candidate_evidence(profile)
    
    # Check for hard skill hallucinations (tools/languages in JD but not in profile)
    if parsed_jd:
        truth = classify_jd_keyword_truth(parsed_jd, evidence_graph)
        unsupported_jd_terms = set(truth.unsupported)
        
        for path, text in _iter_bullet_text(rec):
            for term in unsupported_jd_terms:
                if _contains(text, term) and _is_hard_skill(term):
                    _issue(
                        issues,
                        "unsupported_hard_skill_claim",
                        f"Bullet claims JD skill not found in your profile: {term}. Delete or move to Learning Focus.",
                        path,
                        severity=ResumeValidationSeverity.ERROR if mode == ResumeValidationMode.EXPORT else ResumeValidationSeverity.WARNING,
                        blocks_export=True,
                    )

    # Trace every bullet back to evidence to detect hallucinations
    for path, text in _iter_bullet_text(rec):
        source_id = None
        if "experience." in path:
            try:
                idx = int(path.split(".")[1])
                source_id = rec.experience[idx].source_id
            except: pass
        elif "projects." in path:
            try:
                idx = int(path.split(".")[1])
                source_id = rec.projects[idx].source_id
            except: pass
            
        # Full traceability check
        if not trace_claim(text, evidence_graph, source_id=source_id):
            # Special case for metrics
            if _has_metric(text):
                 _issue(
                    issues,
                    "metric_hallucination",
                    "Metric detected in bullet with low traceability to your profile evidence. Review for accuracy.",
                    path,
                    severity=ResumeValidationSeverity.WARNING,
                    blocks_export=False,
                )
            else:
                _issue(
                    issues,
                    "untraceable_claim",
                    "Bullet claim has low traceability to your profile evidence. Review for accuracy.",
                    path,
                    severity=ResumeValidationSeverity.WARNING,
                    blocks_export=False,
                )


def _has_metric(text: str) -> bool:
    return bool(re.search(r"\d+%|\b\d+\s*(?:percent|million|billion|users|customers|revenue|increase|reduction|improvement|ms|seconds|minutes|hours)\b", text, re.IGNORECASE))


def _repair_education(entries: list[ResumeEducationEntry], issues: list[ResumeValidationIssue]) -> list[ResumeEducationEntry]:
    repaired: list[ResumeEducationEntry] = []
    seen: set[str] = set()
    for index, edu in enumerate(entries):
        path = f"education.{index}"
        if not edu.included:
            continue
        edu.institution = _repair_string(edu.institution, f"{path}.institution", issues)
        edu.degree = _repair_string(edu.degree, f"{path}.degree", issues)
        edu.field_of_study = _repair_optional_string(edu.field_of_study, f"{path}.field_of_study", issues) or None
        edu.start_date = _repair_optional_date(edu.start_date, f"{path}.start_date", issues)
        edu.end_date = _repair_optional_date(edu.end_date, f"{path}.end_date", issues)
        edu.gpa = _repair_optional_string(edu.gpa, f"{path}.gpa", issues) or None
        edu.honors = _repair_optional_string(edu.honors, f"{path}.honors", issues) or None
        edu.relevant_coursework = _dedupe_repaired_strings(edu.relevant_coursework, f"{path}.relevant_coursework", issues)
        key = _key("|".join([edu.institution, edu.degree, edu.field_of_study or ""]))
        if key in seen:
            _issue(issues, "duplicate_education_removed", "Removed duplicate education entry.", path, repaired=True)
            continue
        seen.add(key)
        if not _has_any_text(edu.institution, edu.degree, edu.field_of_study):
            _issue(issues, "empty_education_removed", "Removed empty education entry.", path, repaired=True)
            continue
        repaired.append(edu)
    return repaired


def _repair_certifications(entries: list[ResumeCertEntry], issues: list[ResumeValidationIssue]) -> list[ResumeCertEntry]:
    repaired: list[ResumeCertEntry] = []
    seen: set[str] = set()
    for index, cert in enumerate(entries):
        path = f"certifications.{index}"
        if not cert.included:
            continue
        cert.name = _repair_string(cert.name, f"{path}.name", issues)
        cert.issuing_org = _repair_optional_string(cert.issuing_org, f"{path}.issuing_org", issues) or None
        cert.date = _repair_optional_date(cert.date, f"{path}.date", issues)
        key = _key("|".join([cert.name, cert.issuing_org or ""]))
        if key in seen:
            _issue(issues, "duplicate_certification_removed", "Removed duplicate certification.", path, repaired=True)
            continue
        seen.add(key)
        if cert.name:
            repaired.append(cert)
    return repaired


def _repair_achievements(
    entries: list[ResumeAchievementEntry],
    section: str,
    issues: list[ResumeValidationIssue],
) -> list[ResumeAchievementEntry]:
    repaired: list[ResumeAchievementEntry] = []
    seen: set[str] = set()
    for index, item in enumerate(entries):
        path = f"{section}.{index}"
        if not item.included:
            continue
        item.title = _repair_string(item.title, f"{path}.title", issues)
        item.issuer = _repair_optional_string(item.issuer, f"{path}.issuer", issues) or None
        item.description = _repair_optional_string(item.description, f"{path}.description", issues) or None
        item.date = _repair_optional_date(item.date, f"{path}.date", issues)
        key = _key("|".join([item.title, item.issuer or ""]))
        if key in seen:
            _issue(issues, f"duplicate_{section}_removed", f"Removed duplicate {section} entry.", path, repaired=True)
            continue
        seen.add(key)
        if _has_any_text(item.title, item.description):
            repaired.append(item)
    return repaired


def _repair_custom_sections(sections: list[ResumeCustomSection], issues: list[ResumeValidationIssue]) -> list[ResumeCustomSection]:
    repaired: list[ResumeCustomSection] = []
    seen: set[str] = set()
    for index, section in enumerate(sections):
        path = f"custom_sections.{index}"
        if not section.included:
            continue
        section.title = _repair_string(section.title, f"{path}.title", issues)
        section.items = _dedupe_repaired_strings(section.items, f"{path}.items", issues)
        key = _key(section.title)
        if key in seen:
            _issue(issues, "duplicate_custom_section_removed", "Removed duplicate custom section.", path, repaired=True)
            continue
        seen.add(key)
        if section.title and section.items:
            repaired.append(section)
    return repaired


def _canonical_section_order(section_order: list[str], issues: list[ResumeValidationIssue]) -> list[str]:
    canonical = ["summary", "skills", "experience", "projects", "education", "certifications", "achievements"]
    cleaned = []
    aliases = {"technical skills": "skills", "professional experience": "experience", "work experience": "experience"}
    for raw in section_order:
        section = aliases.get(_clean_text(raw).casefold(), _clean_text(raw).casefold())
        if section and section != "contact" and section not in cleaned:
            cleaned.append(section)
    for section in canonical:
        if section not in cleaned:
            cleaned.append(section)
    if cleaned != section_order:
        _issue(issues, "section_order_canonicalized", "Canonicalized section order.", "section_order", repaired=True)
    return cleaned


def _validate_required_fields(rec: ResumeRecommendation, mode: ResumeValidationMode, issues: list[ResumeValidationIssue]) -> None:
    strict = mode == ResumeValidationMode.EXPORT
    _require(bool(rec.generation_id), "missing_generation_id", "Missing generation id.", "generation_id", strict, issues)
    _require(bool(rec.target_title), "missing_target_title", "Missing resume target title.", "target_title", strict, issues)
    _require(bool(rec.contact.full_name), "missing_contact_name", "Missing contact full name.", "contact.full_name", strict, issues)
    _require(bool(rec.contact.email), "missing_contact_email", "Missing contact email.", "contact.email", strict, issues)
    if rec.contact.email and not _EMAIL_RE.match(rec.contact.email):
        _issue(issues, "invalid_contact_email", "Contact email does not look valid.", "contact.email", severity=ResumeValidationSeverity.ERROR if strict else ResumeValidationSeverity.WARNING, blocks_export=True)
    has_skills = any(group.skills for group in rec.skills)
    has_body = any(entry.bullets for entry in rec.experience) or any(project.bullets or project.description for project in rec.projects) or bool(rec.education)
    _require(has_skills, "missing_skills", "Resume has no skills section.", "skills", strict, issues)
    _require(has_body, "missing_body_section", "Resume needs experience, projects, or education content.", "", strict, issues)


def _validate_locked_fields(
    rec: ResumeRecommendation,
    locked: LockedFields | None,
    issues: list[ResumeValidationIssue],
) -> None:
    violations = validate_locked_fields_in_output(rec, locked, logger=logger)
    for violation in violations:
        _issue(
            issues,
            "locked_field_restored",
            violation,
            "locked_fields",
            repaired=True,
        )


def _coerce_locked_fields(
    locked: LockedFields | None,
    rec: ResumeRecommendation,
) -> LockedFields | None:
    if locked is not None:
        return locked
    if not rec.locked_fields:
        return None
    try:
        return LockedFields.model_validate(rec.locked_fields)
    except Exception as exc:
        logger.warning("locked_fields.invalid_audit_payload: %s", exc)
        return None


def _validate_printable_fields(
    rec: ResumeRecommendation,
    mode: ResumeValidationMode,
    issues: list[ResumeValidationIssue],
) -> None:
    strict = mode == ResumeValidationMode.EXPORT
    for path, text in _iter_printable_text(rec):
        if path == "summary" and text and _PLACEHOLDER_RE.fullmatch(text):
            _issue(
                issues,
                "summary_placeholder",
                "Summary contains placeholder text.",
                path,
                severity=ResumeValidationSeverity.ERROR if strict else ResumeValidationSeverity.WARNING,
                blocks_export=True,
            )
        if _CONTAMINATION_RE.search(text) or _RAW_METADATA_RE.search(text):
            _issue(
                issues,
                "jd_boilerplate_contamination",
                "Resume text contains job-description boilerplate or ATS metadata.",
                path,
                severity=ResumeValidationSeverity.ERROR if strict else ResumeValidationSeverity.WARNING,
                blocks_export=True,
            )
        if "ajax-asynchronous-javascript-and-xml" in text.casefold() or _has_unknown_hyphen_slug(text):
            _issue(
                issues,
                "url_slug_fragment",
                "Resume text contains raw URL slug fragments.",
                path,
                severity=ResumeValidationSeverity.ERROR if strict else ResumeValidationSeverity.WARNING,
                blocks_export=True,
            )
        if _CORRUPTED_TEXT_RE.search(text):
            _issue(
                issues,
                "invalid_unicode_text",
                "Resume text contains corrupted Unicode characters.",
                path,
                severity=ResumeValidationSeverity.ERROR if strict else ResumeValidationSeverity.WARNING,
                blocks_export=True,
            )


def _validate_render_text(text: str, path: str, issues: list[ResumeValidationIssue]) -> None:
    if _CONTAMINATION_RE.search(text) or _RAW_METADATA_RE.search(text):
        _issue(
            issues,
            "rendered_contamination",
            "Rendered export text contains job-description boilerplate or ATS metadata.",
            path,
            severity=ResumeValidationSeverity.ERROR,
            blocks_export=True,
        )
    if _CORRUPTED_TEXT_RE.search(text):
        _issue(
            issues,
            "rendered_invalid_unicode",
            "Rendered export text contains corrupted Unicode characters.",
            path,
            severity=ResumeValidationSeverity.ERROR,
            blocks_export=True,
        )
    if _CONTROL_CHAR_RE.search(text) or _INVISIBLE_EXPORT_CHAR_RE.search(text):
        _issue(
            issues,
            "rendered_hidden_characters",
            "Rendered export text contains hidden or control characters.",
            path,
            severity=ResumeValidationSeverity.ERROR,
            blocks_export=True,
        )
    if _PRIVATE_USE_CHAR_RE.search(text):
        _issue(
            issues,
            "rendered_private_use_characters",
            "Rendered export text contains icon or private-use glyph characters.",
            path,
            severity=ResumeValidationSeverity.ERROR,
            blocks_export=True,
        )


def _require(condition: bool, code: str, message: str, path: str, strict: bool, issues: list[ResumeValidationIssue]) -> None:
    if not condition:
        _issue(issues, code, message, path, severity=ResumeValidationSeverity.ERROR if strict else ResumeValidationSeverity.WARNING, blocks_export=True)


def _repair_string(value: str | None, path: str, issues: list[ResumeValidationIssue]) -> str:
    return _repair_optional_string(value, path, issues) or ""


def _repair_optional_string(value: str | None, path: str, issues: list[ResumeValidationIssue]) -> str | None:
    cleaned = _clean_text(value)
    if value is not None and cleaned != value:
        _issue(issues, "text_normalized", "Normalized whitespace or control characters.", path, repaired=True)
    return cleaned or None


def _repair_date(value: str | None, path: str, issues: list[ResumeValidationIssue]) -> str:
    return _repair_optional_date(value, path, issues) or ""


def _repair_optional_date(value: str | None, path: str, issues: list[ResumeValidationIssue]) -> str | None:
    had_date_separator = bool(
        value
        and (
            _CORRUPTED_DATE_SEPARATOR_RE.search(str(value))
            or re.search(r"[\u2010-\u2015\u2212]", str(value))
        )
    )
    cleaned = _repair_optional_string(value, path, issues)
    if cleaned and had_date_separator:
        _issue(issues, "date_separator_repaired", "Repaired corrupted date separator.", path, repaired=True)
        return cleaned
    if cleaned and _CORRUPTED_DATE_SEPARATOR_RE.search(cleaned):
        repaired = _CORRUPTED_DATE_SEPARATOR_RE.sub("-", cleaned)
        repaired = re.sub(r"\s*-\s*", "-", repaired)
        _issue(issues, "date_separator_repaired", "Repaired corrupted date separator.", path, repaired=True)
        return repaired
    return cleaned


def _dedupe_repaired_strings(values: list[str], path: str, issues: list[ResumeValidationIssue]) -> list[str]:
    cleaned = [_clean_text(value) for value in values]
    deduped = _dedupe_strings(cleaned)
    if deduped != values:
        _issue(issues, "list_normalized", "Removed empty or duplicate values.", path, repaired=True)
    return deduped


def _clean_bullet_text(value: str | None) -> str:
    cleaned = _clean_text(value)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _LEADING_BULLET_RE.sub("", cleaned)
    return cleaned.strip(" \t\r\n-*#;:")


def _clean_text(value: str | None) -> str:
    text = normalize_unicode_for_resume_export(value)
    text = _CONTROL_CHAR_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        key = _key(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _is_meaningful_text(value: str | None) -> bool:
    text = _clean_text(value)
    return bool(text and not _SYMBOL_ONLY_RE.fullmatch(text) and re.search(r"[A-Za-z0-9]", text))


def _has_any_text(*values: str | None) -> bool:
    return any(_is_meaningful_text(value) for value in values)


def _key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(value).casefold()).strip()


def _meaningful_words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def _has_object_or_result(text: str) -> bool:
    lowered = text.casefold()
    if re.search(r"\b(?:by|for|with|using|through|to|into|across|that|which|resulting|reducing|improving|increasing|supporting)\b", lowered):
        return True
    return len(_meaningful_words(text)) >= 8


def _looks_like_keyword_list(text: str) -> bool:
    words = _meaningful_words(text)
    comma_count = text.count(",")
    return comma_count >= 3 and len(words) <= comma_count + 5


def _has_unknown_hyphen_slug(text: str) -> bool:
    for match in _URL_SLUG_RE.findall(text):
        normalized = match.casefold()
        if normalized not in _KNOWN_HYPHEN_SKILLS:
            return True
    return False


def _skill_is_contaminated(skill: str, path: str, issues: list[ResumeValidationIssue]) -> bool:
    lowered = skill.casefold()
    contaminated = bool(_CONTAMINATION_RE.search(skill) or _RAW_METADATA_RE.search(skill))
    contaminated = contaminated or "ajax-asynchronous-javascript-and-xml" in lowered
    contaminated = contaminated or _has_unknown_hyphen_slug(skill)
    if contaminated:
        _issue(
            issues,
            "contaminated_skill_removed",
            "Removed contaminated skill value.",
            path,
            repaired=True,
        )
    return contaminated


def _expected_category(skill: str) -> str | None:
    key = _key(skill).replace(" ", ".") if "." in skill else _key(skill)
    return _SKILL_CATEGORY_MAP.get(key) or _SKILL_CATEGORY_MAP.get(skill.casefold())


def _profile_corpus(profile: MasterProfile | None) -> str:
    if not profile:
        return ""
    parts: list[str] = [profile.summary or ""]
    parts.extend(skill.name for skill in profile.skills)
    for exp in profile.work_experience:
        parts.extend([exp.company, exp.title, exp.description or "", *exp.bullets, *exp.tags])
    for project in profile.projects:
        parts.extend([project.name, project.description or "", *project.technologies, *project.bullets])
    for cert in profile.certifications:
        parts.extend([cert.name, cert.issuing_org or ""])
    return _clean_text(" ".join(parts)).casefold()


def _iter_bullet_text(rec: ResumeRecommendation):
    for exp_index, exp in enumerate(rec.experience):
        for bullet_index, bullet in enumerate(exp.bullets):
            yield f"experience.{exp_index}.bullets.{bullet_index}", bullet.text
    for project_index, project in enumerate(rec.projects):
        for bullet_index, bullet in enumerate(project.bullets):
            yield f"projects.{project_index}.bullets.{bullet_index}", bullet.text


def _iter_printable_text(rec: ResumeRecommendation):
    yield "target_title", rec.target_title or ""
    yield "summary", rec.summary or ""
    for group_index, group in enumerate(rec.skills):
        yield f"skills.{group_index}.category", group.category
        for skill_index, skill in enumerate(group.skills):
            yield f"skills.{group_index}.skills.{skill_index}", skill
    for exp_index, exp in enumerate(rec.experience):
        yield f"experience.{exp_index}.company", exp.company
        yield f"experience.{exp_index}.title", exp.title
        yield f"experience.{exp_index}.location", exp.location or ""
        yield f"experience.{exp_index}.start_date", exp.start_date
        yield f"experience.{exp_index}.end_date", exp.end_date or ""
        for bullet_index, bullet in enumerate(exp.bullets):
            yield f"experience.{exp_index}.bullets.{bullet_index}", bullet.text
    for project_index, project in enumerate(rec.projects):
        yield f"projects.{project_index}.name", project.name
        yield f"projects.{project_index}.description", project.description or ""
        for tech_index, technology in enumerate(project.technologies):
            yield f"projects.{project_index}.technologies.{tech_index}", technology
        for bullet_index, bullet in enumerate(project.bullets):
            yield f"projects.{project_index}.bullets.{bullet_index}", bullet.text
    for edu_index, edu in enumerate(rec.education):
        for field_name in ("institution", "degree", "field_of_study", "start_date", "end_date", "gpa", "honors"):
            yield f"education.{edu_index}.{field_name}", str(getattr(edu, field_name) or "")
        for course_index, course in enumerate(edu.relevant_coursework):
            yield f"education.{edu_index}.relevant_coursework.{course_index}", course
    for section_name, entries in (("certifications", rec.certifications), ("achievements", rec.achievements), ("awards", rec.awards)):
        for entry_index, entry in enumerate(entries):
            for field_name in ("name", "issuing_org", "title", "issuer", "date", "description"):
                if hasattr(entry, field_name):
                    yield f"{section_name}.{entry_index}.{field_name}", str(getattr(entry, field_name) or "")
    for section_index, section in enumerate(rec.custom_sections):
        yield f"custom_sections.{section_index}.title", section.title
        for item_index, item in enumerate(section.items):
            yield f"custom_sections.{section_index}.items.{item_index}", item


def _valid_title_text(title: str | None) -> bool:
    cleaned = _clean_text(title)
    return bool(
        _is_meaningful_text(cleaned)
        and not _PLACEHOLDER_RE.fullmatch(cleaned)
        and not _CONTAMINATION_RE.search(cleaned)
        and not _RAW_METADATA_RE.search(cleaned)
        and not _has_unknown_hyphen_slug(cleaned)
    )


def _contains(text: str, term: str) -> bool:
    normalized_text = _clean_text(text).casefold()
    normalized_term = _clean_text(term).casefold()
    if not normalized_term:
        return True
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])", normalized_text))


def _is_hard_skill(term: str) -> bool:
    cleaned = _clean_text(term)
    return bool(cleaned and len(cleaned.split()) <= 4 and not re.search(r"\b(?:communication|teamwork|leadership|collaboration)\b", cleaned, re.IGNORECASE))


def _issue(
    issues: list[ResumeValidationIssue],
    code: str,
    message: str,
    path: str,
    severity: ResumeValidationSeverity = ResumeValidationSeverity.WARNING,
    repaired: bool = False,
    blocks_export: bool = False,
) -> None:
    issues.append(
        ResumeValidationIssue(
            code=code,
            message=message,
            severity=severity,
            path=path,
            repaired=repaired,
            blocks_export=blocks_export,
        )
    )
