from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.jd import ParsedJD, SeniorityLevel
from app.schemas.profile import MasterProfile


class ResumeRoleClassification(str, Enum):
    FRESHER_INTERN = "fresher_intern"
    ENTRY_LEVEL = "entry_level"
    EXPERIENCED = "experienced"
    SENIOR = "senior"
    DOMAIN_SPECIALIST = "domain_specialist"


class ResumeStrategy(BaseModel):
    classification: ResumeRoleClassification
    section_order: list[str] = Field(default_factory=list)
    preserve_sections: list[str] = Field(default_factory=list)
    trim_first: list[str] = Field(default_factory=list)


FRESHER_INTERN_SECTION_ORDER = [
    "Contact",
    "Target Title",
    "Professional Summary",
    "Education",
    "Technical Skills",
    "Projects",
    "Experience",
    "Achievements",
    "Certifications",
]

EXPERIENCED_SECTION_ORDER = [
    "Contact",
    "Target Title",
    "Professional Summary",
    "Technical Skills",
    "Professional Experience",
    "Projects",
    "Education",
    "Certifications",
]

_FRESHER_SIGNALS = (
    "intern",
    "internship",
    "graduate",
    "fresh graduate",
    "fresher",
    "no arrears",
    "learning new technologies",
    "learn new technologies",
    "training",
    "basic understanding",
    "basic knowledge",
)

_DOMAIN_SIGNALS = (
    "sharepoint",
    "power pages",
    "power automate",
    "obdx",
    "oracle banking",
    "salesforce",
    "sap",
    "servicenow",
)


def build_resume_strategy(parsed_jd: ParsedJD, profile: MasterProfile | None = None) -> ResumeStrategy:
    classification = classify_resume_role(parsed_jd, profile)
    is_fresher = classification == ResumeRoleClassification.FRESHER_INTERN

    return ResumeStrategy(
        classification=classification,
        section_order=FRESHER_INTERN_SECTION_ORDER if is_fresher else EXPERIENCED_SECTION_ORDER,
        preserve_sections=[
            "education",
            "projects",
            "achievements",
            "awards",
            "certifications",
            "metrics",
            "leadership",
            "experience",
        ] if is_fresher else ["experience", "projects", "skills", "education", "certifications"],
        trim_first=[
            "unrelated skills",
            "repeated skills",
            "generic phrases",
            "lower-value bullets",
        ],
    )


def classify_resume_role(parsed_jd: ParsedJD, profile: MasterProfile | None = None) -> ResumeRoleClassification:
    text = _jd_text(parsed_jd)
    if parsed_jd.seniority == SeniorityLevel.INTERN or any(signal in text for signal in _FRESHER_SIGNALS):
        return ResumeRoleClassification.FRESHER_INTERN

    if parsed_jd.seniority == SeniorityLevel.ENTRY or parsed_jd.required_experience_years in {0, 1, 2}:
        return ResumeRoleClassification.ENTRY_LEVEL

    if parsed_jd.seniority in {SeniorityLevel.SENIOR, SeniorityLevel.LEAD, SeniorityLevel.STAFF, SeniorityLevel.PRINCIPAL, SeniorityLevel.DIRECTOR, SeniorityLevel.VP, SeniorityLevel.C_LEVEL}:
        return ResumeRoleClassification.SENIOR

    domain_hits = sum(1 for signal in _DOMAIN_SIGNALS if signal in text)
    if domain_hits >= 2:
        return ResumeRoleClassification.DOMAIN_SPECIALIST

    if profile and _estimated_experience_count(profile) <= 1 and profile.projects and profile.education:
        return ResumeRoleClassification.ENTRY_LEVEL

    return ResumeRoleClassification.EXPERIENCED


def is_fresher_intern_strategy(strategy: ResumeStrategy | None) -> bool:
    return bool(strategy and strategy.classification == ResumeRoleClassification.FRESHER_INTERN)


def _jd_text(parsed_jd: ParsedJD) -> str:
    parts = [
        parsed_jd.job_title,
        parsed_jd.required_education or "",
        parsed_jd.raw_text,
        " ".join(parsed_jd.required_skills),
        " ".join(parsed_jd.preferred_skills),
        " ".join(parsed_jd.responsibilities),
        " ".join(req.text for req in parsed_jd.requirements),
        " ".join(parsed_jd.tools_platforms),
        " ".join(parsed_jd.domain_platform_terms),
        " ".join(keyword.keyword for keyword in parsed_jd.keywords),
    ]
    return re.sub(r"\s+", " ", " ".join(parts).casefold())


def _estimated_experience_count(profile: MasterProfile) -> int:
    return len([exp for exp in profile.work_experience if exp.company and exp.title])
