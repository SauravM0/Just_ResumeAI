"""
Deterministic fallback parser for JD analysis when Gemini is unavailable.
"""

from __future__ import annotations

import re
from collections import Counter

from app.schemas.jd import JDKeyword, JDQualityLevel, JDRequirement, ParsedJD, SeniorityLevel

COMMON_SKILLS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "node.js",
    "node",
    "sql",
    "postgresql",
    "mysql",
    "mongodb",
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "git",
    "linux",
    "fastapi",
    "django",
    "flask",
    "rest",
    "apis",
    "graphql",
    "html",
    "css",
    "tailwind",
    "excel",
    "power bi",
    "tableau",
    "machine learning",
    "ai",
    "communication",
    "leadership",
    "agile",
    "scrum",
}

SENIORITY_PATTERNS: list[tuple[str, SeniorityLevel]] = [
    (r"\bc[-\s]?level\b|\bchief\b", SeniorityLevel.C_LEVEL),
    (r"\bvp\b|\bvice president\b", SeniorityLevel.VP),
    (r"\bdirector\b", SeniorityLevel.DIRECTOR),
    (r"\bprincipal\b", SeniorityLevel.PRINCIPAL),
    (r"\bstaff\b", SeniorityLevel.STAFF),
    (r"\blead\b", SeniorityLevel.LEAD),
    (r"\bsenior\b|\bsr\.?\b", SeniorityLevel.SENIOR),
    (r"\bmid\b|\bmid-level\b", SeniorityLevel.MID),
    (r"\bentry\b|\bjunior\b|\bjr\.?\b", SeniorityLevel.ENTRY),
    (r"\bintern\b|\binternship\b", SeniorityLevel.INTERN),
]

NICE_TO_HAVE_HINTS = (
    "preferred",
    "nice to have",
    "bonus",
    "plus",
    "good to have",
    "desired",
)

REQUIREMENT_HINTS = (
    "required",
    "requirements",
    "qualifications",
    "must have",
    "experience with",
    "proficiency in",
    "skills",
)

RESPONSIBILITY_HINTS = (
    "responsibilities",
    "what you'll do",
    "what you will do",
    "duties",
    "role overview",
)

EDUCATION_PATTERNS = (
    r"\bbachelor(?:'s)? degree\b",
    r"\bmaster(?:'s)? degree\b",
    r"\bphd\b",
    r"\bhigh school diploma\b",
)


def analyze_jd_without_ai(raw_text: str) -> ParsedJD:
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    lower_text = raw_text.lower()

    title = _extract_title(lines)
    company = _extract_company(lines, raw_text)
    location = _extract_location(raw_text)
    seniority = _extract_seniority(lower_text)
    requirements = _extract_requirements(lines)
    responsibilities = _extract_responsibilities(lines)
    required_skills, preferred_skills = _extract_skills(lower_text, requirements)
    keywords = _build_keywords(required_skills, preferred_skills, responsibilities, requirements)
    experience_years = _extract_experience_years(lower_text)
    education = _extract_education(lower_text)
    quality, quality_warnings = _assess_quality(
        title=title,
        requirements=requirements,
        responsibilities=responsibilities,
        skills=required_skills + preferred_skills,
        company=company,
        location=location,
    )

    quality_warnings.insert(
        0,
        "AI provider was temporarily unavailable, so this job description was parsed with a local fallback."
    )

    return ParsedJD(
        job_title=title,
        company=company,
        location=location,
        seniority=seniority,
        department=None,
        industry=None,
        requirements=requirements,
        responsibilities=responsibilities,
        keywords=keywords,
        required_skills=required_skills,
        preferred_skills=preferred_skills,
        required_experience_years=experience_years,
        required_education=education,
        quality=quality,
        quality_warnings=quality_warnings,
        raw_text=raw_text,
    )


def _extract_title(lines: list[str]) -> str:
    for line in lines[:5]:
        if len(line) > 80:
            continue
        if any(token in line.lower() for token in ("job description", "about us", "overview")):
            continue
        return line
    return "Untitled Role"


def _extract_company(lines: list[str], raw_text: str) -> str | None:
    for line in lines[:10]:
        match = re.search(r"(?:company|employer)\s*:\s*(.+)", line, re.IGNORECASE)
        if match:
            return match.group(1).strip(" -")

    match = re.search(r"\bat\s+([A-Z][A-Za-z0-9&.,' -]{2,60})", raw_text)
    if match:
        return match.group(1).strip()
    return None


def _extract_location(raw_text: str) -> str | None:
    patterns = [
        r"\b(remote|hybrid|on[- ]site)\b",
        r"\blocation\s*:\s*([^\n]+)",
        r"\b([A-Z][a-z]+,\s*[A-Z]{2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            return match.group(1) if match.lastindex else match.group(0)
    return None


def _extract_seniority(lower_text: str) -> SeniorityLevel:
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, lower_text):
            return level
    return SeniorityLevel.UNKNOWN


def _extract_requirements(lines: list[str]) -> list[JDRequirement]:
    requirements: list[JDRequirement] = []
    collecting = False

    for line in lines:
        normalized = line.lower()
        if any(hint in normalized for hint in REQUIREMENT_HINTS):
            collecting = True
            continue
        if collecting and any(hint in normalized for hint in RESPONSIBILITY_HINTS):
            collecting = False

        if not collecting and not line.startswith(("-", "*", "\u2022")):
            continue

        text = line.lstrip("-*\u2022 ").strip()
        if len(text) < 8:
            continue

        is_required = not any(hint in normalized for hint in NICE_TO_HAVE_HINTS)
        category = _categorize_requirement(text)
        requirements.append(
            JDRequirement(text=text, is_required=is_required, category=category)
        )

    return _dedupe_requirements(requirements)[:20]


def _extract_responsibilities(lines: list[str]) -> list[str]:
    responsibilities: list[str] = []
    collecting = False

    for line in lines:
        normalized = line.lower()
        if any(hint in normalized for hint in RESPONSIBILITY_HINTS):
            collecting = True
            continue
        if collecting and any(hint in normalized for hint in REQUIREMENT_HINTS):
            collecting = False

        if not collecting:
            continue

        text = line.lstrip("-*\u2022 ").strip()
        if len(text) >= 8:
            responsibilities.append(text)

    return _dedupe_strings(responsibilities)[:12]


def _extract_skills(lower_text: str, requirements: list[JDRequirement]) -> tuple[list[str], list[str]]:
    requirement_text = " ".join(req.text.lower() for req in requirements)
    matched_skills: list[tuple[str, bool]] = []

    for skill in COMMON_SKILLS:
        if skill in lower_text:
            preferred = skill in requirement_text and any(
                hint in requirement_text for hint in NICE_TO_HAVE_HINTS
            )
            matched_skills.append((skill, preferred))

    required = sorted({skill.title() for skill, is_preferred in matched_skills if not is_preferred})
    preferred = sorted({skill.title() for skill, is_preferred in matched_skills if is_preferred})
    return required[:20], preferred[:20]


def _build_keywords(
    required_skills: list[str],
    preferred_skills: list[str],
    responsibilities: list[str],
    requirements: list[JDRequirement],
) -> list[JDKeyword]:
    keyword_counter: Counter[str] = Counter()

    for skill in required_skills:
        keyword_counter[skill] += 3
    for skill in preferred_skills:
        keyword_counter[skill] += 1

    for sentence in responsibilities + [req.text for req in requirements]:
        for phrase in re.findall(r"\b[A-Za-z][A-Za-z0-9.+#/-]{2,}\b", sentence):
            token = phrase.lower()
            if token in {"the", "and", "for", "with", "you", "our", "will", "are"}:
                continue
            keyword_counter[token] += 1

    keywords: list[JDKeyword] = []
    for keyword, count in keyword_counter.most_common(20):
        importance = "critical" if count >= 3 else "high" if count == 2 else "medium"
        normalized = keyword if any(char.isupper() for char in keyword) else keyword.title()
        keywords.append(
            JDKeyword(keyword=normalized, frequency=max(1, count), importance=importance)
        )

    return keywords


def _extract_experience_years(lower_text: str) -> int | None:
    match = re.search(r"(\d+)\+?\s+years? of experience", lower_text)
    if match:
        return int(match.group(1))
    match = re.search(r"minimum of (\d+)\s+years?", lower_text)
    if match:
        return int(match.group(1))
    return None


def _extract_education(lower_text: str) -> str | None:
    for pattern in EDUCATION_PATTERNS:
        match = re.search(pattern, lower_text)
        if match:
            return match.group(0).title()
    return None


def _assess_quality(
    *,
    title: str,
    requirements: list[JDRequirement],
    responsibilities: list[str],
    skills: list[str],
    company: str | None,
    location: str | None,
) -> tuple[JDQualityLevel, list[str]]:
    warnings: list[str] = []
    score = 0

    if title and title != "Untitled Role":
        score += 1
    else:
        warnings.append("Job title could not be identified confidently.")

    if company:
        score += 1
    else:
        warnings.append("Company name is missing or unclear.")

    if location:
        score += 1
    else:
        warnings.append("Location or work arrangement is missing.")

    if len(requirements) >= 4:
        score += 2
    elif requirements:
        score += 1
        warnings.append("Only a few concrete requirements were identified.")
    else:
        warnings.append("No clear requirement section was found.")

    if responsibilities:
        score += 1
    else:
        warnings.append("Responsibilities were not clearly separated in the JD.")

    if len(skills) >= 4:
        score += 1
    else:
        warnings.append("Only a limited number of skills could be extracted.")

    if score >= 6:
        return JDQualityLevel.STRONG, warnings
    if score >= 3:
        return JDQualityLevel.MODERATE, warnings
    return JDQualityLevel.WEAK, warnings


def _categorize_requirement(text: str) -> str | None:
    lower = text.lower()
    if any(token in lower for token in ("degree", "bachelor", "master", "phd")):
        return "education"
    if "year" in lower or "experience" in lower:
        return "experience"
    if any(token in lower for token in COMMON_SKILLS):
        return "technical_skill"
    if any(token in lower for token in ("communication", "collaboration", "leadership")):
        return "soft_skill"
    return None


def _dedupe_requirements(requirements: list[JDRequirement]) -> list[JDRequirement]:
    seen: set[str] = set()
    deduped: list[JDRequirement] = []
    for requirement in requirements:
        key = requirement.text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(requirement)
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
