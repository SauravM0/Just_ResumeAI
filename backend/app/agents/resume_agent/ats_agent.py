from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import ResumeRecommendation
from app.schemas.scoring import ATSScore
from app.services.candidate_evidence_service import KeywordTruthReport
from app.services.scoring_service import compute_ats_score

logger = logging.getLogger(__name__)


class ATSAgentResult(BaseModel):
    ats_score: ATSScore
    missing_supported_keywords: list[str] = Field(default_factory=list)
    safe_improvements: list[str] = Field(default_factory=list)


class ATSAgent:
    def run(
        self,
        recommendation: ResumeRecommendation,
        parsed_jd: ParsedJD,
        profile: MasterProfile,
        ats_plan: ATSKeywordPlannerOutput,
        evidence_report: KeywordTruthReport,
        *,
        target_pages: int = 1,
    ) -> ATSAgentResult:
        logger.info("resume_agent.ats_agent.started")
        ats_score = compute_ats_score(
            recommendation,
            parsed_jd,
            ats_plan=ats_plan,
            profile=profile,
            target_pages=target_pages,
        )
        supported = {_key(term): term for term in evidence_report.source_supported}
        missing_supported = [
            supported[_key(term)]
            for term in ats_score.missing_keywords
            if _key(term) in supported
        ]
        safe_improvements = list(ats_score.recommendations[:8])
        if missing_supported:
            safe_improvements.insert(
                0,
                f"Use supported evidence for missing ATS terms: {', '.join(missing_supported[:6])}.",
            )
        logger.info(
            "resume_agent.ats_agent.completed score=%.1f missing_supported=%s",
            ats_score.overall_score,
            len(missing_supported),
        )
        return ATSAgentResult(
            ats_score=ats_score,
            missing_supported_keywords=_dedupe(missing_supported),
            safe_improvements=_dedupe(safe_improvements),
        )


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


ats_agent = ATSAgent()
