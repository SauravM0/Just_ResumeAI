"""Locked field extraction for facts AI must preserve exactly."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.schemas.profile import MasterProfile

if TYPE_CHECKING:
    from app.schemas.resume import ResumeRecommendation


class LockedFields(BaseModel):
    """Fields that downstream AI flows must not modify."""

    full_name: str = ""
    email: str = ""
    phone: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    company_values: dict[str, str] = Field(default_factory=dict)
    company_names: list[str] = Field(default_factory=list)
    institution_values: dict[str, str] = Field(default_factory=dict)
    institution_names: list[str] = Field(default_factory=list)
    gpa_values: dict[str, str] = Field(default_factory=dict)
    cert_names: list[str] = Field(default_factory=list)
    achievement_titles: list[str] = Field(default_factory=list)


def build_locked_fields(profile: MasterProfile) -> LockedFields:
    """Extract and freeze user-provided identity and credential facts."""
    return LockedFields(
        full_name=profile.contact.full_name or "",
        email=profile.contact.email or "",
        phone=profile.contact.phone,
        linkedin_url=profile.contact.linkedin_url,
        github_url=profile.contact.github_url,
        company_values={item.id: item.company for item in profile.work_experience if item.company.strip()},
        company_names=[item.company for item in profile.work_experience if item.company.strip()],
        institution_values={item.id: item.institution for item in profile.education if item.institution.strip()},
        institution_names=[item.institution for item in profile.education if item.institution.strip()],
        gpa_values={item.id: item.gpa for item in profile.education if item.gpa},
        cert_names=[item.name for item in profile.certifications if item.name.strip()],
        achievement_titles=[item.title for item in profile.awards if item.title.strip()],
    )


def validate_locked_fields_in_output(
    rec: "ResumeRecommendation",
    locked: LockedFields | None,
    logger=None,
) -> list[str]:
    """
    Restore generated resume fields that must remain identical to the profile.

    The recommendation is intentionally mutated in place so callers can run this
    as a final repair gate before persisting or exporting.
    """
    if locked is None:
        return []

    violations: list[str] = []
    _restore_contact(rec, locked, violations)
    _restore_experience(rec, locked, violations)
    _restore_education(rec, locked, violations)

    if violations and logger:
        for violation in violations:
            logger.warning("locked_fields.violation: %s", violation)
    return violations


_AT_COMPANY_RE = re.compile(
    r"\bat\s+([A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})"
    r"(?=\s+(?:to|for|using|with|by|and|while|through|across|resulting|,|\.)|[,.]?$)"
)


def guard_bullet_company_references(bullet_text: str, locked: LockedFields | None) -> str:
    """Remove unsupported ``at Company`` phrases from generated bullet text."""
    if locked is None or not locked.company_names:
        return bullet_text

    text = bullet_text or ""
    for match in list(_AT_COMPANY_RE.finditer(text)):
        mentioned = match.group(1).strip(" ,.;:")
        if len(mentioned) <= 3:
            continue
        if _matches_any(mentioned, locked.company_names):
            continue
        text = text.replace(match.group(0), "", 1)

    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"\s*,\s*,+", ", ", text)
    return text.strip(" ,;:-")


def _restore_contact(rec: "ResumeRecommendation", locked: LockedFields, violations: list[str]) -> None:
    if locked.full_name and rec.contact.full_name != locked.full_name:
        violations.append(f"contact.full_name='{rec.contact.full_name}' restored to locked full name")
        rec.contact.full_name = locked.full_name
    if locked.email and rec.contact.email != locked.email:
        violations.append(f"contact.email='{rec.contact.email}' restored to locked email")
        rec.contact.email = locked.email
    if locked.phone and rec.contact.phone != locked.phone:
        violations.append(f"contact.phone='{rec.contact.phone}' restored to locked phone")
        rec.contact.phone = locked.phone
    if locked.linkedin_url and rec.contact.linkedin_url != locked.linkedin_url:
        violations.append("contact.linkedin_url restored to locked LinkedIn URL")
        rec.contact.linkedin_url = locked.linkedin_url
    if locked.github_url and rec.contact.github_url != locked.github_url:
        violations.append("contact.github_url restored to locked GitHub URL")
        rec.contact.github_url = locked.github_url


def _restore_experience(rec: "ResumeRecommendation", locked: LockedFields, violations: list[str]) -> None:
    valid_names = [_clean(value) for value in locked.company_names]
    for index, entry in enumerate(rec.experience):
        expected = locked.company_values.get(entry.source_id)
        if expected and entry.company != expected:
            violations.append(f"experience[{index}].company='{entry.company}' restored to locked '{expected}'")
            entry.company = expected
            continue
        if valid_names and _clean(entry.company) not in valid_names:
            restored = _find_closest(entry.company, locked.company_names)
            violations.append(f"experience[{index}].company='{entry.company}' not in locked company names")
            entry.company = restored


def _restore_education(rec: "ResumeRecommendation", locked: LockedFields, violations: list[str]) -> None:
    valid_names = [_clean(value) for value in locked.institution_names]
    for index, entry in enumerate(rec.education):
        expected = locked.institution_values.get(entry.source_id)
        if expected and entry.institution != expected:
            violations.append(f"education[{index}].institution='{entry.institution}' restored to locked '{expected}'")
            entry.institution = expected
        elif valid_names and _clean(entry.institution) not in valid_names:
            restored = _find_closest(entry.institution, locked.institution_names)
            violations.append(f"education[{index}].institution='{entry.institution}' not in locked institutions")
            entry.institution = restored

        locked_gpa = locked.gpa_values.get(entry.source_id)
        if locked_gpa and entry.gpa != locked_gpa:
            violations.append(f"education[{index}].gpa='{entry.gpa}' restored to locked '{locked_gpa}'")
            entry.gpa = locked_gpa


def _find_closest(value: str, options: list[str]) -> str:
    value_key = _clean(value)
    for option in options:
        option_key = _clean(option)
        if value_key and (value_key in option_key or option_key in value_key):
            return option
    return options[0] if options else value


def _matches_any(value: str, options: list[str]) -> bool:
    value_key = _clean(value)
    return any(value_key and (value_key in _clean(option) or _clean(option) in value_key) for option in options)


def _clean(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
