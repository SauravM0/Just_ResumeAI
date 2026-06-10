from __future__ import annotations

import re
from collections import OrderedDict

from app.schemas.alignment import KeywordPlacementReport
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import BulletStatus, ResumeRecommendation
from app.services.candidate_evidence_service import (
    build_candidate_evidence,
    classify_jd_keyword_truth,
    is_supported_placement,
    is_learning_placement,
    learning_focus_phrase,
)
from app.services.jd_sanitization_service import sanitize_parsed_jd
from app.services.skill_taxonomy_service import clean_keyword_terms, merge_typed_skill_groups
from app.services.synonym_service import get_all_forms

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
        ats_plan.target_resume_title if ats_plan and ats_plan.seniority_adjusted else parsed_jd.job_title,
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
    return any(_contains_keyword_exact(corpus, form) for form in get_all_forms(keyword))


def _contains_keyword_exact(corpus: str, keyword: str) -> bool:
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

    parsed_jd = sanitize_parsed_jd(parsed_jd)

    _TRIVIAL = {
        "and", "the", "for", "with", "our", "your", "will", "role", "team",
        "job", "work", "using", "experience", "skills", "skill", "required",
        "preferred", "etc", "e.g", "i.e",
    }

    candidates: list[str] = [
        parsed_jd.job_title or "",
        *parsed_jd.required_skills,
        *parsed_jd.preferred_skills,
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
    for term in clean_keyword_terms(candidates):
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
    profile: MasterProfile | None = None,
    aggressive_mode: bool = False,
) -> "ResumeRecommendation":
    """
    POST-PROCESSING KEYWORD GUARANTEE.

    After AI generation, deterministically insert every keyword from
    build_master_keyword_list() that is missing from the resume.

    In aggressive mode: inject ALL missing keywords directly into main skill
    groups, summary, and project tech lists — no evidence gate.
    In realistic mode: use evidence classification to decide placement.
    """
    master_keywords = build_master_keyword_list(parsed_jd, ats_plan)
    if not master_keywords:
        return recommendation

    # Build current resume corpus (all text, normalized same way scorer does)
    def _norm(text: str) -> str:
        t = str(text or "").casefold()
        return re.sub(r"[^a-z0-9+#./\s-]+", " ", t)

    def _keyword_in_corpus(kw: str, corpus: str) -> bool:
        if any(_keyword_in_corpus_exact(form, corpus) for form in get_all_forms(kw)):
            return True
        return False

    def _keyword_in_corpus_exact(kw: str, corpus: str) -> bool:
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
        " ".join([
            proj.name,
            proj.description or "",
            " ".join(proj.technologies),
            " ".join(
                bullet.text
                for bullet in proj.bullets
                if bullet.status != BulletStatus.REJECTED
            ),
        ])
        for proj in recommendation.projects
        if proj.included
    ))
    title_text = _norm(recommendation.target_title or "")
    full_corpus = " ".join([title_text, summary_text, skill_text, experience_text, project_text])

    # Find ALL missing keywords
    all_missing: list[str] = []
    for kw in master_keywords:
        if _keyword_in_corpus(kw, full_corpus):
            continue
        word_count = len(kw.split())
        if word_count > 4:
            continue  # Skip long responsibility phrases
        all_missing.append(kw)

    if not all_missing:
        return recommendation

    rec = recommendation.model_copy(deep=True)

    # ALWAYS AGGRESSIVE MODE: inject ALL missing keywords directly into main skill groups
    # No evidence gate, no Learning Focus — straight into hands-on skills
    rec.skills = merge_typed_skill_groups(
        rec.skills,
        [kw for kw in all_missing if len(kw.split()) <= 3],
        learning_focus_values=[],  # No learning focus in aggressive mode
    )

    # Inject top missing keywords into summary naturally
    summary_inject = [kw for kw in all_missing if len(kw.split()) <= 2][:5]
    if summary_inject and rec.summary:
        # Add a professional sentence that weaves in missing keywords
        jd_title = parsed_jd.job_title or "the target role"
        keyword_phrase = ", ".join(summary_inject[:3])
        remaining = ", ".join(summary_inject[3:])
        inject_sentence = f"Skilled in {keyword_phrase}"
        if remaining:
            inject_sentence += f" with exposure to {remaining}"
        inject_sentence += f", aligned with {jd_title} requirements."
        rec.summary = f"{rec.summary.rstrip('.')}. {inject_sentence}"

    # Inject into project technology lists
    tech_keywords = [kw for kw in all_missing if len(kw.split()) <= 2]
    if tech_keywords and rec.projects:
        for proj in rec.projects:
            if proj.included and len(tech_keywords) > 0:
                existing_tech_lower = {t.casefold() for t in proj.technologies}
                added = 0
                for tkw in tech_keywords[:]:
                    if tkw.casefold() not in existing_tech_lower and added < 4:
                        proj.technologies.append(tkw)
                        existing_tech_lower.add(tkw.casefold())
                        tech_keywords.remove(tkw)
                        added += 1

    return rec
