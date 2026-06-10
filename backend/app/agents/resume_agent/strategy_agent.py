from __future__ import annotations

import logging

from pydantic import BaseModel

from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.services.resume_strategy_service import ResumeStrategy, build_resume_strategy

logger = logging.getLogger(__name__)


class StrategyAgentResult(BaseModel):
    strategy: ResumeStrategy
    ats_plan: ATSKeywordPlannerOutput


class StrategyAgent:
    def run(
        self,
        parsed_jd: ParsedJD,
        profile: MasterProfile,
        *,
        emphasis: str | None = None,
        target_pages: int = 1,
    ) -> StrategyAgentResult:
        logger.info("resume_agent.strategy_agent.started")
        strategy = build_resume_strategy(parsed_jd, profile)
        ats_plan = build_ats_keyword_plan(
            parsed_jd=parsed_jd,
            profile=profile,
            emphasis=emphasis,
            target_pages=target_pages,
        )
        logger.info(
            "resume_agent.strategy_agent.completed classification=%s title=%s",
            strategy.classification.value,
            ats_plan.target_resume_title,
        )
        return StrategyAgentResult(strategy=strategy, ats_plan=ats_plan)


strategy_agent = StrategyAgent()
