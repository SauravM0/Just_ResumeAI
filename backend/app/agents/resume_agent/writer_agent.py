from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.ai.gemini_client import GeminiClientError
from app.ai.orchestrators.resume_orchestrator import generate_recommendation
from app.ai.resume_fallback import generate_recommendation_without_ai
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import ResumeRecommendation, ResumeSkillGroup
from app.services.candidate_evidence_service import KeywordTruthReport
from app.services.keyword_placement_service import inject_missing_keywords

logger = logging.getLogger(__name__)

_FALLBACK_WARNING = (
    "AI resume generation was temporarily unavailable. "
    "A rule-based fallback was used instead. Review the output carefully."
)


class WriterAgentResult(BaseModel):
    recommendation: ResumeRecommendation
    fallback_used: bool = False
    warnings: list[str] = Field(default_factory=list)


class WriterAgent:
    async def run(
        self,
        *,
        profile: MasterProfile,
        parsed_jd: ParsedJD,
        generation_id: str,
        ats_plan: ATSKeywordPlannerOutput,
        evidence_report: KeywordTruthReport,
        emphasis: str | None = None,
        target_pages: int = 1,
        additional_alignment_text: str | None = None,
        rejected_ids: list[str] | None = None,
        locked_bullets: dict[str, str] | None = None,
    ) -> WriterAgentResult:
        logger.info("resume_agent.writer_agent.started")
        fallback_used = False
        warnings: list[str] = []
        try:
            recommendation = await generate_recommendation(
                profile=profile,
                parsed_jd=parsed_jd,
                generation_id=generation_id,
                emphasis=emphasis,
                rejected_ids=rejected_ids,
                locked_bullets=locked_bullets,
                target_pages=target_pages,
                additional_alignment_text=additional_alignment_text,
                ats_plan=ats_plan,
            )
        except GeminiClientError:
            fallback_used = True
            warnings.append(_FALLBACK_WARNING)
            logger.warning("resume_agent.writer_agent.fallback generation_id=%s", generation_id)
            recommendation = generate_recommendation_without_ai(
                profile=profile,
                parsed_jd=parsed_jd,
                generation_id=generation_id,
                emphasis=emphasis,
                rejected_ids=rejected_ids,
                locked_bullets=locked_bullets,
                target_pages=target_pages,
                additional_alignment_text=additional_alignment_text,
                ats_plan=ats_plan,
            )

        recommendation = inject_missing_keywords(
            recommendation=recommendation,
            parsed_jd=parsed_jd,
            ats_plan=ats_plan,
            profile=profile,
        )
        recommendation = _remove_unsupported_skill_claims(recommendation, evidence_report)
        recommendation.target_title = ats_plan.target_resume_title or recommendation.target_title
        recommendation.warnings = _dedupe([*recommendation.warnings, *warnings])
        logger.info(
            "resume_agent.writer_agent.completed fallback=%s experiences=%s projects=%s",
            fallback_used,
            len(recommendation.experience),
            len(recommendation.projects),
        )
        return WriterAgentResult(
            recommendation=recommendation,
            fallback_used=fallback_used,
            warnings=warnings,
        )


def _remove_unsupported_skill_claims(
    recommendation: ResumeRecommendation,
    report: KeywordTruthReport,
) -> ResumeRecommendation:
    rec = recommendation.model_copy(deep=True)
    truth_terms = {
        _key(term)
        for term in [*report.source_supported, *report.adjacent_or_learning, *report.unsupported]
    }
    filtered: list[ResumeSkillGroup] = []
    for group in rec.skills:
        is_learning_group = group.category.casefold() == "learning focus"
        safe_skills = []
        for skill in group.skills:
            key = _key(skill)
            if key not in truth_terms:
                safe_skills.append(skill)
                continue
            truth = report.truth_for(skill)
            if truth == "source_supported":
                safe_skills.append(skill)
            elif truth == "adjacent_or_learning" and is_learning_group:
                safe_skills.append(skill)
        if safe_skills:
            filtered.append(group.model_copy(update={"skills": safe_skills}))
    rec.skills = filtered
    return rec


def _key(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split())


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


writer_agent = WriterAgent()
