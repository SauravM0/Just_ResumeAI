"""Deterministic internal skill taxonomy for recruiter-safe resumes."""

from __future__ import annotations

import re

from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import InternalTypedSkillTaxonomy as TypedSkillTaxonomy
from app.schemas.resume import ResumeSkillGroup, TypedSkillCategory
from app.services.jd_sanitization_service import sanitize_parsed_jd


CANONICAL_CATEGORY_LABELS: dict[TypedSkillCategory, str] = {
    "programming_languages": "Programming Languages",
    "frontend_frameworks": "Frontend Frameworks",
    "backend_frameworks": "Backend Frameworks",
    "databases": "Databases",
    "cloud_devops": "Cloud & DevOps",
    "tools": "Tools",
    "domain_platforms": "Domain Platforms",
    "ai_ml": "AI/ML",
    "soft_skills": "Soft Skills",
    "learning_focus": "Learning Focus",
    "review_needed": "Review Needed",
}

EXPORT_CATEGORY_ORDER: list[TypedSkillCategory] = [
    "programming_languages",
    "frontend_frameworks",
    "backend_frameworks",
    "databases",
    "cloud_devops",
    "tools",
    "domain_platforms",
    "ai_ml",
    "learning_focus",
]

EDITOR_CATEGORY_ORDER: list[TypedSkillCategory] = [
    *EXPORT_CATEGORY_ORDER,
    "soft_skills",
    "review_needed",
]

_SINGLE_ADJECTIVES = {
    "strong", "good", "excellent", "great", "familiar", "basic", "advanced", "skilled",
    "proficient", "experienced", "solid",
}
_SOFT_SKILLS = {
    "communication", "communication skills", "leadership", "problem solving",
    "problem-solving", "problem-solving skills", "good team player", "team player",
    "teamwork", "collaboration", "cross-functional collaboration",
    "technical communication", "stakeholder management", "mentoring",
}
_GENERIC_SOFT_DROP = {
    "good team player", "team player", "hard worker", "self motivated",
    "self-motivated", "positive attitude", "communication skills", "problem solving",
    "problem-solving", "leadership",
}
_BOILERPLATE_RE = re.compile(
    r"\b(?:we are seeking|ideal candidate|responsibilities include|apply now|job description|equal opportunity|about us|ats keywords|metadata|job id|requisition id)\b",
    re.IGNORECASE,
)
_URL_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*", re.IGNORECASE)
_LEARNING_FOCUS_RE = re.compile(r"^currently strengthening (.+?) fundamentals$", re.IGNORECASE)

_CANONICAL_ALIASES = {
    "js": "JavaScript",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "react": "React",
    "reactjs": "React.js",
    "react-js": "React.js",
    "react.js": "React.js",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node-js": "Node.js",
    "node.js": "Node.js",
    "nextjs": "Next.js",
    "next-js": "Next.js",
    "next.js": "Next.js",
    "express": "Express.js",
    "express.js": "Express.js",
    "fastapi": "FastAPI",
    "asp-net": "ASP.NET",
    "asp.net": "ASP.NET",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "ci cd": "CI/CD",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "ajax": "AJAX",
    "git": "Git",
    "aws": "AWS",
    "gcp": "GCP",
    "r": "R",
    "go": "Go",
    "sql": "SQL",
    "pl/sql": "PL/SQL",
    "ui/ux design": "UI/UX Design",
}

_CATEGORY_TERMS: dict[TypedSkillCategory, set[str]] = {
    "programming_languages": {
        "python", "java", "javascript", "typescript", "c", "c++", "c#", "go",
        "golang", "dart", "kotlin", "swift", "rust", "sql", "pl/sql", "bash",
        "shell", "php", "ruby", "scala", "r", "matlab",
    },
    "frontend_frameworks": {
        "react.js", "react", "angular", "vue", "vue.js", "next.js", "redux",
        "html", "css", "tailwind", "bootstrap", "vite", "webpack", "ui/ux design",
    },
    "backend_frameworks": {
        "node.js", "express.js", "fastapi", "django", "flask", "spring",
        "spring boot", "asp.net", ".net", "dotnet", "rest apis", "restful apis",
        "graphql", "grpc", "microservices", "kafka",
    },
    "databases": {
        "postgresql", "mysql", "mongodb", "redis", "sqlite", "oracle", "firebase",
        "supabase", "dynamodb", "cassandra", "elasticsearch", "vector databases",
        "data modelling", "data modeling",
    },
    "cloud_devops": {
        "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "terraform",
        "ansible", "jenkins", "github actions", "gitlab ci", "ci/cd", "linux",
        "openshift", "rhel", "nginx",
    },
    "tools": {
        "git", "github", "gitlab", "jira", "postman", "figma", "excel", "ms excel",
        "microsoft excel", "ms word", "word", "microsoft word", "powerpoint",
        "ms powerpoint", "outlook", "ms outlook", "technical documentation",
        "unit testing", "ajax",
    },
    "domain_platforms": {
        "salesforce", "servicenow", "sap", "workday", "sharepoint", "obdx",
        "oracle banking", "power pages", "power automate",
    },
    "ai_ml": {
        "rag", "rag pipelines", "llm", "llms", "langchain", "openai", "pytorch",
        "tensorflow", "scikit-learn", "pandas", "numpy", "machine learning",
        "deep learning", "databricks", "apache spark", "spark", "nlp",
    },
    "soft_skills": _SOFT_SKILLS,
    "learning_focus": set(),
    "review_needed": set(),
}


def build_typed_skill_taxonomy(
    *,
    existing_groups: list[ResumeSkillGroup],
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    include_review_needed: bool = False,
) -> TypedSkillTaxonomy:
    parsed_jd = sanitize_parsed_jd(parsed_jd)
    taxonomy = TypedSkillTaxonomy()
    profile_terms = [skill.name for skill in profile.skills]
    existing_terms = [skill for group in existing_groups for skill in group.skills]
    jd_terms = [
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.tools_platforms,
        *parsed_jd.domain_platform_terms,
        *parsed_jd.mobile_platform_terms,
        *parsed_jd.preferred_skills,
    ]

    for raw in _dedupe(profile_terms):
        add_skill_to_taxonomy(taxonomy, raw, include_review_needed=include_review_needed)
    for raw in _dedupe([*existing_terms, *jd_terms]):
        normalized = normalize_skill_value(raw)
        if not normalized:
            continue
        if _profile_supports_term(profile, normalized):
            add_skill_to_taxonomy(taxonomy, normalized, include_review_needed=include_review_needed)
        elif classify_skill(normalized) not in {None, "soft_skills"}:
            taxonomy.learning_focus.append(f"Currently strengthening {normalized} fundamentals")
        elif include_review_needed:
            taxonomy.review_needed.append(normalized)

    return _dedupe_taxonomy(taxonomy)


def add_skill_to_taxonomy(
    taxonomy: TypedSkillTaxonomy,
    raw_value: str,
    *,
    include_review_needed: bool = False,
) -> None:
    normalized = normalize_skill_value(raw_value)
    if normalized is None:
        return
    category = classify_skill(normalized)
    if category is None:
        if include_review_needed:
            taxonomy.review_needed.append(normalized)
        return
    if category == "soft_skills" and _skill_key(normalized) in _GENERIC_SOFT_DROP:
        return
    getattr(taxonomy, category).append(normalized)


def normalize_skill_value(raw_value: str | None) -> str | None:
    cleaned = re.sub(r"\s+", " ", str(raw_value or "")).strip(" ,;:-")
    if not cleaned:
        return None
    lowered = cleaned.casefold()
    if _BOILERPLATE_RE.search(cleaned):
        return None
    if lowered in _SINGLE_ADJECTIVES:
        return None
    if lowered == "ajax-asynchronous-javascript-and-xml":
        return None
    if len(cleaned.split()) > 4:
        return None
    alias_key = _skill_key(cleaned)
    if alias_key in _CANONICAL_ALIASES:
        return _CANONICAL_ALIASES[alias_key]
    if _URL_SLUG_RE.match(lowered):
        return None
    if len(cleaned) > 45:
        return None
    return _canonical_case(cleaned)


def classify_skill(skill: str) -> TypedSkillCategory | None:
    key = _skill_key(skill)
    learning_match = _LEARNING_FOCUS_RE.match(skill.strip())
    if learning_match and classify_skill(learning_match.group(1)) not in {None, "soft_skills"}:
        return "learning_focus"
    if key in _SINGLE_ADJECTIVES:
        return None
    if key in _SOFT_SKILLS:
        return "soft_skills"
    for category, terms in _CATEGORY_TERMS.items():
        if category in {"soft_skills", "learning_focus", "review_needed"}:
            continue
        if key in terms:
            return category
    return None


def typed_taxonomy_to_resume_groups(
    taxonomy: TypedSkillTaxonomy,
    *,
    include_soft_skills: bool = False,
    include_review_needed: bool = False,
    target_pages: int = 1,
) -> list[ResumeSkillGroup]:
    order = list(EXPORT_CATEGORY_ORDER)
    if include_soft_skills:
        order.append("soft_skills")
    if include_review_needed:
        order.append("review_needed")

    total_limit = 32 if target_pages <= 1 else 42
    groups: list[ResumeSkillGroup] = []
    used = 0
    for category in order:
        values = _dedupe(getattr(taxonomy, category))
        if not values:
            continue
        remaining = total_limit - used
        if remaining <= 0:
            break
        selected = values[:remaining]
        groups.append(ResumeSkillGroup(category=CANONICAL_CATEGORY_LABELS[category], skills=selected))
        used += len(selected)
    return groups


def sanitize_resume_skill_groups(
    groups: list[ResumeSkillGroup],
    *,
    include_review_needed: bool = False,
    include_soft_skills: bool = False,
) -> list[ResumeSkillGroup]:
    taxonomy = TypedSkillTaxonomy()
    for group in groups:
        for skill in group.skills:
            add_skill_to_taxonomy(taxonomy, skill, include_review_needed=include_review_needed)
    return typed_taxonomy_to_resume_groups(
        _dedupe_taxonomy(taxonomy),
        include_soft_skills=include_soft_skills,
        include_review_needed=include_review_needed,
    )


def merge_typed_skill_groups(
    groups: list[ResumeSkillGroup],
    values,
    *,
    learning_focus_values=(),
    target_pages: int = 1,
) -> list[ResumeSkillGroup]:
    """Merge values through the typed taxonomy before re-emitting display groups."""
    taxonomy = _taxonomy_from_groups(groups)
    for value in values:
        add_skill_to_taxonomy(taxonomy, str(value or ""))
    for value in learning_focus_values:
        normalized = normalize_skill_value(str(value or ""))
        if normalized and classify_skill(normalized) not in {None, "soft_skills"}:
            taxonomy.learning_focus.append(f"Currently strengthening {normalized} fundamentals")
    return typed_taxonomy_to_resume_groups(_dedupe_taxonomy(taxonomy), target_pages=target_pages)


def clean_keyword_terms(values) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = normalize_skill_value(str(value or ""))
        if normalized and classify_skill(normalized) is not None:
            result.append(normalized)
    return _dedupe(result)


def _taxonomy_from_groups(groups: list[ResumeSkillGroup]) -> TypedSkillTaxonomy:
    taxonomy = TypedSkillTaxonomy()
    for group in groups:
        for skill in group.skills:
            add_skill_to_taxonomy(taxonomy, skill)
    return taxonomy


def _dedupe_taxonomy(taxonomy: TypedSkillTaxonomy) -> TypedSkillTaxonomy:
    for category in EDITOR_CATEGORY_ORDER:
        setattr(taxonomy, category, _dedupe(getattr(taxonomy, category)))
    return taxonomy


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        key = _skill_key(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _skill_key(value: str | None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9+#./-]+", " ", text).strip()
    return text


def _canonical_case(value: str) -> str:
    key = _skill_key(value)
    if key in _CANONICAL_ALIASES:
        return _CANONICAL_ALIASES[key]
    if value.isupper() or any(char in value for char in ".#/+"):
        return value
    tokens = _TOKEN_RE.findall(value)
    if len(tokens) == 1 and len(tokens[0]) <= 3:
        return tokens[0].upper()
    return " ".join(part[:1].upper() + part[1:] if part.islower() else part for part in value.split())


def _profile_supports_term(profile: MasterProfile, term: str) -> bool:
    parts: list[str] = [profile.summary or "", *(skill.name for skill in profile.skills)]
    for exp in profile.work_experience:
        parts.extend([exp.title, exp.description or "", *exp.bullets, *exp.tags])
    for project in profile.projects:
        parts.extend([project.name, project.description or "", *project.technologies, *project.bullets])
    for edu in profile.education:
        parts.extend([edu.degree, edu.field_of_study or "", *edu.relevant_coursework])
    for cert in profile.certifications:
        parts.extend([cert.name, cert.issuing_org or ""])
    normalized_term = _skill_key(term)
    normalized_corpus = _skill_key(" ".join(parts))
    if not normalized_term:
        return False
    pattern = (
        re.compile(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])")
        if " " in normalized_term or "/" in normalized_term or "." in normalized_term
        else re.compile(rf"\b{re.escape(normalized_term)}\b")
    )
    return bool(pattern.search(normalized_corpus))
