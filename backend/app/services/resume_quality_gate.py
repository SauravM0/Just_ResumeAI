"""
resume_quality_gate.py — ATS-first quality pass.

PHILOSOPHY (v2 — Always-Generate):
  * NEVER delete a bullet because it lacks source-connection evidence.
  * NEVER delete a bullet because the profile has no certifications.
  * Evidence checks are WARNINGS ONLY — they never kill content.
  * Only truly corrupted / duplicate / impossibly-fake text is fatal.
  * Skills are ALWAYS guaranteed: JD required terms inject when profile is thin.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from app.domain.rules import MIN_BULLET_LENGTH
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import BulletStatus, ResumeBullet, ResumeRecommendation, ResumeSkillGroup
from app.services.resume_strategy_service import build_resume_strategy, is_fresher_intern_strategy

logger = logging.getLogger(__name__)


SKILL_DISPATCH_TABLE = {
    # Exact dispatch prevents common languages from leaking into database/tool groups.
    "python": "Programming Languages", "java": "Programming Languages", "javascript": "Programming Languages",
    "js": "Programming Languages", "typescript": "Programming Languages", "c": "Programming Languages",
    "c++": "Programming Languages", "c/c++": "Programming Languages", "c#": "Programming Languages",
    "go": "Programming Languages", "golang": "Programming Languages", "dart": "Programming Languages",
    "kotlin": "Programming Languages", "swift": "Programming Languages", "rust": "Programming Languages",
    "sql": "Programming Languages", "pl/sql": "Programming Languages",
    "fastapi": "Backend & APIs", "node.js": "Backend & APIs", "nodejs": "Backend & APIs",
    "express": "Backend & APIs", "express.js": "Backend & APIs", "spring": "Backend & APIs",
    "spring boot": "Backend & APIs", "django": "Backend & APIs", "flask": "Backend & APIs",
    ".net": "Backend & APIs", "dotnet": "Backend & APIs", "rest apis": "Backend & APIs",
    "restful apis": "Backend & APIs", "graphql": "Backend & APIs", "grpc": "Backend & APIs",
    "react": "Web & UI Development", "react.js": "Web & UI Development", "reactjs": "Web & UI Development",
    "next.js": "Web & UI Development", "nextjs": "Web & UI Development", "redux": "Web & UI Development",
    "angular": "Web & UI Development", "vue": "Web & UI Development", "html": "Web & UI Development",
    "css": "Web & UI Development", "ui/ux design": "Web & UI Development",
    "postgresql": "Databases & Data Modelling", "postgres": "Databases & Data Modelling",
    "mysql": "Databases & Data Modelling", "firebase": "Databases & Data Modelling",
    "mongodb": "Databases & Data Modelling", "redis": "Databases & Data Modelling",
    "sqlite": "Databases & Data Modelling", "oracle": "Databases & Data Modelling",
    "vector databases": "Databases & Data Modelling", "data modelling": "Databases & Data Modelling",
    "data modeling": "Databases & Data Modelling",
    "docker": "Cloud & DevOps", "kubernetes": "Cloud & DevOps", "aws": "Cloud & DevOps",
    "azure": "Cloud & DevOps", "gcp": "Cloud & DevOps", "google cloud": "Cloud & DevOps",
    "openshift": "Cloud & DevOps", "red hat openshift": "Cloud & DevOps",
    "rhel": "Cloud & DevOps", "red hat enterprise linux": "Cloud & DevOps",
    "red hat": "Learning Focus / JD Tools", "container platform": "Cloud & DevOps",
    "ci/cd": "Cloud & DevOps", "ci/cd pipelines": "Cloud & DevOps", "jenkins": "Cloud & DevOps",
    "github actions": "Cloud & DevOps", "gitlab": "Cloud & DevOps", "github": "Automation & Tools",
    "terraform": "Cloud & DevOps", "ansible": "Cloud & DevOps", "bash": "Programming Languages",
    "git": "Automation & Tools", "linux": "Automation & Tools", "observability": "Automation & Tools", "postman": "Automation & Tools",
    "jira": "Automation & Tools", "technical documentation": "Automation & Tools",
    "unit testing": "Automation & Tools",
    "rag": "AI/ML & Data", "rag pipelines": "AI/ML & Data", "llm": "AI/ML & Data",
    "llm integration": "AI/ML & Data", "langchain": "AI/ML & Data", "sparksql": "AI/ML & Data",
    "databricks": "AI/ML & Data", "apache spark": "AI/ML & Data", "machine learning": "AI/ML & Data",
    "android": "Mobile Development", "ios": "Mobile Development", "flutter": "Mobile Development",
    "react native": "Mobile Development",
}

SKILLS_BLOCK_LIST = {
    "basic technical knowledge", "basic knowledge", "analytical skills", "analytical skill",
    "accountability", "collaboration", "problem-solving", "problem-solving skills",
    "teamwork", "communication", "communication skills", "data engineering", "cloud",
}

SKILL_CATEGORY_ORDER = [
    "Programming Languages",
    "Web & UI Development",
    "Backend & APIs",
    "Databases & Data Modelling",
    "Automation & Tools",
    "Cloud & DevOps",
    "AI/ML & Data",
    "Learning Focus / JD Tools",
    "Security / Networking",
    "Mobile Development",
]

_FILLER_PATTERNS = [
    re.compile(r"\bfocused\s+on\b", re.IGNORECASE),
    re.compile(r"\bATS-friendly delivery\b", re.IGNORECASE),
    re.compile(r"\bBuilt\s+OBDX\s+Developer\s+Installation\b", re.IGNORECASE),
]
_GENERIC_IMPACT_RE = re.compile(
    r",\s*(improving reliability|supporting production readiness|streamlining delivery|reducing manual effort|strengthening troubleshooting|enhancing application development)$",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]{1,}", re.IGNORECASE)
_CORRUPTED_TEXT_RE = re.compile(r"(?:\u00c3|\u00c2|\ufffd)")
_UNREADABLE_RE = re.compile(r"(?:[A-Z0-9/+#.-]{2,}\s*){10,}")
# Only literal impossible fabrications are fatal — nothing evidence-based.
_FATAL_FAKE_TERMS = ("fake employer", "invented employer", "impossible certification")


def apply_resume_quality_gate(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    target_pages: int = 1,
) -> ResumeRecommendation:
    """Remove only fatal defects; weak source overlap is a warning-level signal."""
    rec = recommendation.model_copy(deep=True)
    strategy = build_resume_strategy(parsed_jd, profile)
    rec.summary = _clean_summary(rec.summary, rec.target_title)
    rec.skills = build_skill_taxonomy(rec.skills, parsed_jd, profile, target_pages)

    seen_bullets: set[str] = set()
    rec.experience = [
        entry for entry in rec.experience
        if _clean_entry_bullets(entry, parsed_jd, profile, seen_bullets)
    ]
    rec.projects = [
        entry for entry in rec.projects
        if _clean_entry_bullets(entry, parsed_jd, profile, seen_bullets)
    ]
    rec.education = [edu for edu in rec.education if edu.included and (edu.institution.strip() or edu.degree.strip())]
    rec.certifications = [cert for cert in rec.certifications if cert.included and cert.name.strip()]
    rec.achievements = [item for item in rec.achievements if item.included and item.title.strip()]
    rec.awards = [item for item in rec.awards if item.included and item.title.strip()]
    rec.custom_sections = [
        section.model_copy(update={"items": _dedupe(section.items)})
        for section in rec.custom_sections
        if section.included and section.title.strip() and _dedupe(section.items)
    ]

    warnings = list(rec.warnings)
    if is_fresher_intern_strategy(strategy):
        warnings.append("Fresher/intern strategy: preserved education, projects, achievements, and certifications.")
    rec.warnings = _dedupe(warnings)
    return rec


def build_skill_taxonomy(
    existing_groups: list[ResumeSkillGroup],
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    target_pages: int = 1,
) -> list[ResumeSkillGroup]:
    """
    Build the final skill taxonomy.

    ALWAYS-POPULATE CONTRACT:
    - All JD required_skills and programming_languages are injected unconditionally.
    - All profile skills are merged in.
    - If the result is still empty, inject ALL JD terms directly.
    - This guarantees the skills section is NEVER empty, even for a bare profile.
    """
    profile_skills = [skill.name for skill in profile.skills]
    jd_learning_tools = _jd_learning_tools(parsed_jd)

    # Full JD priority list — all required terms are always included.
    jd_priority = _dedupe([
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.tools_platforms,
        *parsed_jd.domain_platform_terms,
        *parsed_jd.mobile_platform_terms,
        *parsed_jd.preferred_skills,
        *jd_learning_tools,
    ])

    # Merge profile skills + AI-composed skill groups + all JD required terms.
    candidate_values = _dedupe_skills([
        *profile_skills,
        *(skill for group in existing_groups for skill in group.skills),
        # ALWAYS inject JD required + programming languages — no source check.
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
    ], jd_priority)

    # Remove soft-skill filler and overlong phrases.
    candidate_values = [v for v in candidate_values if _is_allowed_skill(v)]

    allowed: dict[str, str] = {_skill_key(v): v for v in candidate_values}

    # Inject remaining JD priority terms (tools, platforms, cloud) that
    # aren't already present — no profile-support check required.
    for value in jd_priority:
        key = _skill_key(value)
        if key not in allowed and _is_allowed_skill(value):
            allowed[key] = value

    categorized: dict[str, list[str]] = {category: [] for category in SKILL_CATEGORY_ORDER}
    for value in allowed.values():
        categorized[_classify_skill(value, jd_learning_tools)].append(value)

    total_limit = 32 if target_pages <= 1 else 42
    total_min = 16 if target_pages <= 1 else 0
    priority_keys = {value.casefold() for value in jd_priority}

    ordered_values: list[tuple[str, str]] = []
    for category in SKILL_CATEGORY_ORDER:
        skills = _dedupe_skills(categorized[category], jd_priority)
        skills.sort(key=lambda s: (s.casefold() not in priority_keys, s.casefold()))
        for skill in skills:
            ordered_values.append((category, skill))

    selected = ordered_values[:total_limit]
    if len(selected) < total_min:
        selected = ordered_values

    groups: list[ResumeSkillGroup] = []
    for category in SKILL_CATEGORY_ORDER:
        skills = [skill for skill_category, skill in selected if skill_category == category]
        if skills:
            groups.append(ResumeSkillGroup(category=category, skills=skills))

    # ALWAYS-POPULATE SAFETY NET: if taxonomy is still empty, inject everything.
    if not groups and jd_priority:
        logger.warning("Skill taxonomy produced 0 groups — injecting all JD priority terms as fallback.")
        all_clean = [v for v in jd_priority if _is_allowed_skill(v)]
        if all_clean:
            groups = [ResumeSkillGroup(category="Technical Skills", skills=all_clean[:30])]

    return groups


def _clean_summary(summary: str | None, target_title: str) -> str | None:
    cleaned = _clean_text(summary)
    for pattern in _FILLER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"^\s*possessing\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*,\s*,+", ",", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned).strip(" .")
    if not cleaned:
        return target_title.strip() or None
    return cleaned[:1].upper() + cleaned[1:] + "."


def _clean_entry_bullets(entry, parsed_jd: ParsedJD, profile: MasterProfile, seen_bullets: set[str]) -> bool:
    """
    Keep all bullets that pass ONLY structural/corruption checks.
    Source-connection and certification evidence are WARNINGS — never fatal.
    """
    valid: list[ResumeBullet] = []
    for bullet in entry.bullets:
        if bullet.status == BulletStatus.REJECTED:
            continue
        text = _clean_bullet_text(bullet.text)
        severity = _bullet_quality_severity(text, seen_bullets)
        if severity == "fatal":
            logger.debug("Dropped bullet (fatal): %s", text[:80])
            continue
        seen_bullets.add(_dedupe_key(text))
        valid.append(bullet.model_copy(update={"text": text, "original_text": bullet.original_text or text}))
    entry.bullets = valid
    return bool(valid)


def _bullet_quality_severity(text: str, seen_bullets: set[str]) -> str:
    """
    Only truly corrupted, duplicate, or literally impossible text is fatal.
    Evidence / source-connection checks are REMOVED — trust the AI composer.
    """
    if not _valid_bullet_text(text):
        return "fatal"
    if _dedupe_key(text) in seen_bullets:
        return "fatal"
    if _contains_literal_fake_terms(text):
        return "fatal"
    return "keep"


def _contains_literal_fake_terms(text: str) -> bool:
    """Only block bullets containing exact impossible-fabrication strings."""
    lowered = text.casefold()
    return any(term in lowered for term in _FATAL_FAKE_TERMS)


def _valid_bullet_text(text: str) -> bool:
    if len(text) < MIN_BULLET_LENGTH:
        return False
    if text.startswith("-") or text in {".", "â€¢"}:
        return False
    if _CORRUPTED_TEXT_RE.search(text):
        return False
    if any(pattern.search(text) for pattern in _FILLER_PATTERNS):
        return False
    if _looks_like_keyword_stuffing(text):
        return False
    if _UNREADABLE_RE.search(text):
        return False
    return bool(re.search(r"[A-Za-z0-9]", text))


def _clean_bullet_text(text: str | None) -> str:
    cleaned = _clean_text(text)
    cleaned = re.sub(r"^[\-*â€¢\s]+", "", cleaned)
    cleaned = _GENERIC_IMPACT_RE.sub("", cleaned)
    return cleaned.strip(" .;:-\t")


def _looks_like_keyword_stuffing(text: str) -> bool:
    tokens = [token.casefold() for token in _TOKEN_RE.findall(text)]
    counts = Counter(tokens)
    if any(count > 2 and len(token) > 3 for token, count in counts.items()):
        return True
    return len(re.findall(r"\b[A-Z0-9/+#.-]{2,}\b", text)) >= 12


def _classify_skill(skill: str, jd_learning_tools: list[str] | None = None) -> str:
    text = skill.casefold().strip()
    normalized = _skill_key(skill)
    if any(text == tool.casefold() for tool in jd_learning_tools or []):
        return "Learning Focus / JD Tools"
    if normalized in SKILL_DISPATCH_TABLE:
        return SKILL_DISPATCH_TABLE[normalized]
    # Pattern tier keeps new frameworks/tools usable without waiting for a code-table update.
    if re.search(r"(\.js|js)$", normalized) or normalized.endswith(("framework", "library", "sdk")):
        return "Web & UI Development" if any(term in normalized for term in ("react", "next", "vue", "angular", "ui")) else "Backend & APIs"
    if any(term in normalized for term in ("db", "database", "postgres", "mysql", "mongo", "redis", "cassandra", "dynamo")):
        return "Databases & Data Modelling"
    if any(term in normalized for term in ("cloud", "aws", "azure", "gcp", "docker", "kubernetes", "openshift", "rhel", "red hat", "devops", "ci/cd", "pipeline")):
        return "Cloud & DevOps"
    if any(term in normalized for term in ("android", "ios", "mobile", "flutter", "react native")):
        return "Mobile Development"
    if any(term in normalized for term in ("ai", "ml", "llm", "rag", "spark", "model", "nlp", "vector")):
        return "AI/ML & Data"
    if text in {"c", "c++", "c/c++", "c#", "java", "python", "javascript", "typescript", "go", "golang", "ruby", "php", "swift", "kotlin"}:
        return "Programming Languages"
    if text in {"sql", "pl/sql"} or any(term in text for term in ("postgres", "mysql", "oracle", "mongodb", "redis", "database", "db2", "sqlite", "data modelling", "data modeling", "vector database")):
        return "Databases & Data Modelling"
    if any(term in text for term in ("react", "angular", "vue", "frontend", "ui", "ux", "html", "css")):
        return "Web & UI Development"
    if any(term in text for term in ("node", "express", "spring", "django", "fastapi", "flask", ".net", "hibernate", "microservices", "api", "oop", "unit testing")):
        return "Backend & APIs"
    if any(term in text for term in ("excel", "powerpoint", "word", "outlook", "documentation", "power automate", "flow", "git", "jira", "postman", "tool")):
        return "Automation & Tools"
    if any(term in text for term in ("aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "ci/cd", "devops", "terraform", "linux")):
        return "Cloud & DevOps"
    if any(term in text for term in ("sharepoint", "obdx", "oracle banking", "banking", "open banking", "cemli", "extensibility")):
        return "Learning Focus / JD Tools"
    if any(term in text for term in ("android", "ios", "mobile", "react native", "flutter")):
        return "Mobile Development"
    if any(term in text for term in ("security", "network", "oauth", "saml", "jwt", "ssl", "tls", "firewall")):
        return "Security / Networking"
    return "Automation & Tools"


def _jd_learning_tools(parsed_jd: ParsedJD) -> list[str]:
    corpus = " ".join([
        parsed_jd.raw_text,
        " ".join(parsed_jd.tools_platforms),
        " ".join(parsed_jd.domain_platform_terms),
        " ".join(parsed_jd.required_skills),
        " ".join(parsed_jd.preferred_skills),
        " ".join(keyword.keyword for keyword in parsed_jd.keywords),
    ]).casefold()
    tools: list[str] = []
    for label, needles in {
        "MS Excel": ["excel", "ms excel"],
        "MS PowerPoint": ["powerpoint", "power point", "ms powerpoint"],
        "MS Word": ["word", "ms word"],
        "MS Outlook": ["outlook", "ms outlook"],
        "SharePoint Application Building": ["sharepoint"],
        "Power Pages": ["power pages"],
        "Power Automate Flow Creation": ["power automate", "flow creation"],
        "OOP": ["oop", "object oriented"],
        "Data Modelling": ["data modelling", "data modeling"],
        "UI/UX Design": ["ui/ux", "ui ux", "user interface"],
        "Technical Documentation": ["technical documentation", "documentation"],
        "Unit Testing": ["unit testing", "test cases"],
    }.items():
        if any(needle in corpus for needle in needles):
            tools.append(label)
    return _dedupe(tools)


def _has_profile_support(value: str, profile: MasterProfile) -> bool:
    """Check if a skill value appears anywhere in the profile text."""
    profile_text = " ".join([
        " ".join(skill.name for skill in profile.skills),
        " ".join(exp.description or "" for exp in profile.work_experience),
        " ".join(" ".join(exp.bullets) for exp in profile.work_experience),
        " ".join(" ".join(project.technologies) for project in profile.projects),
        " ".join(" ".join(project.bullets) for project in profile.projects),
    ])
    return bool(_tokens(value) & _tokens(profile_text))


def _tokens(text: str | None) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(text or "") if len(token) > 2}


def _clean_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _dedupe_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(str(value or ""))
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _skill_key(value: str | None) -> str:
    text = _clean_text(str(value or "")).casefold()
    aliases = {
        "reactjs": "react.js",
        "nodejs": "node.js",
        "nextjs": "next.js",
        "golang": "go",
        "postgres": "postgresql",
        "restful api": "rest apis",
        "restful apis": "rest apis",
    }
    return aliases.get(text, text)


def _is_allowed_skill(value: str) -> bool:
    cleaned = _clean_text(value)
    key = cleaned.casefold()
    # Blocking is case-insensitive because these phrases often come from JD prose.
    if key in SKILLS_BLOCK_LIST:
        return False
    if len(cleaned.split()) > 4:
        return False
    if any(blocked in key for blocked in SKILLS_BLOCK_LIST if " " in blocked):
        return False
    return bool(cleaned)


def _dedupe_skills(values, jd_priority: list[str] | None = None) -> list[str]:
    priority_forms = {_skill_key(value): value for value in jd_priority or []}
    chosen: dict[str, str] = {}
    for value in values:
        cleaned = _clean_text(str(value or ""))
        if not cleaned:
            continue
        key = _skill_key(cleaned)
        preferred = priority_forms.get(key)
        current = chosen.get(key)
        if preferred:
            chosen[key] = preferred
        elif current is None or _specificity_score(cleaned) > _specificity_score(current):
            chosen[key] = cleaned
    return list(chosen.values())


def _specificity_score(value: str) -> tuple[int, int]:
    # Prefer canonical/specific forms such as React.js over react when JD form is absent.
    return (int(any(char in value for char in ".#/+")), len(value))
