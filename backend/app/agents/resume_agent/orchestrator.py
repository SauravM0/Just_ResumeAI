from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from app.agents.resume_agent.ats_agent import ATSAgentResult, ats_agent
from app.agents.resume_agent.evidence_agent import evidence_agent
from app.agents.resume_agent.export_gate import export_gate_agent
from app.agents.resume_agent.jd_agent import jd_agent
from app.agents.resume_agent.profile_agent import profile_agent
from app.agents.resume_agent.recruiter_review_agent import RecruiterReview, recruiter_review_agent
from app.agents.resume_agent.strategy_agent import StrategyAgentResult, strategy_agent
from app.agents.resume_agent.writer_agent import writer_agent
from app.schemas.alignment import ATSAlignmentReport
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import ResumeRecommendation
from app.schemas.scoring import ATSScore
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_pre_check import ATSPreCheckResult, validate_ats_readiness
from app.services.candidate_evidence_service import KeywordTruthReport

logger = logging.getLogger(__name__)


class ResumeAgentOptions(BaseModel):
    generation_id: str = "resume-agent"
    target_pages: int = Field(default=1, ge=1, le=2)
    emphasis: str | None = None
    additional_alignment_text: str | None = None
    rejected_ids: list[str] = Field(default_factory=list)
    locked_bullets: dict[str, str] = Field(default_factory=dict)


class ResumeAgentRunResult(BaseModel):
    parsed_jd: ParsedJD
    resume_recommendation: ResumeRecommendation
    ats_score: ATSScore
    recruiter_review: RecruiterReview
    warnings: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    evidence_report: KeywordTruthReport
    export_ready: bool = False
    ats_plan: ATSKeywordPlannerOutput
    alignment_report: ATSAlignmentReport
    ats_pre_check: ATSPreCheckResult | None = None
    safe_improvements: list[str] = Field(default_factory=list)
    missing_supported_keywords: list[str] = Field(default_factory=list)


class ResumeAgentOrchestrator:
    def validate_jd_intake(self, raw_jd: str) -> tuple[str, list[str]]:
        return jd_agent.validate_intake(raw_jd)

    async def run(
        self,
        raw_jd: str,
        candidate_profile: MasterProfile | dict,
        options: ResumeAgentOptions | dict | None = None,
    ) -> ResumeAgentRunResult:
        opts = _options(options)
        logger.info("resume_agent.orchestrator.started generation_id=%s", opts.generation_id)

        # ── Phase 1: JD analysis + profile parsing (independent, parallel) ──
        jd_task = jd_agent.run(raw_jd)
        profile_task = asyncio.to_thread(profile_agent.run, candidate_profile)
        jd_result, profile_result = await asyncio.gather(jd_task, profile_task)

        # ── Phase 2: Strategy + evidence (sequential — evidence needs ats_plan) ──
        strategy_result = strategy_agent.run(
            jd_result.parsed_jd,
            profile_result.profile,
            emphasis=opts.emphasis,
            target_pages=opts.target_pages,
        )
        evidence_result = evidence_agent.run(
            jd_result.parsed_jd,
            profile_result.profile,
            strategy_result.ats_plan,
        )

        # ── Phase 3: Writer (async — needs all previous results) ──
        writer_result = await writer_agent.run(
            profile=profile_result.profile,
            parsed_jd=jd_result.parsed_jd,
            generation_id=opts.generation_id,
            ats_plan=strategy_result.ats_plan,
            evidence_report=evidence_result.report,
            emphasis=opts.emphasis,
            target_pages=opts.target_pages,
            additional_alignment_text=opts.additional_alignment_text,
            rejected_ids=opts.rejected_ids,
            locked_bullets=opts.locked_bullets,
        )

        # ── Phase 4a: ATS scoring + export gate (independent, parallel) ──
        t_ats = asyncio.to_thread(
            _score,
            writer_result.recommendation,
            jd_result.parsed_jd,
            profile_result.profile,
            strategy_result,
            evidence_result.report,
            opts,
        )
        t_export = asyncio.to_thread(
            export_gate_agent.run,
            writer_result.recommendation,
            jd_result.parsed_jd,
            profile_result.profile,
        )

        ats_result, export_result = await asyncio.gather(t_ats, t_export)

        # ── Phase 4b: Recruiter review (needs ats_score from Phase 4a) ──
        recruiter_review = recruiter_review_agent.run(
            writer_result.recommendation,
            ats_result.ats_score,
        )

        final_recommendation = export_result.recommendation
        if export_result.export_ready and final_recommendation != writer_result.recommendation:
            ats_result = _score(
                final_recommendation,
                jd_result.parsed_jd,
                profile_result.profile,
                strategy_result,
                evidence_result.report,
                opts,
            )
            recruiter_review = recruiter_review_agent.run(
                final_recommendation,
                ats_result.ats_score,
            )

        alignment_report = build_ats_alignment_report(
            parsed_jd=jd_result.parsed_jd,
            recommendation=final_recommendation,
            formatting_score=ats_result.ats_score.format_score,
            ats_plan=strategy_result.ats_plan,
        )
        ats_pre_check = validate_ats_readiness(final_recommendation, jd_result.parsed_jd)
        blocked_reasons = _dedupe([*export_result.blocked_reasons, *recruiter_review.issues])
        warnings = _dedupe(
            [
                *jd_result.warnings,
                *strategy_result.ats_plan.seniority_warnings,
                *writer_result.warnings,
                *final_recommendation.warnings,
                *export_result.warnings,
                *recruiter_review.warnings,
                *ats_pre_check.critical_gaps,
                *ats_pre_check.warnings,
            ]
        )
        export_ready = export_result.export_ready and recruiter_review.passed
        logger.info(
            "resume_agent.orchestrator.completed generation_id=%s export_ready=%s blocked=%s",
            opts.generation_id,
            export_ready,
            len(blocked_reasons),
        )
        return ResumeAgentRunResult(
            parsed_jd=jd_result.parsed_jd,
            resume_recommendation=final_recommendation,
            ats_score=ats_result.ats_score,
            recruiter_review=recruiter_review,
            warnings=warnings,
            blocked_reasons=blocked_reasons,
            evidence_report=evidence_result.report,
            export_ready=export_ready,
            ats_plan=strategy_result.ats_plan,
            alignment_report=alignment_report,
            ats_pre_check=ats_pre_check,
            safe_improvements=ats_result.safe_improvements,
            missing_supported_keywords=ats_result.missing_supported_keywords,
        )


def _score(
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    strategy_result: StrategyAgentResult,
    evidence_report: KeywordTruthReport,
    options: ResumeAgentOptions,
) -> ATSAgentResult:
    return ats_agent.run(
        recommendation,
        parsed_jd,
        profile,
        strategy_result.ats_plan,
        evidence_report,
        target_pages=options.target_pages,
    )


def _options(options: ResumeAgentOptions | dict | None) -> ResumeAgentOptions:
    if options is None:
        return ResumeAgentOptions()
    if isinstance(options, ResumeAgentOptions):
        return options
    return ResumeAgentOptions.model_validate(options)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


resume_agent_orchestrator = ResumeAgentOrchestrator()
