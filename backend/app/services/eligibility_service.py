"""
Deterministic profile/JD eligibility checks.

This service only compares stated profile facts with explicit JD constraints.
It never upgrades an unknown or mismatched profile into an eligible one.
"""

from __future__ import annotations

import re
from datetime import date

from app.schemas.jd import ParsedJD
from app.schemas.pipeline import EligibilityResult
from app.schemas.profile import MasterProfile


_BRANCH_ALIASES: dict[str, set[str]] = {
    "mechanical": {"mechanical", "mech"},
    "automobile": {"automobile", "automotive"},
    "electrical": {"electrical", "eee"},
    "electronics": {"electronics", "ece", "electronic", "communication"},
    "civil": {"civil"},
    "computer science": {"computer science", "computer", "cse", "cs", "software", "information technology", "it"},
}

_DEGREE_TERMS = {
    "bachelor": {"bachelor", "bachelors", "b.tech", "btech", "be", "b.e", "bs", "b.s"},
    "master": {"master", "masters", "m.tech", "mtech", "ms", "m.s", "mba"},
    "diploma": {"diploma", "polytechnic"},
}


def check_eligibility(profile: MasterProfile, parsed_jd: ParsedJD) -> EligibilityResult:
    """Return deterministic eligibility status for explicit JD constraints."""
    blocking_issues: list[str] = []
    warnings: list[str] = []
    matched_points: list[str] = []

    jd_text = _jd_text(parsed_jd)
    normalized_jd = _normalize(jd_text)

    profile_branches = _profile_branches(profile)
    required_branches = _required_branches(normalized_jd)
    if required_branches:
        matched_branch = _match_any_branch(profile_branches, required_branches)
        if matched_branch:
            matched_points.append(f"Branch matches explicit JD requirement: {matched_branch}.")
        else:
            blocking_issues.append(
                "Branch mismatch: JD requires "
                f"{', '.join(sorted(required_branches))}; profile lists "
                f"{', '.join(sorted(profile_branches)) or 'no branch'}."
            )

    profile_degrees = _profile_degrees(profile)
    required_degrees = _required_degrees(normalized_jd, parsed_jd.required_education)
    if required_degrees:
        if profile_degrees & required_degrees:
            matched_points.append(f"Degree level matches: {', '.join(sorted(profile_degrees & required_degrees))}.")
        elif not profile_degrees:
            warnings.append("Degree requirement found in JD, but no clear degree level was found in the profile.")
        else:
            blocking_issues.append(
                "Degree mismatch: JD requires "
                f"{', '.join(sorted(required_degrees))}; profile lists {', '.join(sorted(profile_degrees))}."
            )

    required_batches = _required_batches(normalized_jd)
    profile_batches = _profile_batches(profile)
    if required_batches:
        matched_batch = sorted(required_batches & profile_batches)
        if matched_batch:
            matched_points.append(f"Graduating batch matches: {', '.join(str(y) for y in matched_batch)}.")
        else:
            message = (
                "Graduating batch mismatch: JD requires "
                f"{', '.join(str(y) for y in sorted(required_batches))}; profile lists "
                f"{', '.join(str(y) for y in sorted(profile_batches)) or 'no graduation year'}."
            )
            if _has_specific_batch_constraint(normalized_jd):
                blocking_issues.append(message)
            else:
                warnings.append(message)

    min_score = _minimum_marks_or_cgpa(normalized_jd)
    if min_score:
        profile_score = _profile_score(profile)
        if profile_score is None:
            warnings.append(f"JD mentions minimum {min_score[0]} of {min_score[1]}, but profile has no comparable GPA/marks.")
        elif _score_meets(profile_score, min_score):
            matched_points.append(f"Academic score meets stated minimum {min_score[0]} {min_score[1]}.")
        else:
            blocking_issues.append(
                f"Academic score mismatch: JD requires at least {min_score[0]} {min_score[1]}; profile lists {profile_score[0]} {profile_score[1]}."
            )

    if parsed_jd.required_experience_years is not None:
        profile_years = _infer_years_of_experience(profile)
        required_years = parsed_jd.required_experience_years
        if profile_years >= required_years:
            matched_points.append(f"Experience years meet requirement: {profile_years}+ years.")
        else:
            blocking_issues.append(
                f"Experience mismatch: JD requires {required_years}+ years; profile shows about {profile_years} years."
            )

    if parsed_jd.location and _looks_location_required(normalized_jd):
        profile_location = (profile.contact.location or "").strip()
        if profile_location and _normalize(parsed_jd.location) in _normalize(profile_location):
            matched_points.append(f"Location matches explicit JD location: {parsed_jd.location}.")
        else:
            warnings.append(
                f"JD appears location-specific ({parsed_jd.location}); profile location is {profile_location or 'not listed'}."
            )

    if _freshers_only(normalized_jd) and profile.work_experience:
        blocking_issues.append("JD says freshers only, but profile includes work experience.")

    if _no_backlog(normalized_jd):
        if _profile_mentions_backlog(profile):
            blocking_issues.append("JD excludes backlogs, and profile appears to mention backlog.")
        else:
            warnings.append("JD requires no active backlogs; profile does not explicitly verify backlog status.")

    if blocking_issues:
        status = "hard_mismatch"
    elif warnings:
        status = "partial_match"
    else:
        status = "match"

    return EligibilityResult(
        status=status,
        blocking_issues=_dedupe(blocking_issues),
        warnings=_dedupe(warnings),
        matched_points=_dedupe(matched_points),
    )


def _jd_text(parsed_jd: ParsedJD) -> str:
    parts = [
        parsed_jd.raw_text,
        parsed_jd.required_education or "",
        " ".join(req.text for req in parsed_jd.requirements),
        " ".join(parsed_jd.required_skills),
    ]
    return " ".join(part for part in parts if part)


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


def _profile_branches(profile: MasterProfile) -> set[str]:
    fields = " ".join(
        " ".join(part for part in [edu.degree, edu.field_of_study or "", edu.institution] if part)
        for edu in profile.education
    )
    normalized = _normalize(fields)
    return {branch for branch, aliases in _BRANCH_ALIASES.items() if any(alias in normalized for alias in aliases)}


def _required_branches(normalized_jd: str) -> set[str]:
    if not any(term in normalized_jd for term in ("branch", "discipline", "mechanical", "automobile", "electrical", "electronics", "civil", "computer science", "cse")):
        return set()
    branches = {
        branch
        for branch, aliases in _BRANCH_ALIASES.items()
        if any(re.search(rf"\b{re.escape(alias)}\b", normalized_jd) for alias in aliases)
    }
    return branches


def _match_any_branch(profile_branches: set[str], required_branches: set[str]) -> str | None:
    for branch in sorted(profile_branches & required_branches):
        return branch
    return None


def _profile_degrees(profile: MasterProfile) -> set[str]:
    text = _normalize(" ".join(edu.degree for edu in profile.education))
    return {level for level, terms in _DEGREE_TERMS.items() if any(term in text for term in terms)}


def _required_degrees(normalized_jd: str, required_education: str | None) -> set[str]:
    text = f"{normalized_jd} {_normalize(required_education)}"
    return {level for level, terms in _DEGREE_TERMS.items() if any(term in text for term in terms)}


def _required_batches(normalized_jd: str) -> set[int]:
    if "batch" not in normalized_jd and "graduat" not in normalized_jd and "passing" not in normalized_jd:
        return set()
    years = {int(year) for year in re.findall(r"\b(20[1-4][0-9])\b", normalized_jd)}
    return {year for year in years if 2010 <= year <= 2049}


def _profile_batches(profile: MasterProfile) -> set[int]:
    years: set[int] = set()
    for edu in profile.education:
        for value in (edu.end_date, edu.start_date):
            match = re.search(r"\b(20[1-4][0-9])\b", value or "")
            if match:
                years.add(int(match.group(1)))
                break
    return years


def _has_specific_batch_constraint(normalized_jd: str) -> bool:
    return bool(re.search(r"\b(specific|only|eligible|must)\b.{0,40}\bbatch\b|\bbatch\b.{0,40}\b(only|eligible|must)\b", normalized_jd))


def _minimum_marks_or_cgpa(normalized_jd: str) -> tuple[float, str] | None:
    cgpa = re.search(r"(?:minimum|min|at least)?\s*(\d+(?:\.\d+)?)\s*(?:/10)?\s*cgpa", normalized_jd)
    if cgpa:
        return float(cgpa.group(1)), "cgpa"
    percent = re.search(r"(?:minimum|min|at least)?\s*(\d+(?:\.\d+)?)\s*%", normalized_jd)
    if percent:
        return float(percent.group(1)), "percent"
    return None


def _profile_score(profile: MasterProfile) -> tuple[float, str] | None:
    for edu in profile.education:
        if not edu.gpa:
            continue
        text = edu.gpa.lower()
        number = re.search(r"\d+(?:\.\d+)?", text)
        if not number:
            continue
        value = float(number.group(0))
        if "%" in text or value > 10:
            return value, "percent"
        return value, "cgpa"
    return None


def _score_meets(profile_score: tuple[float, str], minimum: tuple[float, str]) -> bool:
    profile_value, profile_unit = profile_score
    min_value, min_unit = minimum
    if profile_unit == min_unit:
        return profile_value >= min_value
    if profile_unit == "cgpa" and min_unit == "percent":
        return profile_value * 10 >= min_value
    if profile_unit == "percent" and min_unit == "cgpa":
        return profile_value / 10 >= min_value
    return False


def _infer_years_of_experience(profile: MasterProfile) -> int:
    starts: list[date] = []
    ends: list[date] = []
    for exp in profile.work_experience:
        start = _parse_partial_date(exp.start_date)
        end = date.today() if exp.is_current else _parse_partial_date(exp.end_date)
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    if not starts or not ends:
        return 0
    days = (max(ends) - min(starts)).days
    return max(days // 365, 0)


def _parse_partial_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        if re.fullmatch(r"\d{4}", value):
            return date(int(value), 1, 1)
        if re.fullmatch(r"\d{4}-\d{2}", value):
            year, month = value.split("-")
            return date(int(year), int(month), 1)
        return date.fromisoformat(value)
    except ValueError:
        return None


def _looks_location_required(normalized_jd: str) -> bool:
    return any(marker in normalized_jd for marker in ("work location", "job location", "must be located", "onsite", "on-site", "hybrid"))


def _freshers_only(normalized_jd: str) -> bool:
    return bool(re.search(r"\bfreshers?\s+only\b|\bonly\s+freshers?\b", normalized_jd))


def _no_backlog(normalized_jd: str) -> bool:
    return bool(re.search(r"\bno\s+(?:active\s+)?backlogs?\b|\bwithout\s+backlogs?\b", normalized_jd))


def _profile_mentions_backlog(profile: MasterProfile) -> bool:
    text = _normalize(
        " ".join(
            [
                profile.summary or "",
                " ".join(profile.custom_sections.get("Notes", [])),
                " ".join(award.description or "" for award in profile.awards),
            ]
        )
    )
    return "backlog" in text


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
