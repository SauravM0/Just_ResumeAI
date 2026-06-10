from __future__ import annotations

import re
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.jd import ParsedJD, SeniorityLevel
from app.schemas.profile import MasterProfile, WorkExperience


SENIORITY_ADJUSTMENT_WARNING = (
    "JD seniority exceeds candidate evidence; title was adjusted to avoid unsupported seniority."
)


class CandidateSeniority(str, Enum):
    FRESHER = "fresher"
    INTERN = "intern"
    ENTRY_LEVEL = "entry_level"
    JUNIOR = "junior"
    MID_LEVEL = "mid_level"
    SENIOR = "senior"


class CandidateTimelineAssessment(BaseModel):
    professional_months: int = 0
    internship_months: int = 0
    professional_years: float = 0.0
    internship_years: float = 0.0
    graduation_year: int | None = None
    has_full_time_work: bool = False
    is_student: bool = False
    candidate_seniority: CandidateSeniority = CandidateSeniority.ENTRY_LEVEL


class HonestTitleDecision(BaseModel):
    title: str
    adjusted: bool = False
    warnings: list[str] = Field(default_factory=list)
    timeline: CandidateTimelineAssessment


_INTERN_SIGNALS = re.compile(r"\b(intern|internship|trainee|apprentice|co-?op)\b", re.IGNORECASE)
_SYNTHETIC_EXPERIENCE_SIGNALS = (
    "academic / project-based experience",
    "academic experience",
    "project-based experience",
)
_HIGH_SENIORITY_TITLE_RE = re.compile(
    r"^\s*(senior|sr\.?|lead|principal|staff|chief|head)\s+",
    re.IGNORECASE,
)
_MONTH_YYYY_RE = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})$",
    re.IGNORECASE,
)
_MONTH_ABBR_RE = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+(\d{4})$",
    re.IGNORECASE,
)
_PRESENT_SIGNALS = re.compile(r"^(present|current|now|ongoing)$", re.IGNORECASE)
_STUDENT_SIGNALS = re.compile(
    r"\b(pursuing|currently enrolled|expected graduation|candidate|student|enrolled|studying|yet to complete)\b",
    re.IGNORECASE,
)


def assess_candidate_timeline(
    profile: MasterProfile,
    *,
    as_of: date | None = None,
) -> CandidateTimelineAssessment:
    """Infer candidate experience from dated work history only."""
    today = as_of or date.today()
    professional_intervals: list[tuple[int, int]] = []
    internship_intervals: list[tuple[int, int]] = []

    for experience in profile.work_experience:
        interval = _work_interval(experience, today)
        if not interval or _is_synthetic_experience(experience):
            continue
        if _is_internship(experience, profile):
            internship_intervals.append(interval)
        else:
            professional_intervals.append(interval)

    professional_months = _merged_month_count(professional_intervals)
    internship_months = _merged_month_count(internship_intervals)
    graduation_year = _graduation_year(profile)
    has_full_time_work = professional_months > 0
    is_student = _is_student_status(profile, graduation_year, today)
    seniority = _candidate_seniority(
        professional_months=professional_months,
        internship_months=internship_months,
        graduation_year=graduation_year,
        has_full_time_work=has_full_time_work,
        today=today,
    )
    return CandidateTimelineAssessment(
        professional_months=professional_months,
        internship_months=internship_months,
        professional_years=round(professional_months / 12, 1),
        internship_years=round(internship_months / 12, 1),
        graduation_year=graduation_year,
        has_full_time_work=has_full_time_work,
        is_student=is_student,
        candidate_seniority=seniority,
    )


def choose_honest_target_title(
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    requested_title: str | None = None,
    *,
    as_of: date | None = None,
) -> HonestTitleDecision:
    timeline = assess_candidate_timeline(profile, as_of=as_of)
    title = _clean_title(requested_title or parsed_jd.job_title or "")
    if not title:
        title = _fallback_title(profile)

    if not jd_seniority_exceeds_candidate(parsed_jd, timeline, title):
        return HonestTitleDecision(title=title, timeline=timeline)

    return HonestTitleDecision(
        title=downgrade_target_title(title),
        adjusted=True,
        warnings=[SENIORITY_ADJUSTMENT_WARNING],
        timeline=timeline,
    )


def jd_seniority_exceeds_candidate(
    parsed_jd: ParsedJD,
    timeline: CandidateTimelineAssessment,
    title: str | None = None,
) -> bool:
    """Return true when JD years or title/seniority exceed candidate evidence."""
    years = parsed_jd.required_experience_years or 0
    jd_is_senior = (
        years >= 5
        or parsed_jd.seniority in {
            SeniorityLevel.SENIOR,
            SeniorityLevel.LEAD,
            SeniorityLevel.STAFF,
            SeniorityLevel.PRINCIPAL,
            SeniorityLevel.DIRECTOR,
            SeniorityLevel.VP,
            SeniorityLevel.C_LEVEL,
        }
        or bool(_HIGH_SENIORITY_TITLE_RE.search(title or parsed_jd.job_title or ""))
    )
    if not jd_is_senior:
        return False
    if timeline.candidate_seniority in {CandidateSeniority.FRESHER, CandidateSeniority.INTERN}:
        return True
    return years >= 5 and timeline.professional_months < years * 12


def downgrade_target_title(title: str) -> str:
    cleaned = _clean_title(title)
    lowered = cleaned.casefold()
    if re.match(r"^\s*lead\s+backend\s+engineer\b", lowered):
        return "Backend Developer"
    if re.match(r"^\s*principal\s+software\s+engineer\b", lowered):
        return "Software Developer"

    downgraded = _HIGH_SENIORITY_TITLE_RE.sub("", cleaned).strip(" -:/")
    if not downgraded:
        return "Software Developer"
    if re.fullmatch(r"backend engineer", downgraded, flags=re.IGNORECASE):
        return "Backend Developer"
    return downgraded


def allows_seniority_claims(timeline: CandidateTimelineAssessment) -> bool:
    return timeline.candidate_seniority == CandidateSeniority.SENIOR


def _candidate_seniority(
    *,
    professional_months: int,
    internship_months: int,
    graduation_year: int | None,
    has_full_time_work: bool,
    today: date,
) -> CandidateSeniority:
    if not has_full_time_work:
        if graduation_year is not None and graduation_year >= today.year - 1:
            return CandidateSeniority.FRESHER
        if internship_months:
            return CandidateSeniority.INTERN
        return CandidateSeniority.ENTRY_LEVEL
    if professional_months < 12:
        return CandidateSeniority.ENTRY_LEVEL
    if professional_months < 36:
        return CandidateSeniority.JUNIOR
    if professional_months < 60:
        return CandidateSeniority.MID_LEVEL
    return CandidateSeniority.SENIOR


def _work_interval(experience: WorkExperience, today: date) -> tuple[int, int] | None:
    start = _parse_month(experience.start_date)
    end = None
    if experience.end_date and _PRESENT_SIGNALS.match(experience.end_date.strip()):
        end = _month_ordinal(today)
    elif experience.is_current:
        end = _month_ordinal(today)
    elif experience.end_date:
        end = _parse_month(experience.end_date)
    else:
        end = _month_ordinal(today)
    if start is None or end is None or end < start:
        return None
    return start, end


def _parse_month(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    # Try YYYY-MM format first
    match = re.match(r"^(\d{4})-(\d{1,2})$", text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        if 1 <= month <= 12:
            return year * 12 + month - 1
        return None
    # Try YYYY (year-only)
    match = re.match(r"^(\d{4})$", text)
    if match:
        return int(match.group(1)) * 12  # July of that year
    # Try Month YYYY (full month name)
    match = _MONTH_YYYY_RE.match(text)
    if match:
        month = _month_name_to_number(match.group(1))
        year = int(match.group(2))
        return year * 12 + month - 1
    # Try Mon YYYY (abbreviated)
    match = _MONTH_ABBR_RE.match(text)
    if match:
        month = _month_name_to_number(match.group(1))
        year = int(match.group(2))
        return year * 12 + month - 1
    return None


def _month_name_to_number(name: str) -> int:
    months = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    return months.get(name.casefold().rstrip("."), 1)


def _month_ordinal(value: date) -> int:
    return value.year * 12 + value.month - 1


def _merged_month_count(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum(end - start + 1 for start, end in merged)


def _is_internship(experience: WorkExperience, profile: MasterProfile | None = None) -> bool:
    text = " ".join([experience.title, experience.company, *experience.tags])
    if _INTERN_SIGNALS.search(text):
        return True
    # Check for education overlap: if role dates overlap with education period, likely an internship
    if profile and _overlaps_education(experience, profile):
        return True
    return False


def _overlaps_education(experience: WorkExperience, profile: MasterProfile) -> bool:
    start = _parse_month(experience.start_date)
    end = None
    if experience.end_date and _PRESENT_SIGNALS.match(experience.end_date.strip()):
        return False  # Current role unlikely to be education-overlapping
    elif experience.is_current:
        return False
    elif experience.end_date:
        end = _parse_month(experience.end_date)
    if start is None or end is None:
        return False
    for edu in profile.education:
        edu_start = _parse_month(edu.start_date)
        edu_end = _parse_month(edu.end_date) if edu.end_date else None
        # Roles during education (or within 3 months after) are likely internships
        if edu_end is not None and edu_start is not None:
            grace = 3  # months of grace after graduation
            if edu_start - grace <= start <= edu_end + grace:
                return True
    return False


def _is_student_status(profile: MasterProfile, graduation_year: int | None, today: date) -> bool:
    """Determine if the candidate is likely still a student."""
    if graduation_year is not None and graduation_year >= today.year:
        return True
    # Check for current education with no end date (still enrolled)
    for edu in profile.education:
        if not edu.end_date:
            return True
        if edu.end_date and _PRESENT_SIGNALS.match(edu.end_date.strip()):
            return True
    # Check for student signals in degree/field descriptions
    for edu in profile.education:
        text = " ".join([edu.degree, edu.field_of_study or "", edu.honors or ""])
        if _STUDENT_SIGNALS.search(text):
            return True
    return False

def is_fresher_or_student(timeline: CandidateTimelineAssessment) -> bool:
    """Return True if the candidate is a student or fresher (no real work experience)."""
    return timeline.is_student or timeline.candidate_seniority in {
        CandidateSeniority.FRESHER,
        CandidateSeniority.INTERN,
    }


def _is_synthetic_experience(experience: WorkExperience) -> bool:
    company = experience.company.casefold()
    return any(signal in company for signal in _SYNTHETIC_EXPERIENCE_SIGNALS)


def _graduation_year(profile: MasterProfile) -> int | None:
    years: list[int] = []
    for education in profile.education:
        parsed = _parse_month(education.end_date)
        if parsed is not None:
            years.append(parsed // 12)
    return max(years) if years else None


def _clean_title(title: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", str(title or "")).strip()
    cleaned = re.sub(r"^\s*(designation|job title|title|role)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" :-\t")


def _fallback_title(profile: MasterProfile) -> str:
    if profile.work_experience:
        return _clean_title(profile.work_experience[0].title) or "Software Developer"
    if profile.projects:
        return "Software Developer"
    return "Resume Candidate"
