"""Structured profile extraction from uploaded resume text."""

from __future__ import annotations

import logging
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.ai.gemini_client import GeminiClientError, get_gemini_client
from app.schemas.profile import (
    Award,
    Certification,
    ContactInfo,
    Education,
    MasterProfile,
    Project,
    Skill,
    WorkExperience,
)
from app.services.locked_fields_service import build_locked_fields
from app.services.resume_parser_service import normalize_resume_text

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d[\d ()-]{7,}\d)")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}(?:-\d{2})?(?:-\d{2})?$")
_MONTH_MAP = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}
_SKILL_SPLIT_RE = re.compile(r"[,|;/]")
_BULLET_PREFIX_RE = re.compile(r"^[\s*+\-]+")


class ResumeProfileExtractionError(RuntimeError):
    """Raised when no structured profile can be created from source text."""


class ExtractedContact(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


class ExtractedExperience(BaseModel):
    company: str = ""
    title: str = ""
    location: str | None = None
    start_date: str = ""
    end_date: str | None = None
    is_current: bool = False
    description: str | None = None
    bullets: list[str] = Field(default_factory=list)


class ExtractedEducation(BaseModel):
    institution: str = ""
    degree: str = ""
    field_of_study: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    gpa: str | None = None
    honors: str | None = None
    relevant_coursework: list[str] = Field(default_factory=list)


class ExtractedProject(BaseModel):
    name: str = ""
    description: str | None = None
    technologies: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)


class ExtractedCertification(BaseModel):
    name: str = ""
    issuing_org: str | None = None
    issue_date: str | None = None


class ExtractedAchievement(BaseModel):
    title: str = ""
    description: str | None = None
    date: str | None = None
    issuer: str | None = None


class ExtractedProfileDraft(BaseModel):
    contact: ExtractedContact = Field(default_factory=ExtractedContact)
    summary: str | None = None
    work_experience: list[ExtractedExperience] = Field(default_factory=list)
    education: list[ExtractedEducation] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    projects: list[ExtractedProject] = Field(default_factory=list)
    certifications: list[ExtractedCertification] = Field(default_factory=list)
    achievements: list[ExtractedAchievement] = Field(default_factory=list)


class FieldConfidence(BaseModel):
    field: str
    value: str
    confidence: float
    reason: str
    needs_confirmation: bool


class ExtractionConfidenceReport(BaseModel):
    fields: list[FieldConfidence] = Field(default_factory=list)
    overall_confidence: float = 1.0
    has_low_confidence_fields: bool = False


class ProfileExtractionResult(BaseModel):
    profile: MasterProfile
    cleaned_text: str
    warnings: list[str] = Field(default_factory=list)
    confidence: ExtractionConfidenceReport = Field(default_factory=ExtractionConfidenceReport)
    locked_fields: dict[str, Any] = Field(default_factory=dict)


async def extract_profile_from_resume_text(
    text: str,
    *,
    ai_client: Any | None = None,
) -> ProfileExtractionResult:
    """Extract an editable MasterProfile, falling back to deterministic contact parsing."""
    cleaned_text = normalize_resume_text(text)
    if len(cleaned_text) < 20:
        raise ResumeProfileExtractionError("Source resume text is too short to extract a profile.")

    warnings: list[str] = []
    draft: ExtractedProfileDraft | None = None
    try:
        client = ai_client or get_gemini_client()
        draft = await client.generate_structured(
            _profile_extraction_prompt(cleaned_text[:25000]),
            ExtractedProfileDraft,
            system_instruction=(
                "Extract only facts present in the source resume. "
                "Do not invent skills, dates, employers, degrees, or achievements."
            ),
            temperature=0.0,
        )
    except (GeminiClientError, ValueError) as exc:
        logger.info("source_resume.profile_extraction.ai_fallback reason=%s", exc.__class__.__name__)
        warnings.append("AI profile extraction was unavailable; review the imported profile before generation.")

    draft = draft or _deterministic_draft(cleaned_text)
    profile = normalize_extracted_profile(draft, source_text=cleaned_text)
    locked_fields = build_locked_fields(profile)
    confidence = _compute_confidence(profile, draft)
    return ProfileExtractionResult(
        profile=profile,
        cleaned_text=cleaned_text,
        warnings=warnings,
        confidence=confidence,
        locked_fields=locked_fields.model_dump(mode="json"),
    )


def normalize_extracted_profile(
    draft: ExtractedProfileDraft | dict[str, Any],
    *,
    source_text: str = "",
) -> MasterProfile:
    """Convert extractor output into the app's clean profile contract."""
    extracted = draft if isinstance(draft, ExtractedProfileDraft) else ExtractedProfileDraft.model_validate(draft)
    contact = extracted.contact
    fallback = _deterministic_draft(source_text).contact if source_text else ExtractedContact()

    profile = MasterProfile(
        id=str(uuid4()),
        version=1,
        contact=ContactInfo(
            full_name=_clean_line(contact.full_name or fallback.full_name),
            email=_clean_line(contact.email or fallback.email),
            phone=_optional_line(contact.phone or fallback.phone),
            location=_optional_line(contact.location),
            linkedin_url=_optional_line(contact.linkedin_url),
            github_url=_optional_line(contact.github_url),
            portfolio_url=_optional_line(contact.portfolio_url),
        ),
        summary=_optional_paragraph(extracted.summary),
        work_experience=[
            WorkExperience(
                id=str(uuid4()),
                company=_clean_line(item.company),
                title=_clean_line(item.title),
                location=_optional_line(item.location),
                start_date=_clean_date_flexible(item.start_date),
                end_date=_clean_date_flexible(item.end_date) or None,
                is_current=item.is_current or _is_present_date(item.end_date),
                description=_optional_paragraph(item.description),
                bullets=_clean_list(item.bullets),
                tags=[],
                needs_rewrite=True,
            )
            for item in extracted.work_experience
            if _clean_line(item.company) and _clean_line(item.title) and _clean_date_flexible(item.start_date)
        ],
        education=[
            Education(
                id=str(uuid4()),
                institution=_clean_line(item.institution),
                degree=_clean_line(item.degree),
                field_of_study=_optional_line(item.field_of_study),
                start_date=_clean_date_flexible(item.start_date) or None,
                end_date=_clean_date_flexible(item.end_date) or None,
                gpa=_optional_line(item.gpa),
                honors=_optional_line(item.honors),
                relevant_coursework=_clean_list(item.relevant_coursework),
            )
            for item in extracted.education
            if _clean_line(item.institution) and _clean_line(item.degree)
        ],
        skills=[Skill(name=value) for value in _clean_list(extracted.skills)],
        projects=[
            Project(
                id=str(uuid4()),
                name=_clean_line(item.name),
                description=_optional_paragraph(item.description),
                technologies=_clean_list(item.technologies),
                bullets=_clean_list(item.bullets),
                needs_rewrite=True,
            )
            for item in extracted.projects
            if _clean_line(item.name)
        ],
        certifications=[
            Certification(
                id=str(uuid4()),
                name=_clean_line(item.name),
                issuing_org=_optional_line(item.issuing_org),
                issue_date=_clean_date_flexible(item.issue_date) or None,
            )
            for item in extracted.certifications
            if _clean_line(item.name)
        ],
        awards=[
            Award(
                id=str(uuid4()),
                title=_clean_line(item.title),
                description=_optional_paragraph(item.description),
                date=_clean_date_flexible(item.date) or None,
                issuer=_optional_line(item.issuer),
            )
            for item in extracted.achievements
            if _clean_line(item.title)
        ],
    )
    return profile


def _deterministic_draft(text: str) -> ExtractedProfileDraft:
    lines = [line.strip() for line in normalize_resume_text(text).splitlines() if line.strip()]
    first_line = next((line for line in lines if _looks_like_name(line)), "")
    email = (_EMAIL_RE.search(text).group(0) if _EMAIL_RE.search(text) else "")
    phone_match = _PHONE_RE.search(text)
    urls = _URL_RE.findall(text)
    skills = _skills_from_lines(lines)
    return ExtractedProfileDraft(
        contact=ExtractedContact(
            full_name=first_line,
            email=email,
            phone=phone_match.group(0).strip() if phone_match else None,
            linkedin_url=next((url for url in urls if "linkedin.com" in url.casefold()), None),
            github_url=next((url for url in urls if "github.com" in url.casefold()), None),
        ),
        skills=skills,
    )


def _profile_extraction_prompt(text: str) -> str:
    return f"""Extract the complete candidate profile from this resume. Return ONLY facts present in the source.

CRITICAL EXTRACTION RULES:
1. GPA/CGPA: ALWAYS extract if present. Accept any format: "3.8/4.0", "8.7 CGPA", "9.1/10", "87%".
   Put the EXACT raw string in the gpa field; do not convert or normalize.
2. Dates: extract EXACTLY as written. "March 2023", "Jan 2024", "May 2025 (expected)" are all valid.
   Do NOT convert to ISO format; that happens later.
3. Achievements: Extract ALL awards, hackathons, competitions, scholarships, honours, recognitions.
   Put them in the achievements array with title, description, date, and issuer when available.
4. Coursework: If the resume lists "Relevant Coursework" or similar, extract ALL course names.
5. Technologies in projects: Extract the COMPLETE tech stack for each project, including versions if listed.
6. Bullet points: Extract ALL bullet points for each experience and project, preserving the original wording.
7. Contact: Extract email, phone (with country code), LinkedIn URL, GitHub URL, portfolio URL.
8. Summary/Objective: Extract verbatim if present.
9. Skills: Split into individual skills, not "Python, Django, React" as one skill.
10. Do NOT invent anything. If a field is not in the resume, leave it empty/null.

SOURCE RESUME:
{text}"""


def _skills_from_lines(lines: list[str]) -> list[str]:
    for index, line in enumerate(lines):
        lowered = line.casefold()
        if lowered.startswith(("skills", "technical skills", "technologies")):
            value = line.split(":", 1)[1] if ":" in line else " ".join(lines[index + 1:index + 3])
            return _clean_list(_SKILL_SPLIT_RE.split(value))
    return []


def _looks_like_name(value: str) -> bool:
    lowered = value.casefold()
    if lowered in {"resume", "curriculum vitae", "cv"} or "@" in value or len(value) > 70:
        return False
    words = value.split()
    return 1 < len(words) <= 5 and not any(char.isdigit() for char in value)


def _clean_line(value: str | None) -> str:
    return " ".join(normalize_resume_text(str(value or "")).splitlines()).strip()


def _optional_line(value: str | None) -> str | None:
    cleaned = _clean_line(value)
    return cleaned or None


def _optional_paragraph(value: str | None) -> str | None:
    cleaned = _clean_line(value)
    return cleaned or None


def _clean_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _BULLET_PREFIX_RE.sub("", _clean_line(value))
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _clean_date(value: str | None) -> str:
    return _clean_date_flexible(value)


def _clean_date_flexible(value: str | None) -> str:
    """Parse common resume date formats into YYYY or YYYY-MM."""
    cleaned = _clean_line(value)
    if not cleaned:
        return ""
    lower = cleaned.casefold()
    if _DATE_RE.match(cleaned):
        return cleaned[:7] if len(cleaned) > 7 else cleaned
    if lower in {"present", "current", "now", "ongoing"}:
        return ""
    for abbrev, month in _MONTH_MAP.items():
        if abbrev in lower:
            year_match = re.search(r"20\d{2}|19\d{2}", cleaned)
            if year_match:
                return f"{year_match.group()}-{month}"
    year_match = re.search(r"20\d{2}|19\d{2}", cleaned)
    if year_match:
        return year_match.group()
    return ""


def _is_present_date(value: str | None) -> bool:
    return _clean_line(value).casefold() in {"present", "current", "now", "ongoing"}


def _compute_confidence(profile: MasterProfile, draft: ExtractedProfileDraft) -> ExtractionConfidenceReport:
    fields: list[FieldConfidence] = []

    if profile.contact.email:
        confidence = 1.0 if _EMAIL_RE.fullmatch(profile.contact.email) else 0.4
        if confidence < 0.8:
            fields.append(FieldConfidence(
                field="contact.email",
                value=profile.contact.email,
                confidence=confidence,
                reason="Email format looks unusual",
                needs_confirmation=True,
            ))

    gpa_pattern = re.compile(r"^\d+\.?\d*\s*(?:/\s*\d+\.?\d*|cgpa|gpa|%)?$", re.IGNORECASE)
    for index, edu in enumerate(profile.education):
        if edu.gpa:
            confidence = 1.0 if gpa_pattern.match(edu.gpa.strip()) else 0.5
            if confidence < 0.8:
                fields.append(FieldConfidence(
                    field=f"education[{index}].gpa",
                    value=edu.gpa,
                    confidence=confidence,
                    reason="GPA format is non-standard; please verify",
                    needs_confirmation=True,
                ))

    for index, exp in enumerate(profile.work_experience):
        if exp.company:
            is_all_caps = exp.company.isupper() and len(exp.company) > 3
            is_very_short = len(exp.company) < 3
            has_digits = any(char.isdigit() for char in exp.company)
            confidence = 0.6 if (is_all_caps or is_very_short or has_digits) else 1.0
            if confidence < 0.8:
                fields.append(FieldConfidence(
                    field=f"work_experience[{index}].company",
                    value=exp.company,
                    confidence=confidence,
                    reason="Company name looks unusual; please verify",
                    needs_confirmation=True,
                ))
        if not exp.start_date:
            fields.append(FieldConfidence(
                field=f"work_experience[{index}].start_date",
                value="",
                confidence=0.3,
                reason="Start date could not be extracted; please add manually",
                needs_confirmation=True,
            ))

    has_low = any(field.confidence < 0.7 for field in fields)
    overall = sum(field.confidence for field in fields) / len(fields) if fields else 1.0
    return ExtractionConfidenceReport(
        fields=fields,
        overall_confidence=overall,
        has_low_confidence_fields=has_low,
    )
