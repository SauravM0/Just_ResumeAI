from __future__ import annotations

import logging

from pydantic import BaseModel

from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.services.candidate_evidence_service import (
    EvidenceGraph,
    KeywordTruthReport,
    build_candidate_evidence,
    classify_jd_keyword_truth,
)

logger = logging.getLogger(__name__)


class EvidenceAgentResult(BaseModel):
    evidence: EvidenceGraph
    report: KeywordTruthReport


class EvidenceAgent:
    def run(
        self,
        parsed_jd: ParsedJD,
        profile: MasterProfile,
        ats_plan: ATSKeywordPlannerOutput | None = None,
    ) -> EvidenceAgentResult:
        logger.info("resume_agent.evidence_agent.started")
        evidence = build_candidate_evidence(profile)
        report = classify_jd_keyword_truth(parsed_jd, evidence, ats_plan)
        logger.info(
            "resume_agent.evidence_agent.completed supported=%s adjacent=%s unsupported=%s",
            len(report.source_supported),
            len(report.adjacent_or_learning),
            len(report.unsupported),
        )
        return EvidenceAgentResult(evidence=evidence, report=report)


evidence_agent = EvidenceAgent()
