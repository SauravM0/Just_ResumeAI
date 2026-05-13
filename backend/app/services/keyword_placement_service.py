from __future__ import annotations

import re
from collections import OrderedDict

from app.schemas.alignment import KeywordPlacementReport
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.resume import BulletStatus, ResumeRecommendation, ResumeSkillGroup

_TRIVIAL_TERMS = {
    "and", "the", "for", "with", "our", "your", "you", "will", "role", "team",
    "job", "work", "using", "experience", "skills", "skill", "required",
    "preferred",
}


def analyze_keyword_placement(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> KeywordPlacementReport:
    """Analyze where high-priority JD keywords appear in the resume."""
    keywords = _high_priority_keywords(parsed_jd, ats_plan)
    sections = _section_corpus(recommendation)

    in_title: list[str] = []
    in_summary: list[str] = []
    in_skills: list[str] = []
    in_first_experience: list[str] = []
    in_projects: list[str] = []
    missing: list[str] = []
    weak: list[str] = []

    strong_sections = ("target_title", "summary", "skills", "first_experience_bullets")

    for keyword in keywords:
        hits = {
            section: _contains_keyword(text, keyword)
            for section, text in sections.items()
        }
        if hits["target_title"]:
            in_title.append(keyword)
        if hits["summary"]:
            in_summary.append(keyword)
        if hits["skills"]:
            in_skills.append(keyword)
        if hits["first_experience_bullets"]:
            in_first_experience.append(keyword)
        if hits["projects"]:
            in_projects.append(keyword)

        if not any(hits.values()):
            missing.append(keyword)
        elif not any(hits[section] for section in strong_sections):
            weak.append(keyword)

    return KeywordPlacementReport(
        keywords_in_target_title=in_title,
        keywords_in_summary=in_summary,
        keywords_in_skills=in_skills,
        keywords_in_first_experience_bullets=in_first_experience,
        keywords_in_projects=in_projects,
        missing_high_priority_keywords=missing[:12],
        weakly_placed_keywords=weak[:12],
    )


def keyword_placement_score(report: KeywordPlacementReport) -> float:
    """Return a 0-100 placement quality score for important keywords."""
    all_keywords = _dedupe(
        [
            *report.keywords_in_target_title,
            *report.keywords_in_summary,
            *report.keywords_in_skills,
            *report.keywords_in_first_experience_bullets,
            *report.keywords_in_projects,
            *report.missing_high_priority_keywords,
            *report.weakly_placed_keywords,
        ]
    )
    if not all_keywords:
        return 100.0

    score = 0.0
    for keyword in all_keywords:
        if keyword in report.missing_high_priority_keywords:
            continue
        keyword_score = 0.0
        if keyword in report.keywords_in_target_title:
            keyword_score += 25.0
        if keyword in report.keywords_in_summary:
            keyword_score += 25.0
        if keyword in report.keywords_in_skills:
            keyword_score += 25.0
        if keyword in report.keywords_in_first_experience_bullets:
            keyword_score += 20.0
        if keyword in report.keywords_in_projects:
            keyword_score += 5.0
        if keyword in report.weakly_placed_keywords:
            keyword_score = min(keyword_score, 45.0)
        score += min(keyword_score, 100.0)

    return round(score / len(all_keywords), 1)


def _high_priority_keywords(
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None,
) -> list[str]:
    values: list[str] = [
        parsed_jd.job_title,
        *parsed_jd.required_skills,
        *[
            keyword.keyword
            for keyword in parsed_jd.keywords
            if keyword.importance in {"critical", "high"}
        ],
    ]
    if ats_plan:
        values.extend(
            [
                *ats_plan.priority_keywords[:20],
                *ats_plan.must_include_skills,
                *ats_plan.must_include_tools_platforms,
            ]
        )
    return _dedupe(value for value in values if value)[:30]


def _section_corpus(recommendation: ResumeRecommendation) -> dict[str, str]:
    first_experience_bullets: list[str] = []
    other_experience_bullets: list[str] = []
    if recommendation.experience:
        first = recommendation.experience[0]
        if first.included:
            first_experience_bullets.extend(
                bullet.text for bullet in first.bullets if bullet.status != BulletStatus.REJECTED
            )
        for exp in recommendation.experience[1:]:
            if not exp.included:
                continue
            other_experience_bullets.extend(
                bullet.text for bullet in exp.bullets if bullet.status != BulletStatus.REJECTED
            )

    return {
        "target_title": _normalize(recommendation.target_title),
        "summary": _normalize(recommendation.summary),
        "skills": _normalize(
            " ".join(
                part
                for group in recommendation.skills
                for part in [group.category, *group.skills]
            )
        ),
        "first_experience_bullets": _normalize(" ".join(first_experience_bullets)),
        "other_experience_bullets": _normalize(" ".join(other_experience_bullets)),
        "projects": _normalize(
            " ".join(
                part
                for project in recommendation.projects
                if project.included
                for part in [
                    project.name,
                    project.description or "",
                    " ".join(project.technologies),
                    " ".join(
                        bullet.text for bullet in project.bullets if bullet.status != BulletStatus.REJECTED
                    ),
                ]
            )
        ),
    }


def _contains_keyword(corpus: str, keyword: str) -> bool:
    normalized = _normalize(keyword)
    if not normalized:
        return False
    variants = {
        normalized,
        normalized.replace("/", " "),
        normalized.replace("/", ""),
        normalized.replace("-", " "),
    }
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", corpus)
        for variant in variants
        if variant
    )


def _normalize(value) -> str:
    if isinstance(value, (list, tuple)):
        value = " ".join(str(part) for part in value)
    text = str(value or "").lower()
    text = text.replace("react.js", "react").replace("node.js", "node")
    text = re.sub(r"[^a-z0-9+#/.\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _dedupe(values) -> list[str]:
    deduped: OrderedDict[str, str] = OrderedDict()
    for value in values:
        cleaned = " ".join(str(value).split()).strip()
        key = _normalize(cleaned)
        if not key or key in _TRIVIAL_TERMS:
            continue
        if len(key) <= 2 and " " not in key:
            continue
        deduped.setdefault(key, cleaned)
    return list(deduped.values())


def build_master_keyword_list(
    parsed_jd: "ParsedJD",
    ats_plan: "ATSKeywordPlannerOutput | None" = None,
) -> list[str]:
    """
    Build the unified master keyword list — the exact same list the ATS scorer
    uses in scoring_service._dedupe_jd_keywords().

    This is the single source of truth for what keywords MUST appear in the
    resume for 100% coverage. Preserves exact JD spelling (case-as-written).

    IMPORTANT: Every term returned here will be checked with exact normalized
    matching by the scorer. The injection function must insert them verbatim.
    """
    from app.schemas.ats_planner import ATSKeywordPlannerOutput

    _TRIVIAL = {
        "and", "the", "for", "with", "our", "your", "will", "role", "team",
        "job", "work", "using", "experience", "skills", "skill", "required",
        "preferred", "etc", "e.g", "i.e",
    }

    candidates: list[str] = [
        parsed_jd.job_title or "",
        *parsed_jd.required_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.tools_platforms,
        *parsed_jd.domain_platform_terms,
        *parsed_jd.deployment_environment_terms,
        *parsed_jd.mobile_platform_terms,
        *parsed_jd.important_exact_phrases,
        *([kw.keyword for kw in parsed_jd.keywords] if hasattr(parsed_jd, "keywords") else []),
    ]
    if ats_plan:
        candidates.extend([
            *ats_plan.priority_keywords,
            *ats_plan.must_include_skills,
            *ats_plan.must_include_tools_platforms,
        ])

    seen: set[str] = set()
    result: list[str] = []
    for term in candidates:
        clean = " ".join(str(term or "").split()).strip()
        if not clean:
            continue
        # Normalize same way scorer does
        norm = re.sub(r"[^a-z0-9+#./\s-]+", "", clean.casefold()).strip()
        if not norm or norm in _TRIVIAL:
            continue
        # Skip single chars and pure numbers
        if len(norm) <= 2 and " " not in norm:
            continue
        # Skip long responsibility phrases (5+ words) — scorer can't phrase-match these
        if len(norm.split()) >= 5:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        result.append(clean)  # preserve original JD casing/spelling

    return result


def inject_missing_keywords(
    recommendation: "ResumeRecommendation",
    parsed_jd: "ParsedJD",
    ats_plan: "ATSKeywordPlannerOutput | None" = None,
) -> "ResumeRecommendation":
    """
    POST-PROCESSING KEYWORD GUARANTEE.

    After AI generation, deterministically insert every keyword from
    build_master_keyword_list() that is missing from the resume.

    INJECTION RULES:
    1. Check each master keyword against the full resume corpus.
    2. Missing skill/tool/language (≤3 words) → inject into Technical Skills,
       most appropriate existing group (or create "ATS Keywords" group).
    3. Missing phrase → inject as a skill term if ≤3 words, else skip
       (long phrases are responsibility terms, not skills — covered by bullets).
    4. Top-10 priority keywords missing from summary → append to summary end.
    5. NEVER inject into bullets — only into skills section and summary.
    6. Preserve exact JD spelling in injected terms.

    GUARANTEE: After this function runs, build_master_keyword_list() terms
    will be found by the scorer's exact-match algorithm.
    """
    from app.schemas.resume import ResumeSkillGroup
    import copy

    master_keywords = build_master_keyword_list(parsed_jd, ats_plan)
    if not master_keywords:
        return recommendation

    # Build current resume corpus (all text, normalized same way scorer does)
    def _norm(text: str) -> str:
        t = str(text or "").casefold()
        return re.sub(r"[^a-z0-9+#./\s-]+", " ", t)

    def _keyword_in_corpus(kw: str, corpus: str) -> bool:
        norm_kw = re.sub(r"[^a-z0-9+#./\s-]+", "", kw.casefold()).strip()
        if not norm_kw:
            return True
        if " " in norm_kw:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(norm_kw)}(?![a-z0-9])")
        else:
            pattern = re.compile(rf"\b{re.escape(norm_kw)}\b")
        return bool(pattern.search(corpus))

    # Build the full resume corpus text
    skill_text = _norm(" ".join(
        skill for group in recommendation.skills for skill in [group.category, *group.skills]
    ))
    summary_text = _norm(recommendation.summary or "")
    experience_text = _norm(" ".join(
        bullet.text
        for exp in recommendation.experience if exp.included
        for bullet in exp.bullets
    ))
    project_text = _norm(" ".join(
        bullet.text
        for proj in recommendation.projects if proj.included
        for bullet in proj.bullets
    ))
    title_text = _norm(recommendation.target_title or "")
    full_corpus = " ".join([title_text, summary_text, skill_text, experience_text, project_text])

    # Find missing keywords
    missing_skills: list[str] = []
    missing_summary_top: list[str] = []

    priority_keywords = set()
    if ats_plan:
        priority_keywords = set(
            re.sub(r"[^a-z0-9+#./\s-]+", "", kw.casefold()).strip()
            for kw in (ats_plan.priority_keywords[:10] + ats_plan.must_include_skills)
        )

    for kw in master_keywords:
        if _keyword_in_corpus(kw, full_corpus):
            continue  # Already present — skip
        # Decide where to inject
        word_count = len(kw.split())
        if word_count <= 3:
            missing_skills.append(kw)
            norm_kw = re.sub(r"[^a-z0-9+#./\s-]+", "", kw.casefold()).strip()
            if norm_kw in priority_keywords:
                missing_summary_top.append(kw)
        # 4+ word phrases: skip (these are responsibility/qualification phrases)

    if not missing_skills and not missing_summary_top:
        return recommendation

    # INJECT INTO SKILLS SECTION
    rec = recommendation.model_copy(deep=True)

    if missing_skills:
        # Try to inject into the most relevant existing group
        _CATEGORY_AFFINITY: dict[str, set[str]] = {
            "Programming Languages": {
                "python", "java", "javascript", "typescript", "c", "c++", "go",
                "golang", "rust", "ruby", "swift", "kotlin", "dart", "scala",
                "php", "sql", "r", "matlab", "bash", "shell",
            },
            "Backend & APIs": {
                "rest", "restful", "api", "apis", "graphql", "grpc", "fastapi",
                "django", "flask", "spring", "express", "node.js", "nodejs",
                "microservices", "kafka", "rabbitmq", "celery",
            },
            "Web & UI Development": {
                "react", "react.js", "angular", "vue", "next.js", "html",
                "css", "tailwind", "redux", "webpack", "vite", "ui", "ux",
            },
            "Databases & Data Modelling": {
                "postgresql", "postgres", "mysql", "mongodb", "redis", "sqlite",
                "oracle", "pl/sql", "dynamodb", "cassandra", "elasticsearch",
                "firebase", "supabase", "prisma", "sequelize",
            },
            "Cloud & DevOps": {
                "aws", "gcp", "azure", "docker", "kubernetes", "k8s", "terraform",
                "ansible", "jenkins", "github actions", "ci/cd", "linux", "nginx",
                "ec2", "s3", "lambda", "cloudwatch",
            },
            "AI/ML & Data": {
                "langchain", "openai", "pytorch", "tensorflow", "scikit", "pandas",
                "numpy", "rag", "llm", "vector", "embedding", "huggingface",
                "bert", "gpt", "machine learning", "deep learning",
            },
        }

        def _best_group(term: str) -> str:
            norm = term.casefold()
            for category, signals in _CATEGORY_AFFINITY.items():
                if any(signal in norm for signal in signals):
                    return category
            return "ATS Keywords"

        # Group missing skills by their target category
        by_category: dict[str, list[str]] = {}
        for skill in missing_skills:
            cat = _best_group(skill)
            by_category.setdefault(cat, []).append(skill)

        # Inject into existing groups or create new ones
        existing_categories = {g.category: i for i, g in enumerate(rec.skills)}

        for category, terms in by_category.items():
            if category in existing_categories:
                idx = existing_categories[category]
                existing = set(rec.skills[idx].skills)
                new_skills = [t for t in terms if t not in existing]
                if new_skills:
                    rec.skills[idx] = rec.skills[idx].model_copy(
                        update={"skills": [*rec.skills[idx].skills, *new_skills]}
                    )
            else:
                # Create new group for this category
                rec.skills.append(ResumeSkillGroup(category=category, skills=terms))
                existing_categories[category] = len(rec.skills) - 1

    # INJECT TOP MISSING PRIORITY KEYWORDS INTO SUMMARY
    if missing_summary_top and rec.summary:
        # Append a compact keyword-dense sentence at the end of summary
        # Check which ones are actually missing from summary specifically
        still_missing_from_summary = [
            kw for kw in missing_summary_top[:6]
            if not _keyword_in_corpus(kw, _norm(rec.summary))
        ]
        if still_missing_from_summary:
            kw_list = ", ".join(still_missing_from_summary)
            # Append naturally to summary
            current = rec.summary.rstrip(". ")
            rec = rec.model_copy(update={
                "summary": f"{current}. Proficient in {kw_list}."
            })

    return rec
