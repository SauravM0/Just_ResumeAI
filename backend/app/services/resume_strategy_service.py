from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.jd import ParsedJD, SeniorityLevel
from app.schemas.profile import MasterProfile
from app.services.candidate_timeline_service import CandidateSeniority, assess_candidate_timeline, is_fresher_or_student


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
    is_fresher_or_student: bool = False


FRESHER_INTERN_SECTION_ORDER = [
    "contact",
    "target_title",
    "summary",
    "education",
    "experience",
    "projects",
    "achievements",
    "certifications",
    "skills",
]

EXPERIENCED_SECTION_ORDER = [
    "contact",
    "target_title",
    "summary",
    "experience",
    "projects",
    "education",
    "achievements",
    "certifications",
    "skills",
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

    # Determine dynamic section order
    text = _jd_text(parsed_jd)
    technical_focus = len(parsed_jd.programming_languages) + len(parsed_jd.frameworks) >= 5
    
    if is_fresher:
        base_order = [
            "contact", "target_title", "summary", "education"
        ]
        if technical_focus:
            # For technical freshers, show what they can build and what they know first
            base_order += ["skills", "projects", "experience"]
        else:
            base_order += ["experience", "projects", "skills"]
        base_order += ["achievements", "certifications"]
    else:
        base_order = ["contact", "target_title", "summary"]
        if technical_focus:
            base_order += ["skills", "experience", "projects"]
        else:
            base_order += ["experience", "projects", "skills"]
        base_order += ["education", "achievements", "certifications"]

    # Determine frank fresher/student status from timeline evidence
    timeline_fresher = False
    if profile:
        timeline = assess_candidate_timeline(profile)
        timeline_fresher = is_fresher_or_student(timeline)

    return ResumeStrategy(
        classification=classification,
        section_order=base_order,
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
        is_fresher_or_student=timeline_fresher,
    )


def classify_resume_role(parsed_jd: ParsedJD, profile: MasterProfile | None = None) -> ResumeRoleClassification:
    text = _jd_text(parsed_jd)

    # Timeline-based classification takes priority — a student/fresher cannot
    # be classified as SENIOR or EXPERIENCED even if the JD sounds senior.
    if profile:
        timeline = assess_candidate_timeline(profile)
        if is_fresher_or_student(timeline):
            return ResumeRoleClassification.FRESHER_INTERN

    if parsed_jd.seniority == SeniorityLevel.INTERN or any(signal in text for signal in _FRESHER_SIGNALS):
        return ResumeRoleClassification.FRESHER_INTERN

    if parsed_jd.seniority == SeniorityLevel.ENTRY or parsed_jd.required_experience_years in {0, 1, 2}:
        return ResumeRoleClassification.ENTRY_LEVEL

    if parsed_jd.seniority in {SeniorityLevel.SENIOR, SeniorityLevel.LEAD, SeniorityLevel.STAFF, SeniorityLevel.PRINCIPAL, SeniorityLevel.DIRECTOR, SeniorityLevel.VP, SeniorityLevel.C_LEVEL}:
        return ResumeRoleClassification.SENIOR

    domain_hits = sum(1 for signal in _DOMAIN_SIGNALS if signal in text)
    if domain_hits >= 2:
        return ResumeRoleClassification.DOMAIN_SPECIALIST

    if profile and assess_candidate_timeline(profile).candidate_seniority in {
        CandidateSeniority.FRESHER,
        CandidateSeniority.INTERN,
        CandidateSeniority.ENTRY_LEVEL,
    } and profile.projects and profile.education:
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
