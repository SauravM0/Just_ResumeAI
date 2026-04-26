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

PREFERRED_SECTION_HINTS = (
    "preferred qualifications",
    "preferred skills",
    "nice to have",
    "nice-to-have",
    "bonus skills",
    "good to have",
    "desired qualifications",
    "plus",
    "pluses",
)

REQUIRED_OVERRIDE_HINTS = (
    "must have",
    "required",
    "mandatory",
    "minimum requirement",
)

SOFT_SKILL_HINTS = (
    "communication",
    "collaboration",
    "leadership",
    "teamwork",
    "interpersonal",
    "presentation",
    "stakeholder management",
    "written communication",
    "verbal communication",
)

EDUCATION_PATTERNS = (
    r"\bbachelor(?:'s)? degree\b",
    r"\bmaster(?:'s)? degree\b",
    r"\bphd\b",
    r"\bhigh school diploma\b",
)


def analyze_jd_without_ai(raw_text: str) -> ParsedJD:
    lines = _meaningful_lines(raw_text)
    lower_text = raw_text.lower()

    title, company = _extract_title_and_company(lines, raw_text)
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
        r"\b([A-Z][A-Za-z.'-]*(?:[ ][A-Z][A-Za-z.'-]*)*,[ ]*[A-Z][A-Za-z.'-]*(?:[ ][A-Z][A-Za-z.'-]*)*)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_text, re.IGNORECASE)
        if match:
            return match.group(1) if match.lastindex else match.group(0)
    return None


def _meaningful_lines(raw_text: str) -> list[str]:
    """Return trimmed, non-empty lines, skipping decorative separators."""
    lines: list[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.fullmatch(r"[-_=]{3,}", line):
            continue
        lines.append(line)
    return lines


def _looks_like_location(line: str) -> bool:
    lower = line.lower()
    if any(token in lower for token in ("remote", "hybrid", "onsite", "on-site", "location")):
        return True
    if re.search(r"\b[A-Za-z .'-]+,\s*[A-Z]{2}\b", line):
        return True
    if re.search(r"\b[A-Za-z .'-]+,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", line):
        return True
    if re.search(r"\b(united states|usa|uk|canada|india|germany|australia)\b", lower):
        return True
    return False


def _looks_like_title_line(line: str) -> bool:
    lower = line.lower()
    if len(line) > 100:
        return False
    if any(token in lower for token in ("job description", "about us", "overview", "summary", "responsibilities")):
        return False
    title_tokens = (
        "engineer", "developer", "manager", "analyst", "scientist", "designer", "specialist",
        "consultant", "architect", "administrator", "director", "lead", "intern", "coordinator",
        "officer", "associate", "recruiter", "writer",
    )
    return any(token in lower for token in title_tokens)


def _looks_like_company_line(line: str) -> bool:
    lower = line.lower()
    if len(line) > 80 or _looks_like_location(line):
        return False
    if any(token in lower for token in ("requirements", "qualifications", "responsibilities", "about", "overview")):
        return False
    if re.search(r"\b(inc|llc|ltd|corp|corporation|company|technologies|systems|labs|group)\b", lower):
        return True
    if 1 <= len(line.split()) <= 6 and not line.endswith(":"):
        return True
    return False


def _extract_title_and_company(lines: list[str], raw_text: str) -> tuple[str, str | None]:
    title = "Untitled Role"
    company: str | None = None

    header_lines = lines[:6]
    if header_lines:
        first = header_lines[0]
        if _looks_like_title_line(first):
            title = first
            if len(header_lines) > 1 and _looks_like_company_line(header_lines[1]):
                company = header_lines[1]
        else:
            for line in header_lines:
                if _looks_like_title_line(line):
                    title = line
                    break
            if title == "Untitled Role" and len(first) <= 80:
                title = first

    if not company:
        company = _extract_company(lines, raw_text)

    return title, company


def _extract_seniority(lower_text: str) -> SeniorityLevel:
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, lower_text):
            return level
    return SeniorityLevel.UNKNOWN


def _extract_requirements(lines: list[str]) -> list[JDRequirement]:
    requirements: list[JDRequirement] = []
    collecting = False
    section_mode = "neutral"

    for line in lines:
        normalized = line.lower()
        if _is_heading_line(line):
            if any(hint in normalized for hint in RESPONSIBILITY_HINTS):
                collecting = False
                section_mode = "neutral"
                continue
            if any(hint in normalized for hint in PREFERRED_SECTION_HINTS):
                collecting = True
                section_mode = "preferred"
                continue
            if any(hint in normalized for hint in REQUIREMENT_HINTS):
                collecting = True
                section_mode = "required"
                continue

        if not collecting:
            continue

        text = line.lstrip("-*\u2022 ").strip()
        if len(text) < 8:
            continue

        is_required = _classify_requirement_item(text, section_mode)
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
        if _is_heading_line(line) and any(hint in normalized for hint in RESPONSIBILITY_HINTS):
            collecting = True
            continue
        if collecting and _is_heading_line(line) and any(hint in normalized for hint in REQUIREMENT_HINTS):
            collecting = False
            continue

        if not collecting:
            continue

        text = line.lstrip("-*\u2022 ").strip()
        if len(text) >= 8:
            responsibilities.append(text)

    return _dedupe_strings(responsibilities)[:12]


def _extract_skills(lower_text: str, requirements: list[JDRequirement]) -> tuple[list[str], list[str]]:
    matched_skills: dict[str, bool] = {}

    for skill in sorted(COMMON_SKILLS):
        if skill not in lower_text:
            continue

        normalized_skill = _normalize_skill_name(skill)
        preferred = False

        for requirement in requirements:
            if skill in requirement.text.lower():
                preferred = preferred or not requirement.is_required

        existing_preferred = matched_skills.get(normalized_skill)
        if existing_preferred is None:
            matched_skills[normalized_skill] = preferred
        else:
            matched_skills[normalized_skill] = existing_preferred and preferred

    required = sorted(skill for skill, is_preferred in matched_skills.items() if not is_preferred)
    preferred = sorted(skill for skill, is_preferred in matched_skills.items() if is_preferred)
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
    patterns = [
        r"(\d+)\s*[-–]\s*(\d+)\+?\s+years?",
        r"(?:minimum|min\.?)\s+(\d+)\+?\s+years?",
        r"at least\s+(\d+)\+?\s+years?",
        r"(\d+)\+?\s+years?(?:\s+of\s+experience)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, lower_text)
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
    if any(token in lower for token in SOFT_SKILL_HINTS):
        return "soft_skill"
    if any(token in lower for token in ("year", "years", "experience")):
        if any(token in lower for token in COMMON_SKILLS):
            return "technical_skill"
        return "experience"
    if any(token in lower for token in COMMON_SKILLS):
        return "technical_skill"
    return None


def _is_heading_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith(("-", "*", "\u2022")):
        return False
    if stripped.endswith(":"):
        return True
    if len(stripped.split()) <= 6:
        normalized = stripped.lower()
        return any(
            hint in normalized
            for hint in REQUIREMENT_HINTS + RESPONSIBILITY_HINTS + PREFERRED_SECTION_HINTS
        )
    return False


def _classify_requirement_item(text: str, section_mode: str = "neutral") -> bool:
    lower = text.lower()
    if any(hint in lower for hint in REQUIRED_OVERRIDE_HINTS):
        return True
    if any(hint in lower for hint in NICE_TO_HAVE_HINTS):
        return False
    if section_mode == "preferred":
        return False
    return True


def _normalize_skill_name(skill: str) -> str:
    overrides = {
        "node": "Node.js",
        "node.js": "Node.js",
        "apis": "APIs",
        "aws": "AWS",
        "gcp": "GCP",
        "sql": "SQL",
        "html": "HTML",
        "css": "CSS",
        "ai": "AI",
        "power bi": "Power BI",
        "fastapi": "FastAPI",
        "postgresql": "PostgreSQL",
        "mysql": "MySQL",
        "mongodb": "MongoDB",
        "graphql": "GraphQL",
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "react": "React",
        "django": "Django",
        "flask": "Flask",
        "docker": "Docker",
        "kubernetes": "Kubernetes",
        "tableau": "Tableau",
    }
    lower = skill.lower()
    return overrides.get(lower, " ".join(part.upper() if len(part) <= 3 else part.capitalize() for part in lower.split()))


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
