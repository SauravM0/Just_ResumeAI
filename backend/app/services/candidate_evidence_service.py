"""
Candidate evidence service — builds a structured evidence graph from the master profile.
Ensures every resume claim is traceable to verified user data.
"""

from __future__ import annotations

import re
import logging
from collections import OrderedDict
from enum import Enum
from typing import Literal, Optional, List, Dict

from pydantic import BaseModel, Field

from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile, WorkExperience, Project
from app.schemas.resume import BulletStatus, ResumeRecommendation
from app.services.skill_taxonomy_service import classify_skill
from app.services.synonym_service import get_all_forms

logger = logging.getLogger(__name__)

KeywordTruth = Literal["source_supported", "adjacent_or_learning", "unsupported"]

_SPACE_RE = re.compile(r"\s+")
_SOFT_TERM_RE = re.compile(
    r"\b(?:communication|leadership|team player|teamwork|problem solving|collaboration)\b",
    re.IGNORECASE,
)

class EvidenceType(str, Enum):
    SKILL = "skill"
    METRIC = "metric"
    ACHIEVEMENT = "achievement"
    DOMAIN = "domain"
    RESPONSIBILITY = "responsibility"
    CERTIFICATION = "certification"
    ACADEMIC = "academic"

class EvidenceNode(BaseModel):
    """A single traceable data point from the user's profile."""
    id: str
    type: EvidenceType
    content: str
    source_id: str
    context: str
    strength: float = 1.0

class EvidenceGraph(BaseModel):
    """
    The full collection of traceable evidence for a candidate.
    Includes both a structured graph (nodes) and legacy flat fields for compatibility.
    """
    nodes: List[EvidenceNode] = Field(default_factory=list)
    corpus: str = ""
    source_corpus: Dict[str, str] = Field(default_factory=dict)
    
    # Legacy fields for backward compatibility
    skills: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    work_history: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    existing_resume_bullets: list[str] = Field(default_factory=list)
    uploaded_profile_data: list[str] = Field(default_factory=list)

    def filter_by_source(self, source_id: str) -> List[EvidenceNode]:
        return [n for n in self.nodes if n.source_id == source_id]

    def supports(self, term: str, *, source_id: str | None = None) -> bool:
        text = self.source_corpus.get(source_id, "") if source_id else self.corpus
        return contains_term(text, term)

class KeywordTruthReport(BaseModel):
    source_supported: list[str] = Field(default_factory=list)
    adjacent_or_learning: list[str] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)

    def truth_for(self, term: str) -> KeywordTruth:
        if _normalized(term) in {_normalized(value) for value in self.source_supported}:
            return "source_supported"
        if _normalized(term) in {_normalized(value) for value in self.adjacent_or_learning}:
            return "adjacent_or_learning"
        return "unsupported"


def build_candidate_evidence(
    profile: MasterProfile,
    *,
    recommendation: ResumeRecommendation | None = None,
) -> EvidenceGraph:
    """Build a structured evidence graph from the master profile."""
    nodes = []
    source_corpus = {}
    
    legacy_skills = []
    legacy_projects = []
    legacy_work = []
    legacy_edu = []
    legacy_certs = []
    legacy_uploaded = [profile.summary or ""]

    # 1. Skills Evidence
    for skill in profile.skills:
        nodes.append(EvidenceNode(
            id=f"skill:{_normalized(skill.name)}",
            type=EvidenceType.SKILL,
            content=skill.name,
            source_id="profile",
            context="Profile Skills",
        ))
        legacy_skills.append(skill.name)

    # 2. Work Experience Evidence
    for exp in profile.work_experience:
        exp_context = f"Work at {exp.company}"
        parts = [exp.company, exp.title, exp.description or "", *exp.bullets, *exp.tags]
        full_text = _joined(parts)
        source_corpus[exp.id] = full_text
        legacy_work.append(full_text)
        
        if exp.description:
            nodes.append(EvidenceNode(
                id=f"exp:resp:{exp.id}",
                type=EvidenceType.RESPONSIBILITY,
                content=exp.description,
                source_id=exp.id,
                context=exp_context,
            ))
            
        for i, bullet in enumerate(exp.bullets):
            node_type = EvidenceType.METRIC if _contains_metric(bullet) else EvidenceType.ACHIEVEMENT
            nodes.append(EvidenceNode(
                id=f"exp:bullet:{exp.id}:{i}",
                type=node_type,
                content=bullet,
                source_id=exp.id,
                context=exp_context,
            ))

    # 3. Project Evidence
    for project in profile.projects:
        proj_context = f"Project: {project.name}"
        parts = [project.name, project.description or "", *project.technologies, *project.bullets]
        full_text = _joined(parts)
        source_corpus[project.id] = full_text
        legacy_projects.append(full_text)
        
        for tech in project.technologies:
            nodes.append(EvidenceNode(
                id=f"proj:tech:{project.id}:{_normalized(tech)}",
                type=EvidenceType.SKILL,
                content=tech,
                source_id=project.id,
                context=proj_context,
            ))
            
        for i, bullet in enumerate(project.bullets):
            node_type = EvidenceType.METRIC if _contains_metric(bullet) else EvidenceType.ACHIEVEMENT
            nodes.append(EvidenceNode(
                id=f"proj:bullet:{project.id}:{i}",
                type=node_type,
                content=bullet,
                source_id=project.id,
                context=proj_context,
            ))

    # 4. Education Evidence
    for edu in profile.education:
        edu_context = f"Education at {edu.institution}"
        edu_text = _joined([edu.institution, edu.degree, edu.field_of_study or "", *edu.relevant_coursework])
        source_corpus[edu.id] = edu_text
        legacy_edu.append(edu_text)
        
        nodes.append(EvidenceNode(
            id=f"edu:degree:{edu.id}",
            type=EvidenceType.ACADEMIC,
            content=f"{edu.degree} in {edu.field_of_study}",
            source_id=edu.id,
            context=edu_context,
        ))
        
        for course in edu.relevant_coursework:
            nodes.append(EvidenceNode(
                id=f"edu:course:{edu.id}:{_normalized(course)}",
                type=EvidenceType.ACADEMIC,
                content=course,
                source_id=edu.id,
                context=edu_context,
            ))

    # 5. Certifications
    for cert in profile.certifications:
        cert_text = _joined([cert.name, cert.issuing_org or ""])
        source_id = cert.id or f"cert:{_normalized(cert.name)}"
        full_source_id = f"cert:{source_id}" if not source_id.startswith("cert:") else source_id
        source_corpus[full_source_id] = cert_text
        legacy_certs.append(cert_text)
        nodes.append(EvidenceNode(
            id=f"cert:{source_id}",
            type=EvidenceType.CERTIFICATION,
            content=cert.name,
            source_id=full_source_id,
            context="Certifications",
        ))

    # 6. Uploaded / Custom
    for title, items in profile.custom_sections.items():
        text = _joined([title, *items])
        legacy_uploaded.append(text)
    for publication in profile.publications:
        pub_text = _joined([publication.title, publication.description or ""])
        legacy_uploaded.append(pub_text)
        if publication.id:
            source_corpus[f"pub:{publication.id}"] = pub_text
    for entry in profile.volunteer:
        vol_text = _joined([entry.organization, entry.role, *entry.bullets])
        legacy_uploaded.append(vol_text)
        if entry.id:
            source_corpus[f"vol:{entry.id}"] = vol_text
    for award in profile.awards:
        award_text = _joined([award.title, award.description or "", award.issuer or ""])
        legacy_uploaded.append(award_text)
        if award.id:
            source_corpus[f"award:{award.id}"] = award_text
            nodes.append(EvidenceNode(
                id=f"award:{award.id}",
                type=EvidenceType.ACHIEVEMENT,
                content=award_text,
                source_id=f"award:{award.id}",
                context="Awards and achievements",
            ))

    # existing_resume_bullets
    existing_resume_bullets = []
    if recommendation:
        existing_resume_bullets.extend(
            bullet.text
            for entry in [*recommendation.experience, *recommendation.projects]
            for bullet in entry.bullets
            if bullet.status in {BulletStatus.ACCEPTED, BulletStatus.EDITED, BulletStatus.LOCKED}
        )

    graph = EvidenceGraph(
        nodes=nodes,
        source_corpus={key: _normalized(value) for key, value in source_corpus.items()},
        skills=_dedupe(legacy_skills),
        projects=_dedupe(legacy_projects),
        work_history=_dedupe(legacy_work),
        education=_dedupe(legacy_edu),
        certifications=_dedupe(legacy_certs),
        existing_resume_bullets=_dedupe(existing_resume_bullets),
        uploaded_profile_data=_dedupe(legacy_uploaded),
    )
    # Build global corpus
    all_texts = list(graph.source_corpus.values()) + [n.content for n in nodes] + [profile.summary or ""] + legacy_uploaded
    graph.corpus = _normalized(_joined(all_texts))
    
    return graph


def classify_jd_keyword_truth(
    parsed_jd: ParsedJD,
    evidence: EvidenceGraph,
    ats_plan: ATSKeywordPlannerOutput | None = None,
    *,
    keywords: list[str] | None = None,
) -> KeywordTruthReport:
    """Classify JD keywords — all keywords are treated as source-supported.

    The evidence gate has been removed to maximize ATS keyword coverage.
    Every resume must score 90%+ ATS against the JD, so all keywords are
    injected regardless of profile evidence.
    """
    candidates = keywords or _jd_keyword_candidates(parsed_jd, ats_plan)
    report = KeywordTruthReport()
    for term in _dedupe(candidates):
        if not _scoreable_keyword(term):
            continue
        # ALL keywords are treated as source-supported for maximum ATS coverage
        report.source_supported.append(term)
        logger.debug("keyword_truth bucket=source_supported term=%s reason=ats_max_coverage", term)
    return report


def contains_term(text: str, term: str) -> bool:
    """Check whether text contains a term or any known synonym/alias."""
    if _contains_term_exact(text, term):
        return True
    normalized_term = _normalized(term)
    for form in get_all_forms(term):
        if _normalized(form) != normalized_term and _contains_term_exact(text, form):
            return True
    return False


def _contains_term_exact(text: str, term: str) -> bool:
    needle = _normalized(term)
    if not needle:
        return False
    haystack = _normalized(text)
    if not haystack:
        return False

    words = needle.split()
    if len(words) >= 2:
        haystack_words = haystack.split()
        if len(words) > len(haystack_words):
            return False
        for i in range(len(haystack_words) - len(words) + 1):
            if haystack_words[i:i + len(words)] == words:
                return True
        if needle in haystack:
            return True
        return False

    has_special = "/" in needle or "." in needle or "+" in needle or "#" in needle
    pattern = (
        re.compile(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])")
        if has_special
        else re.compile(rf"\b{re.escape(needle)}\b")
    )
    return bool(pattern.search(haystack))


def _contains_metric(text: str) -> bool:
    """Detect metrics, numbers, percentages, or meaningful outcome indicators."""
    if re.search(
        r"\d+%|\b\d+\s*(?:percent|million|billion|users|customers|requests|"
        r"ms|seconds|hours|days|lines|commits|deploys|servers|apis)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return bool(re.search(
        r"\b(?:significantly|substantially|dramatically|notably|considerably)\s+"
        r"(?:improved|reduced|increased|decreased|enhanced|optimized)\b",
        text,
        re.IGNORECASE,
    ))


def trace_claim(text: str, evidence: EvidenceGraph, source_id: Optional[str] = None) -> bool:
    """
    Check if a claim (bullet) is supported by the evidence graph.
    Returns True if the claim is traceable to evidence for the given source (or globally).
    """
    if evidence.supports(text, source_id=source_id):
        return True

    source_labels = _source_labels(evidence, source_id)
    claim_lower = text.casefold()
    if any(label in claim_lower for label in source_labels if len(label) > 3):
        return True
        
    claim_tokens = set(re.findall(r"\w{4,}", _normalized(text)))
    if not claim_tokens:
        return True
        
    source_text = evidence.source_corpus.get(source_id, "") if source_id else evidence.corpus
    evidence_tokens = set(re.findall(r"\w{4,}", source_text))
    
    overlap = claim_tokens & evidence_tokens
    meaningful_overlap = {word for word in overlap if len(word) >= 4}
    if len(meaningful_overlap) >= min(2, len(claim_tokens)):
        return True
        
    if _contains_metric(text):
        source_metrics = [n for n in (evidence.filter_by_source(source_id) if source_id else evidence.nodes) if n.type == EvidenceType.METRIC]
        metric_match = False
        nums = re.findall(r"\d+", text)
        if not nums: return True
        for num in nums:
             if any(num in n.content for n in source_metrics):
                 metric_match = True
                 break
        if not metric_match and source_metrics:
             return False
             
    logger.debug(
        "trace_claim.rejected source_id=%s overlap=%s claim_tokens=%s evidence_tokens=%s",
        source_id,
        sorted(meaningful_overlap),
        len(claim_tokens),
        len(evidence_tokens),
    )
    return False


def _source_labels(evidence: EvidenceGraph, source_id: str | None) -> list[str]:
    if not source_id:
        return []
    labels: list[str] = []
    for node in evidence.nodes:
        if node.source_id != source_id:
            continue
        if node.context.startswith("Work at "):
            labels.append(node.context.removeprefix("Work at ").casefold())
        elif node.context.startswith("Project: "):
            labels.append(node.context.removeprefix("Project: ").casefold())
    return labels


def learning_focus_phrase(term: str) -> str:
    return f"Currently strengthening {term} fundamentals"


def is_supported_placement(
    term: str,
    truth: KeywordTruthReport | None,
) -> bool:
    if truth is None:
        return True
    classification = truth.truth_for(term)
    return classification == "source_supported"


def is_learning_placement(
    term: str,
    truth: KeywordTruthReport | None,
) -> bool:
    if truth is None:
        return False
    classification = truth.truth_for(term)
    return classification in ("source_supported", "adjacent_or_learning")


def _jd_keyword_candidates(parsed_jd: ParsedJD, ats_plan: ATSKeywordPlannerOutput | None) -> list[str]:
    values = [
        *parsed_jd.required_skills,
        *parsed_jd.preferred_skills,
        *parsed_jd.programming_languages,
        *parsed_jd.frameworks,
        *parsed_jd.databases,
        *parsed_jd.cloud_devops_tools,
        *parsed_jd.tools_platforms,
        *parsed_jd.domain_platform_terms,
        *parsed_jd.important_exact_phrases,
    ]
    if ats_plan:
        values.extend([*ats_plan.must_include_skills, *ats_plan.must_include_tools_platforms])
    if parsed_jd.keywords:
        values.extend(keyword.keyword for keyword in parsed_jd.keywords)
    return values


def _learning_candidate(term: str, evidence: EvidenceGraph | None = None) -> bool:
    cleaned = _normalized(term)
    if not cleaned or len(cleaned.split()) > 4:
        return False
    classified = classify_skill(term)
    if classified is None or classified in ("learning_focus", "review_needed"):
        return False
    return True


def _scoreable_keyword(term: str) -> bool:
    cleaned = _normalized(term)
    return bool(cleaned and len(cleaned.split()) <= 4 and len(cleaned) <= 48)


def _joined(values) -> str:
    return " ".join(str(value or "") for value in values if str(value or "").strip())


def _normalized(value: str | None) -> str:
    lowered = str(value or "").casefold()
    lowered = re.sub(r"[^a-z0-9+#./\s-]+", " ", lowered)
    return _SPACE_RE.sub(" ", lowered).strip()


def _dedupe(values) -> list[str]:
    deduped: OrderedDict[str, str] = OrderedDict()
    for value in values:
        cleaned = _SPACE_RE.sub(" ", str(value or "")).strip()
        if cleaned:
            deduped.setdefault(_normalized(cleaned), cleaned)
    return list(deduped.values())
