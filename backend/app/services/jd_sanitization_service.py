from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from app.schemas.jd import JDKeyword, JDRequirement, ParsedJD
from app.schemas.resume import ResumeRecommendation


INVALID_JD_USER_MESSAGE = (
    "The pasted job description appears invalid or contaminated. "
    "Please paste the actual role description."
)


class InvalidJobDescriptionError(ValueError):
    """Raised when JD intake is a placeholder or contaminated paste."""


class ResumeContaminationError(ValueError):
    """Raised when JD boilerplate reaches a resume or render artifact."""


@dataclass(frozen=True)
class JDSanitizationResult:
    clean_text: str
    dropped_fragments: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_valid_jd: bool = True
    fatal_errors: list[str] = field(default_factory=list)

    @property
    def cleaned_text(self) -> str:
        """Compatibility alias for callers added before the public result shape."""
        return self.clean_text


_DROP_LINE_PREFIXES = (
    "ats keywords:",
    "metadata:",
    "tags:",
    "apply now",
    "job id",
    "ref id",
    "invalid job description",
    "invalid job description content",
    "requisition id",
    "equal opportunity",
    "about us",
    "company description",
)

_BOILERPLATE_PHRASES = (
    "We are seeking",
    "The ideal candidate",
    "Responsibilities include",
    "Equal opportunity employer",
    "Apply now",
    "Job Description Content",
    "Invalid Job Description Content",
    "Join our team",
    "Apply today",
    "About the company",
    "Benefits include",
)

_SLUG_MAPPING = {
    "asp-net": "ASP.NET",
    "react-js": "React.js",
    "next-js": "Next.js",
    "node-js": "Node.js",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "ajax-asynchronous-javascript-and-xml": "AJAX",
}

_ALLOWED_HYPHENATED_SKILLS = {
    "ci-cd": "CI/CD",
    "full-stack": "full-stack",
    "front-end": "front-end",
    "back-end": "back-end",
    "end-to-end": "end-to-end",
    "object-oriented": "object-oriented",
}

_URL_LIKE_TOKEN_RE = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+){3,}\b", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_LABEL_RE = re.compile(r"^\s*(ats keywords|metadata|tags|job id|ref id|requisition id)\s*:\s*", re.IGNORECASE)
_EXPLICIT_INVALID_JD_RE = re.compile(r"\binvalid job description(?: content)?\b", re.IGNORECASE)
_FORBIDDEN_FINAL_PHRASES = (
    "Invalid Job Description Content",
    "Job Description Content",
    "We are seeking",
    "The ideal candidate",
    "Apply now",
    "ATS Keywords",
    "Responsibilities include",
    "Equal opportunity employer",
    "metadata:",
    "tags:",
    "ref id",
)

_GENERIC_ATS_NOISE_TERMS = {
    "academy",
    "academic",
    "afterwards",
    "alumni",
    "apply",
    "competitive",
    "degree",
    "how",
    "join",
    "others",
    "others competitive",
    "stage",
    "then",
    "what",
}

_GENERIC_SINGLE_WORD_TERMS = {
    *_GENERIC_ATS_NOISE_TERMS,
    "about",
    "benefits",
    "candidate",
    "company",
    "description",
    "education",
    "employer",
    "location",
    "overview",
    "qualification",
    "qualifications",
    "requirement",
    "requirements",
    "responsibility",
    "responsibilities",
    "role",
}


def sanitize_jd_text(raw_text: str | None) -> JDSanitizationResult:
    """Clean job-board/web-page noise before the JD reaches AI or fallback parsers."""
    dropped: list[str] = []
    warnings: list[str] = []
    text = str(raw_text or "")
    fatal_errors: list[str] = []

    if _EXPLICIT_INVALID_JD_RE.search(html.unescape(text)):
        fatal_errors.append("Job description contains an invalid placeholder marker.")

    before = text
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    if text != before:
        dropped.append("script/style HTML content")

    text = html.unescape(text)
    text = _HTML_TAG_RE.sub("\n", text)

    kept_lines: list[str] = []
    for raw_line in text.splitlines():
        line = _normalize_spaces(raw_line)
        if not line:
            continue
        if _should_drop_line(line):
            dropped.append(line[:180])
            continue
        kept_lines.append(line)
    text = "\n".join(kept_lines)

    for phrase in _BOILERPLATE_PHRASES:
        pattern = re.compile(rf"\b{re.escape(phrase)}\b[:,]?\s*", re.IGNORECASE)
        if pattern.search(text):
            dropped.append(phrase)
            text = pattern.sub("", text)

    text = _normalize_slug_terms(text, dropped)
    text = _drop_long_url_like_tokens(text, dropped)
    text = _normalize_lines(text)

    if dropped:
        warnings.append("Job description sanitization removed boilerplate and URL-like fragments.")

    if not text:
        fatal_errors.append("Job description has no role-specific content after sanitization.")

    return JDSanitizationResult(
        clean_text=text,
        dropped_fragments=_dedupe(dropped)[:40],
        warnings=warnings,
        is_valid_jd=not fatal_errors,
        fatal_errors=_dedupe(fatal_errors),
    )


def require_valid_jd_text(raw_text: str | None) -> JDSanitizationResult:
    """Sanitize a JD and reject known placeholder/contaminated intake."""
    result = sanitize_jd_text(raw_text)
    if not result.is_valid_jd:
        raise InvalidJobDescriptionError(INVALID_JD_USER_MESSAGE)
    return result


def sanitize_parsed_jd(
    parsed_jd: ParsedJD,
    *,
    source_text: str | None = None,
    sanitization: JDSanitizationResult | None = None,
) -> ParsedJD:
    """Normalize structured JD fields so boilerplate cannot become ATS terms."""
    result = parsed_jd.model_copy(deep=True)
    text_result = sanitization or sanitize_jd_text(source_text or result.raw_text)
    result.raw_text = text_result.clean_text

    result.job_title = _clean_field(result.job_title) or "Untitled Role"
    result.company = _clean_optional(result.company)
    result.location = _clean_optional(result.location)
    result.department = _clean_optional(result.department)
    result.industry = _clean_optional(result.industry)
    result.required_education = _clean_optional(result.required_education)

    result.responsibilities = _clean_list(result.responsibilities, max_items=25, max_words=18)
    result.required_skills = _clean_skill_list(result.required_skills)
    result.preferred_skills = _clean_skill_list(result.preferred_skills)
    result.tools_platforms = _clean_skill_list(result.tools_platforms)
    result.programming_languages = _clean_skill_list(result.programming_languages)
    result.frameworks = _clean_skill_list(result.frameworks)
    result.databases = _clean_skill_list(result.databases)
    result.cloud_devops_tools = _clean_skill_list(result.cloud_devops_tools)
    result.domain_platform_terms = _clean_skill_list(result.domain_platform_terms)
    result.deployment_environment_terms = _clean_skill_list(result.deployment_environment_terms)
    result.mobile_platform_terms = _clean_skill_list(result.mobile_platform_terms)
    result.soft_skills = _clean_skill_list(result.soft_skills)
    result.important_exact_phrases = _clean_list(result.important_exact_phrases, max_items=30, max_words=8)

    cleaned_requirements: list[JDRequirement] = []
    for requirement in result.requirements:
        cleaned = _clean_field(requirement.text)
        if _is_noise_term(cleaned) or _word_count(cleaned) > 24:
            continue
        cleaned_requirements.append(requirement.model_copy(update={"text": cleaned}))
    result.requirements = _dedupe_requirements(cleaned_requirements)[:40]

    cleaned_keywords: list[JDKeyword] = []
    for keyword in result.keywords:
        cleaned = _clean_term(keyword.keyword, skill_like=True)
        if _is_noise_term(cleaned) or _word_count(cleaned) > 6:
            continue
        cleaned_keywords.append(keyword.model_copy(update={"keyword": cleaned}))
    result.keywords = _dedupe_keywords(cleaned_keywords)[:80]

    warnings = [*result.quality_warnings, *text_result.warnings]
    result.quality_warnings = _dedupe(warnings)
    return result


def clean_jd_keyword_terms(values: list[str] | tuple[str, ...] | None, *, max_items: int = 80) -> list[str]:
    """Return clean ATS keyword terms, dropping job-board and navigation noise."""
    cleaned: list[str] = []
    for value in values or []:
        term = _clean_term(value, skill_like=True)
        if _is_noise_term(term) or _word_count(term) > 6:
            continue
        cleaned.append(term)
    return _dedupe(cleaned)[:max_items]


def assert_parsed_jd_safe(parsed_jd: ParsedJD) -> None:
    """Fail closed if forbidden paste fragments survive ParsedJD cleanup."""
    matches = _find_forbidden_matches(_parsed_jd_text_fields(parsed_jd))
    if matches:
        raise InvalidJobDescriptionError(INVALID_JD_USER_MESSAGE)


def assert_resume_recommendation_safe(recommendation: ResumeRecommendation) -> None:
    """Fail closed before a recommendation can be rendered or exported."""
    matches = _find_forbidden_matches(_resume_text_fields(recommendation))
    if matches:
        raise ResumeContaminationError(_format_contamination_error(matches))


def assert_render_text_safe(text: str | None, *, artifact: str) -> None:
    """Fail closed when final LaTeX or plain text contains forbidden JD paste text."""
    matches = _find_forbidden_matches([(artifact, text or "")])
    if matches:
        raise ResumeContaminationError(_format_contamination_error(matches))


def recommendation_to_plain_text(recommendation: ResumeRecommendation) -> str:
    """Deterministic text corpus mirroring all user-visible resume fields."""
    return "\n".join(value for _, value in _resume_text_fields(recommendation) if value)


def _should_drop_line(line: str) -> bool:
    lowered = line.casefold().strip()
    return any(lowered.startswith(prefix) for prefix in _DROP_LINE_PREFIXES)


def _normalize_slug_terms(text: str, dropped: list[str]) -> str:
    for slug, canonical in {**_ALLOWED_HYPHENATED_SKILLS, **_SLUG_MAPPING}.items():
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(slug)}(?![A-Za-z0-9])", re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(canonical, text)
    return text


def _drop_long_url_like_tokens(text: str, dropped: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        key = token.casefold()
        if key in _SLUG_MAPPING or key in _ALLOWED_HYPHENATED_SKILLS:
            return token
        dropped.append(token)
        return " "

    return _URL_LIKE_TOKEN_RE.sub(replace, text)


def _clean_list(values: list[str], *, max_items: int, max_words: int) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        term = _clean_field(value)
        if _is_noise_term(term) or _word_count(term) > max_words:
            continue
        cleaned.append(term)
    return _dedupe(cleaned)[:max_items]


def _clean_skill_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        term = _clean_term(value, skill_like=True)
        if _is_noise_term(term) or _word_count(term) > 4:
            continue
        cleaned.append(term)
    return _dedupe(cleaned)[:40]


def _clean_term(value: str | None, *, skill_like: bool = False) -> str:
    text = _clean_field(value)
    text = _LABEL_RE.sub("", text).strip()
    text = _normalize_slug_terms(text, [])
    text = _drop_long_url_like_tokens(text, [])
    text = _normalize_spaces(text).strip(" ,.;:-")
    if skill_like:
        text = _strip_boilerplate_prefix(text)
    return text


def _clean_field(value: str | None) -> str:
    result = sanitize_jd_text(str(value or "")).clean_text
    return _normalize_spaces(result).strip(" ,.;:-")


def _clean_optional(value: str | None) -> str | None:
    cleaned = _clean_field(value)
    return cleaned or None


def _strip_boilerplate_prefix(value: str) -> str:
    text = value
    for phrase in _BOILERPLATE_PHRASES:
        text = re.sub(rf"^\s*{re.escape(phrase)}\b[:,]?\s*", "", text, flags=re.IGNORECASE)
    return text.strip(" ,.;:-")


def _is_noise_term(value: str | None) -> bool:
    text = _normalize_spaces(value).casefold()
    if not text:
        return True
    if text in _GENERIC_ATS_NOISE_TERMS:
        return True
    if _word_count(text) == 1 and text in _GENERIC_SINGLE_WORD_TERMS:
        return True
    if any(text.startswith(prefix.strip(":")) for prefix in _DROP_LINE_PREFIXES):
        return True
    if any(phrase.casefold() in text for phrase in _BOILERPLATE_PHRASES):
        return True
    if re.search(r"https?://|www\.|/jobs/|utm_|job[-_]?id|requisition", text):
        return True
    if _URL_LIKE_TOKEN_RE.fullmatch(text) and text not in _SLUG_MAPPING and text not in _ALLOWED_HYPHENATED_SKILLS:
        return True
    return False


def _normalize_spaces(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_lines(value: str | None) -> str:
    lines = [_normalize_spaces(line) for line in str(value or "").splitlines()]
    return "\n".join(line for line in lines if line)


def _word_count(value: str) -> int:
    return len([part for part in value.split() if part])


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _normalize_spaces(value)
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _dedupe_requirements(requirements: list[JDRequirement]) -> list[JDRequirement]:
    seen: set[str] = set()
    result: list[JDRequirement] = []
    for requirement in requirements:
        key = requirement.text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(requirement)
    return result


def _dedupe_keywords(keywords: list[JDKeyword]) -> list[JDKeyword]:
    by_key: dict[str, JDKeyword] = {}
    importance_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    for keyword in keywords:
        key = keyword.keyword.casefold()
        existing = by_key.get(key)
        if not existing:
            by_key[key] = keyword
            continue
        if importance_order.get(keyword.importance, 1) > importance_order.get(existing.importance, 1):
            existing.importance = keyword.importance
        existing.frequency = max(existing.frequency, keyword.frequency)
    return list(by_key.values())


def _parsed_jd_text_fields(parsed_jd: ParsedJD) -> list[tuple[str, str]]:
    fields = [
        ("parsed_jd.job_title", parsed_jd.job_title),
        ("parsed_jd.company", parsed_jd.company or ""),
        ("parsed_jd.location", parsed_jd.location or ""),
        ("parsed_jd.department", parsed_jd.department or ""),
        ("parsed_jd.industry", parsed_jd.industry or ""),
        ("parsed_jd.required_education", parsed_jd.required_education or ""),
        ("parsed_jd.raw_text", parsed_jd.raw_text or ""),
    ]
    fields.extend((f"parsed_jd.responsibilities.{index}", value) for index, value in enumerate(parsed_jd.responsibilities))
    fields.extend((f"parsed_jd.required_skills.{index}", value) for index, value in enumerate(parsed_jd.required_skills))
    fields.extend((f"parsed_jd.preferred_skills.{index}", value) for index, value in enumerate(parsed_jd.preferred_skills))
    fields.extend((f"parsed_jd.requirements.{index}", item.text) for index, item in enumerate(parsed_jd.requirements))
    fields.extend((f"parsed_jd.keywords.{index}", item.keyword) for index, item in enumerate(parsed_jd.keywords))
    for field_name in (
        "tools_platforms",
        "programming_languages",
        "frameworks",
        "databases",
        "cloud_devops_tools",
        "domain_platform_terms",
        "deployment_environment_terms",
        "mobile_platform_terms",
        "soft_skills",
        "important_exact_phrases",
    ):
        fields.extend(
            (f"parsed_jd.{field_name}.{index}", value)
            for index, value in enumerate(getattr(parsed_jd, field_name))
        )
    return fields


def _resume_text_fields(recommendation: ResumeRecommendation) -> list[tuple[str, str]]:
    fields = [
        ("recommendation.target_title", recommendation.target_title or ""),
        ("recommendation.summary", recommendation.summary or ""),
    ]
    fields.extend((f"recommendation.skills.{index}.{skill_index}", skill)
                  for index, group in enumerate(recommendation.skills)
                  for skill_index, skill in enumerate(group.skills))
    fields.extend((f"recommendation.skills.{index}.category", group.category)
                  for index, group in enumerate(recommendation.skills))
    fields.extend((f"recommendation.experience.{index}.title", entry.title)
                  for index, entry in enumerate(recommendation.experience))
    fields.extend((f"recommendation.experience.{index}.company", entry.company)
                  for index, entry in enumerate(recommendation.experience))
    fields.extend((f"recommendation.experience.{index}.location", entry.location or "")
                  for index, entry in enumerate(recommendation.experience))
    fields.extend((f"recommendation.experience.{index}.date", f"{entry.start_date} {entry.end_date or ''}")
                  for index, entry in enumerate(recommendation.experience))
    fields.extend((f"recommendation.experience.{index}.bullets.{bullet_index}", bullet.text)
                  for index, entry in enumerate(recommendation.experience)
                  for bullet_index, bullet in enumerate(entry.bullets))
    fields.extend((f"recommendation.projects.{index}.name", entry.name)
                  for index, entry in enumerate(recommendation.projects))
    fields.extend((f"recommendation.projects.{index}.description", entry.description or "")
                  for index, entry in enumerate(recommendation.projects))
    fields.extend((f"recommendation.projects.{index}.technologies.{tech_index}", tech)
                  for index, entry in enumerate(recommendation.projects)
                  for tech_index, tech in enumerate(entry.technologies))
    fields.extend((f"recommendation.projects.{index}.bullets.{bullet_index}", bullet.text)
                  for index, entry in enumerate(recommendation.projects)
                  for bullet_index, bullet in enumerate(entry.bullets))
    fields.extend((f"recommendation.custom_sections.{index}.items.{item_index}", item)
                  for index, section in enumerate(recommendation.custom_sections)
                  for item_index, item in enumerate(section.items))
    fields.extend((f"recommendation.custom_sections.{index}.title", section.title)
                  for index, section in enumerate(recommendation.custom_sections))
    fields.extend((f"recommendation.education.{index}.institution", item.institution)
                  for index, item in enumerate(recommendation.education))
    fields.extend((f"recommendation.education.{index}.degree", item.degree)
                  for index, item in enumerate(recommendation.education))
    fields.extend((f"recommendation.education.{index}.field_of_study", item.field_of_study or "")
                  for index, item in enumerate(recommendation.education))
    fields.extend((f"recommendation.education.{index}.coursework.{course_index}", course)
                  for index, item in enumerate(recommendation.education)
                  for course_index, course in enumerate(item.relevant_coursework))
    fields.extend((f"recommendation.certifications.{index}.name", item.name)
                  for index, item in enumerate(recommendation.certifications))
    fields.extend((f"recommendation.certifications.{index}.issuing_org", item.issuing_org or "")
                  for index, item in enumerate(recommendation.certifications))
    fields.extend((f"recommendation.achievements.{index}.title", item.title)
                  for index, item in enumerate(recommendation.achievements))
    fields.extend((f"recommendation.achievements.{index}.description", item.description or "")
                  for index, item in enumerate(recommendation.achievements))
    fields.extend((f"recommendation.achievements.{index}.issuer", item.issuer or "")
                  for index, item in enumerate(recommendation.achievements))
    fields.extend((f"recommendation.awards.{index}.title", item.title)
                  for index, item in enumerate(recommendation.awards))
    fields.extend((f"recommendation.awards.{index}.description", item.description or "")
                  for index, item in enumerate(recommendation.awards))
    fields.extend((f"recommendation.awards.{index}.issuer", item.issuer or "")
                  for index, item in enumerate(recommendation.awards))
    return fields


def _find_forbidden_matches(fields: list[tuple[str, str]]) -> list[tuple[str, str]]:
    matches: list[tuple[str, str]] = []
    for path, value in fields:
        for phrase in _FORBIDDEN_FINAL_PHRASES:
            if re.search(rf"\b{re.escape(phrase)}\b", value or "", re.IGNORECASE):
                matches.append((path, phrase))
    return matches


def _format_contamination_error(matches: list[tuple[str, str]]) -> str:
    path, phrase = matches[0]
    return f"Resume content blocked because forbidden JD text reached {path}: {phrase}."
