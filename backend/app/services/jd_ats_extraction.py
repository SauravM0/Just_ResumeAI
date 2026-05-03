from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.jd import JDKeyword, JDRequirement, ParsedJD


@dataclass(frozen=True)
class TermSpec:
    term: str
    bucket: str
    importance: str = "high"
    aliases: tuple[str, ...] = ()
    preferred_hints: tuple[str, ...] = ()


TERM_SPECS: tuple[TermSpec, ...] = (
    TermSpec("OBDX", "domain_platform_terms", "critical", ("Oracle Banking Digital Experience",)),
    TermSpec("Oracle Banking Digital Experience", "domain_platform_terms", "critical", ("OBDX",)),
    TermSpec("PL/SQL", "programming_languages", "critical", ("PLSQL",)),
    TermSpec("Oracle DB", "databases", "critical", ("Oracle Database", "OracleDB")),
    TermSpec("Java", "programming_languages", "critical"),
    TermSpec("Microservices", "frameworks", "critical"),
    TermSpec("UI/UX", "tools_platforms", "high"),
    TermSpec("DevOps", "cloud_devops_tools", "high"),
    TermSpec("Git", "cloud_devops_tools", "high", ("GIT",)),
    TermSpec("Jenkins", "cloud_devops_tools", "high"),
    TermSpec("CEMLI", "domain_platform_terms", "critical", ("CEMLIs",)),
    TermSpec("CEMLIs", "domain_platform_terms", "critical", ("CEMLI",)),
    TermSpec("Development Workbench", "tools_platforms", "critical"),
    TermSpec("Extensibility", "domain_platform_terms", "high"),
    TermSpec("Non-production environments", "deployment_environment_terms", "high", ("non-production", "non production")),
    TermSpec("DEV", "deployment_environment_terms", "medium"),
    TermSpec("SIT", "deployment_environment_terms", "medium"),
    TermSpec("UAT", "deployment_environment_terms", "medium"),
    TermSpec("iOS", "mobile_platform_terms", "high"),
    TermSpec("Android", "mobile_platform_terms", "high"),
    TermSpec("Mobile App development", "mobile_platform_terms", "high", ("mobile app development",)),
    TermSpec("UK Open Banking", "domain_platform_terms", "high", preferred_hints=("advantage", "preferred", "nice to have")),
    TermSpec("PSD2", "domain_platform_terms", "high"),
    TermSpec("Open Banking APIs", "domain_platform_terms", "high", ("Open Banking API", "banking APIs")),
)

SLASH_SPLITS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Java/Microservices", ("Java", "Microservices")),
    ("iOS/Android", ("iOS", "Android", "Mobile App development")),
    ("PL/SQL", ("PL/SQL",)),
    ("UI/UX", ("UI/UX",)),
)

SOFT_SKILL_TERMS = (
    "communication",
    "collaboration",
    "leadership",
    "teamwork",
    "stakeholder management",
    "problem solving",
    "analytical skills",
)

TITLE_TOKEN_OVERRIDES = {
    "api": "API",
    "apis": "APIs",
    "db": "DB",
    "devops": "DevOps",
    "ios": "iOS",
    "obdx": "OBDX",
    "pl/sql": "PL/SQL",
    "ui/ux": "UI/UX",
    "ux": "UX",
}

COMMON_EXACT_PHRASE_PATTERNS = (
    r"\b[A-Z][A-Za-z0-9.+#]*(?:/[A-Z]?[A-Za-z0-9.+#]+)+\b",
    r"\b(?:Oracle Banking Digital Experience|Development Workbench|Mobile App development|UK Open Banking|Open Banking APIs|Non-production environments)\b",
)


def enrich_parsed_jd_for_ats(parsed_jd: ParsedJD, raw_text: str) -> ParsedJD:
    """Add deterministic ATS extraction without judging candidate evidence."""
    text = raw_text or parsed_jd.raw_text or ""
    parsed_jd.job_title = _clean_job_title(parsed_jd.job_title)

    found = _extract_term_specs(text)
    preferred_terms = {spec.term for spec in found if _is_preferred_context(text, spec)}

    for spec in found:
        _append_unique(getattr(parsed_jd, spec.bucket), spec.term)
        _append_skill(parsed_jd, spec.term, preferred=spec.term in preferred_terms)
        _append_keyword(parsed_jd, spec.term, spec.importance)
        _append_unique(parsed_jd.important_exact_phrases, spec.term)

    for phrase, parts in SLASH_SPLITS:
        if _contains_term(text, phrase):
            _append_keyword(parsed_jd, phrase, "critical" if phrase == "Java/Microservices" else "high")
            _append_unique(parsed_jd.important_exact_phrases, phrase)
            for part in parts:
                matching = next((spec for spec in TERM_SPECS if spec.term == part), None)
                if matching:
                    _append_unique(getattr(parsed_jd, matching.bucket), part)
                _append_skill(parsed_jd, part, preferred=_is_preferred_context(text, TermSpec(part, "")))
                _append_keyword(parsed_jd, part, "critical" if part in {"Java", "Microservices", "PL/SQL"} else "high")
                _append_unique(parsed_jd.important_exact_phrases, part)

    for skill in _extract_soft_skills(text):
        _append_unique(parsed_jd.soft_skills, skill)
        _append_skill(parsed_jd, skill, preferred=_phrase_has_preferred_context(text, skill))
        _append_keyword(parsed_jd, skill, "medium")

    for phrase in _extract_exact_phrases(text):
        _append_unique(parsed_jd.important_exact_phrases, phrase)
        _append_keyword(parsed_jd, phrase, "high")

    _promote_requirement_terms(parsed_jd, preferred_terms)
    parsed_jd.required_skills = _dedupe_preserve(parsed_jd.required_skills)[:40]
    parsed_jd.preferred_skills = _dedupe_preserve(parsed_jd.preferred_skills)[:40]
    parsed_jd.keywords = _dedupe_keywords(parsed_jd.keywords)[:80]
    parsed_jd.requirements = _dedupe_requirements(parsed_jd.requirements)[:40]
    parsed_jd.responsibilities = _dedupe_preserve(parsed_jd.responsibilities)[:25]
    return parsed_jd


def _extract_term_specs(text: str) -> list[TermSpec]:
    return [spec for spec in TERM_SPECS if _contains_spec(text, spec)]


def _contains_spec(text: str, spec: TermSpec) -> bool:
    return any(_contains_term(text, term) for term in (spec.term, *spec.aliases))


def _contains_term(text: str, term: str) -> bool:
    if "/" in term:
        return re.search(re.escape(term), text, flags=re.IGNORECASE) is not None
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE) is not None


def _clean_job_title(title: str) -> str:
    cleaned = (title or "").strip()
    cleaned = re.sub(r"^\s*(designation|job title|title|role)\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip(" :-\t")
    cleaned = re.sub(r"\s*:\s*$", "", cleaned).strip()
    return " ".join(_format_title_token(word) for word in cleaned.split()) or "Untitled Role"


def _format_title_token(word: str) -> str:
    stripped = word.strip()
    return TITLE_TOKEN_OVERRIDES.get(stripped.casefold(), stripped[:1].upper() + stripped[1:].lower())


def _append_skill(parsed_jd: ParsedJD, skill: str, *, preferred: bool) -> None:
    target = parsed_jd.preferred_skills if preferred else parsed_jd.required_skills
    opposite = parsed_jd.required_skills if preferred else parsed_jd.preferred_skills
    if preferred:
        parsed_jd.required_skills = [
            existing for existing in parsed_jd.required_skills if not _same_term(existing, skill)
        ]
        opposite = parsed_jd.required_skills
    if any(_same_term(skill, value) for value in opposite):
        return
    _append_unique(target, skill)


def _append_keyword(parsed_jd: ParsedJD, keyword: str, importance: str) -> None:
    for existing in parsed_jd.keywords:
        if _same_term(existing.keyword, keyword):
            existing.importance = _stronger_importance(existing.importance, importance)
            existing.frequency = max(existing.frequency, 1)
            return
    parsed_jd.keywords.append(JDKeyword(keyword=keyword, importance=importance, frequency=1))


def _promote_requirement_terms(parsed_jd: ParsedJD, preferred_terms: set[str]) -> None:
    known_terms = [spec.term for spec in TERM_SPECS]
    for req in parsed_jd.requirements:
        for term in known_terms:
            if _contains_term(req.text, term):
                _append_skill(parsed_jd, term, preferred=(not req.is_required or term in preferred_terms))


def _extract_soft_skills(text: str) -> list[str]:
    return [term.title() for term in SOFT_SKILL_TERMS if _contains_term(text, term)]


def _extract_exact_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    for pattern in COMMON_EXACT_PHRASE_PATTERNS:
        phrases.extend(match.group(0).strip() for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return _dedupe_preserve(phrases)[:30]


def _is_preferred_context(text: str, spec: TermSpec) -> bool:
    if not spec.preferred_hints:
        return False
    return any(_phrase_has_preferred_context(text, term, spec.preferred_hints) for term in (spec.term, *spec.aliases))


def _phrase_has_preferred_context(
    text: str,
    phrase: str,
    hints: tuple[str, ...] = ("advantage", "preferred", "nice to have", "good to have", "plus", "desired"),
) -> bool:
    for match in re.finditer(re.escape(phrase), text, flags=re.IGNORECASE):
        window = text[max(0, match.start() - 120): match.end() + 120].lower()
        if any(hint in window for hint in hints):
            return True
    return False


def _append_unique(values: list[str], value: str) -> None:
    cleaned = " ".join(str(value).split()).strip()
    if cleaned and not any(_same_term(cleaned, existing) for existing in values):
        values.append(cleaned)


def _dedupe_preserve(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        _append_unique(deduped, value)
    return deduped


def _dedupe_keywords(keywords: list[JDKeyword]) -> list[JDKeyword]:
    deduped: list[JDKeyword] = []
    for keyword in keywords:
        existing = next((item for item in deduped if _same_term(item.keyword, keyword.keyword)), None)
        if existing:
            existing.frequency = max(existing.frequency, keyword.frequency)
            existing.importance = _stronger_importance(existing.importance, keyword.importance)
        else:
            deduped.append(keyword)
    return deduped


def _dedupe_requirements(requirements: list[JDRequirement]) -> list[JDRequirement]:
    seen: set[str] = set()
    deduped: list[JDRequirement] = []
    for requirement in requirements:
        key = requirement.text.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(requirement)
    return deduped


def _same_term(left: str, right: str) -> bool:
    return left.casefold() == right.casefold()


def _stronger_importance(current: str, candidate: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return candidate if order.get(candidate, 1) > order.get(current, 1) else current
