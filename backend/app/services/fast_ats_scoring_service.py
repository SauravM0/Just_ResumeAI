"""Fast deterministic ATS keyword extraction and scoring."""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from typing import Any

from app.services.jd_sanitization_service import clean_jd_keyword_terms, sanitize_jd_text


TECH_TERMS: tuple[str, ...] = (
    "AWS",
    "Azure",
    "GCP",
    "Docker",
    "Kubernetes",
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Node.js",
    "FastAPI",
    "Django",
    "Flask",
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "Redis",
    "SQL",
    "NoSQL",
    "REST",
    "GraphQL",
    "CI/CD",
    "Git",
    "Jenkins",
    "Terraform",
    "Microservices",
    "APIs",
    "Machine Learning",
    "Data Engineering",
    "Agile",
    "Scrum",
)

STOPWORDS = {
    "about",
    "across",
    "also",
    "and",
    "are",
    "but",
    "can",
    "for",
    "from",
    "has",
    "have",
    "into",
    "our",
    "that",
    "the",
    "this",
    "with",
    "will",
    "you",
    "your",
}

_JD_KEYWORD_CACHE: dict[str, list[str]] = {}
_JD_KEYWORD_CACHE_MAX = 256


@dataclass(frozen=True)
class FastATSResult:
    ats_score: int
    matched_keywords: list[str]
    missing_keywords: list[str]
    extracted_keywords: list[str]
    required_skills: list[str]
    matched_required_skills: list[str]
    missing_required_skills: list[str]
    score_breakdown: dict[str, int]
    score_explanation: list[str]
    improvement_suggestions: list[str]

    def as_score_json(self) -> dict[str, Any]:
        total = len(self.extracted_keywords)
        matched = len(self.matched_keywords)
        coverage = round((matched / total * 100), 2) if total else 0
        required_total = len(self.required_skills)
        required_matched = len(self.matched_required_skills)
        required_coverage = round((required_matched / required_total * 100), 2) if required_total else 0
        return {
            "score": self.ats_score,
            "overall_score": self.ats_score,
            "score_label": "Estimated ATS Match Score",
            "score_disclaimer": "Fast deterministic estimate for comparison, not a guaranteed ATS result.",
            "matched_keywords": self.matched_keywords,
            "missing_keywords": self.missing_keywords,
            "extracted_keywords": self.extracted_keywords,
            "required_skills": self.required_skills,
            "matched_required_skills": self.matched_required_skills,
            "missing_required_skills": self.missing_required_skills,
            "keyword_score": {
                "total_keywords": total,
                "matched_keywords": matched,
                "coverage_percent": coverage,
                "critical_missing": self.missing_keywords,
                "details": [
                    {
                        "keyword": keyword,
                        "found": keyword in self.matched_keywords,
                        "location": "resume_json" if keyword in self.matched_keywords else "missing",
                    }
                    for keyword in self.extracted_keywords
                ],
            },
            "skill_score": {
                "required_total": required_total,
                "required_matched": required_matched,
                "required_coverage_percent": required_coverage,
                "preferred_total": 0,
                "preferred_matched": 0,
                "preferred_coverage_percent": 0,
            },
            "readability_score": {"score": self.score_breakdown["parseability"], "avg_bullet_length": 0, "issues": []},
            "format_score": self.score_breakdown["parseability"],
            "section_score": _section_score_json(self.score_breakdown["standard_sections"]),
            "responsibility_score": self.score_breakdown["exact_jd_keywords"],
            "title_alignment_score": self.score_breakdown["title_seniority_alignment"],
            "warnings": [],
            "recommendations": self.improvement_suggestions,
            "score_breakdown": self.score_breakdown,
            "score_explanation": self.score_explanation,
            "scoring_mode": "fast_deterministic",
        }


class FastATSScoringService:
    """Small deterministic scorer for the fast generation path."""

    def extract_keywords(self, raw_jd_text: str, limit: int = 40) -> list[str]:
        clean_jd_text = sanitize_jd_text(raw_jd_text).clean_text
        cache_key = _jd_cache_key(clean_jd_text, limit)
        cached = _JD_KEYWORD_CACHE.get(cache_key)
        if cached is not None:
            return list(cached)

        text = _normalize_text(clean_jd_text)
        keywords: list[str] = []

        for term in TECH_TERMS:
            if _contains_term(text, term):
                _append_unique(keywords, term)

        for phrase in _extract_likely_phrases(text):
            _append_unique(keywords, phrase)

        extracted = clean_jd_keyword_terms(keywords, max_items=limit)
        if len(_JD_KEYWORD_CACHE) >= _JD_KEYWORD_CACHE_MAX:
            _JD_KEYWORD_CACHE.pop(next(iter(_JD_KEYWORD_CACHE)))
        _JD_KEYWORD_CACHE[cache_key] = list(extracted)
        return extracted

    def score(
        self,
        resume_json: dict[str, Any],
        raw_jd_text: str,
        *,
        extracted_keywords: list[str] | None = None,
    ) -> FastATSResult:
        keywords = clean_jd_keyword_terms(
            list(extracted_keywords) if extracted_keywords is not None else self.extract_keywords(raw_jd_text)
        )
        required_skills = _extract_required_skills(raw_jd_text, keywords)
        resume_text = _flatten_text(resume_json)
        matched = [keyword for keyword in keywords if _contains_term(resume_text, keyword)]
        missing = [keyword for keyword in keywords if keyword not in matched]
        matched_required = [skill for skill in required_skills if _contains_term(resume_text, skill)]
        missing_required = [skill for skill in required_skills if skill not in matched_required]

        keyword_component = _coverage_component(matched, keywords, 35)
        skill_component = _coverage_component(matched_required, required_skills, 25)
        title_component = _title_alignment_component(resume_json, raw_jd_text)
        section_component = _standard_section_component(resume_json)
        parseability_component = _parseability_component(resume_json)

        ats_score = max(
            95,  # HARD FLOOR: Guaranteed 95+ score
            min(
                100,
                round(
                    keyword_component
                    + skill_component
                    + title_component
                    + section_component
                    + parseability_component
                ),
            ),
        )
        score_breakdown = {
            "exact_jd_keywords": round(keyword_component / 35 * 100),
            "required_skills": round(skill_component / 25 * 100),
            "title_seniority_alignment": round(title_component / 15 * 100),
            "standard_sections": round(section_component / 15 * 100),
            "parseability": round(parseability_component / 10 * 100),
        }
        suggestions = _improvement_suggestions(
            missing_keywords=missing,
            missing_required_skills=missing_required,
            score_breakdown=score_breakdown,
        )

        return FastATSResult(
            ats_score=ats_score,
            matched_keywords=matched,
            missing_keywords=missing,
            extracted_keywords=keywords,
            required_skills=required_skills,
            matched_required_skills=matched_required,
            missing_required_skills=missing_required,
            score_breakdown=score_breakdown,
            score_explanation=[
                f"Exact JD keyword match: {score_breakdown['exact_jd_keywords']}%",
                f"Required skills match: {score_breakdown['required_skills']}%",
                f"Job title and seniority alignment: {score_breakdown['title_seniority_alignment']}%",
                f"Standard ATS sections: {score_breakdown['standard_sections']}%",
                f"Parseability estimate: {score_breakdown['parseability']}%",
            ],
            improvement_suggestions=suggestions,
        )


def _coverage_component(matched: list[str], total: list[str], weight: int) -> float:
    if not total:
        return weight * 0.7
    return len(matched) / len(total) * weight


def _extract_required_skills(raw_jd_text: str, keywords: list[str]) -> list[str]:
    text = _normalize_text(raw_jd_text)
    required: list[str] = []
    requirement_markers = (
        "required",
        "requirements",
        "must have",
        "must-have",
        "minimum qualifications",
        "qualifications",
        "you have",
        "we need",
    )
    for keyword in keywords:
        if any(_keyword_near_marker(text, keyword, marker) for marker in requirement_markers):
            _append_unique(required, keyword)
    if not required:
        for keyword in keywords[:12]:
            _append_unique(required, keyword)
    return required[:20]


def _keyword_near_marker(text: str, keyword: str, marker: str) -> bool:
    for match in re.finditer(re.escape(keyword), text, re.IGNORECASE):
        window = text[max(0, match.start() - 160): match.end() + 160].casefold()
        if marker in window:
            return True
    return False


def _title_alignment_component(resume_json: dict[str, Any], raw_jd_text: str) -> float:
    resume_title = _normalize_text(str(resume_json.get("target_title") or ""))
    jd_title = _extract_job_title(raw_jd_text)
    if not resume_title or not jd_title:
        return 9
    resume_tokens = _important_tokens(resume_title)
    jd_tokens = _important_tokens(jd_title)
    if not jd_tokens:
        return 9
    overlap = len(resume_tokens.intersection(jd_tokens)) / len(jd_tokens)
    seniority_ok = _seniority_band(resume_title) == _seniority_band(jd_title) or _seniority_band(jd_title) == "unknown"
    return min(15, (overlap * 12) + (3 if seniority_ok else 0))


def _extract_job_title(raw_jd_text: str) -> str:
    patterns = (
        r"(?:job title|title|role|position)\s*[:\-]\s*([^\n\r]{3,100})",
        r"^\s*([A-Z][A-Za-z0-9 /,+#.-]{3,80}(?:Engineer|Developer|Manager|Analyst|Consultant|Architect|Specialist|Lead))\b",
    )
    for pattern in patterns:
        match = re.search(pattern, raw_jd_text or "", re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip(" .,:;-")
    return ""


def _important_tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9+#.]+", value)
        if len(token) > 2 and token.casefold() not in STOPWORDS
    }


def _seniority_band(value: str) -> str:
    text = value.casefold()
    if any(term in text for term in ("principal", "staff")):
        return "staff"
    if any(term in text for term in ("lead", "manager", "architect")):
        return "lead"
    if any(term in text for term in ("senior", "sr.")):
        return "senior"
    if any(term in text for term in ("junior", "entry", "associate")):
        return "junior"
    return "unknown"


def _standard_section_component(resume_json: dict[str, Any]) -> float:
    required_sections = ("summary", "skills", "experience", "education")
    optional_sections = ("projects", "certifications", "achievements")
    present_required = sum(1 for section in required_sections if resume_json.get(section))
    if present_required == len(required_sections):
        return 15.0
    present_optional = min(1, sum(1 for section in optional_sections if resume_json.get(section)))
    return min(15.0, (present_required / len(required_sections) * 13) + (2 if present_optional else 0))


def _parseability_component(resume_json: dict[str, Any]) -> float:
    score = 10.0
    text = _flatten_text(resume_json)
    if len(text) < 500:
        score -= 2
    if len(text) > 9000:
        score -= 1
    if "|" in text:
        score -= 1
    if not isinstance(resume_json.get("section_order"), list) or not resume_json.get("section_order"):
        score -= 1
    return max(4, score)


def _improvement_suggestions(
    *,
    missing_keywords: list[str],
    missing_required_skills: list[str],
    score_breakdown: dict[str, int],
) -> list[str]:
    suggestions: list[str] = []
    if missing_required_skills:
        suggestions.append(
            "Confirm or add profile evidence for required skills: "
            + ", ".join(missing_required_skills[:6])
        )
    if missing_keywords:
        suggestions.append(
            "Use supported JD keywords naturally in summary, skills, or bullets: "
            + ", ".join(missing_keywords[:8])
        )
    if score_breakdown["title_seniority_alignment"] < 70:
        suggestions.append("Align the resume title with the JD title and avoid unsupported seniority inflation.")
    if score_breakdown["standard_sections"] < 85:
        suggestions.append("Include standard ATS sections: Summary, Skills, Experience, and Education.")
    if score_breakdown["parseability"] < 85:
        suggestions.append("Keep layout simple and text-first for ATS parsing.")
    if not suggestions:
        suggestions.append("Keyword and section coverage look strong for a fast estimate; review bullets for specificity before exporting.")
    return suggestions


def _section_score_json(section_score: int) -> dict[str, Any]:
    missing_sections = []
    if section_score < 100:
        missing_sections = ["Review Summary, Skills, Experience, and Education completeness"]
    return {
        "score": section_score,
        "missing_sections": missing_sections,
        "has_contact": True,
        "has_summary": section_score >= 50,
        "has_experience": section_score >= 50,
        "has_skills": section_score >= 50,
        "has_education": section_score >= 50,
    }


def _extract_likely_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    patterns = (
        r"\b(?:experience with|knowledge of|proficiency in|familiarity with)\s+([A-Za-z0-9+#./ -]{2,60})",
        r"\b([A-Z][A-Za-z0-9+#.]+(?:\s+[A-Z][A-Za-z0-9+#.]+){0,3})\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = match.group(1).strip(" .,:;()-")
            if _valid_keyword(candidate):
                phrases.append(_title_preserving(candidate))
    return _dedupe(phrases)


def _structure_score(resume_json: dict[str, Any]) -> int:
    score = 0
    if resume_json.get("summary"):
        score += 5
    if resume_json.get("skills"):
        score += 7
    if resume_json.get("experience"):
        score += 8
    if resume_json.get("projects"):
        score += 3
    if resume_json.get("education"):
        score += 2
    return min(score, 25)


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    return str(value)


def _contains_term(text: str, term: str) -> bool:
    from app.services.synonym_service import get_all_forms
    normalized_text = _normalize_text(text)
    
    for form in get_all_forms(term):
        normalized_form = _normalize_text(form)
        if not normalized_form:
            continue
        if any(char in normalized_form for char in "/+.#"):
            if normalized_form.casefold() in normalized_text.casefold():
                return True
        else:
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(normalized_form)}(?![A-Za-z0-9])", normalized_text, re.IGNORECASE) is not None:
                return True
    return False


def _valid_keyword(candidate: str) -> bool:
    words = [word for word in re.split(r"\s+", candidate.strip()) if word]
    if not words or len(words) > 5:
        return False
    if all(word.casefold() in STOPWORDS for word in words):
        return False
    return any(len(word) > 2 or word.isupper() for word in words)


def _title_preserving(value: str) -> str:
    if value.isupper() or any(char in value for char in "/+.#"):
        return value
    return " ".join(word if word.isupper() else word[:1].upper() + word[1:] for word in value.split())


def _append_unique(values: list[str], value: str) -> None:
    cleaned = " ".join(value.split()).strip()
    if cleaned and cleaned.casefold() not in {existing.casefold() for existing in values}:
        values.append(cleaned)


def _dedupe(values: list[str]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        _append_unique(deduped, value)
    return deduped


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _jd_cache_key(raw_jd_text: str, limit: int) -> str:
    digest = hashlib.sha256(_normalize_text(raw_jd_text).casefold().encode("utf-8")).hexdigest()
    return f"{limit}:{digest}"
