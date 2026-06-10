from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.ai.orchestrators.jd_orchestrator import analyze_jd
from app.schemas.jd import ParsedJD
from app.services.jd_sanitization_service import InvalidJobDescriptionError, require_valid_jd_text

logger = logging.getLogger(__name__)

_MIN_JD_LENGTH = 50


class JDAgentResult(BaseModel):
    parsed_jd: ParsedJD
    clean_jd_text: str
    warnings: list[str] = Field(default_factory=list)


class JDAgent:
    def validate_intake(self, raw_jd: str) -> tuple[str, list[str]]:
        sanitization = require_valid_jd_text(raw_jd)
        clean_text = sanitization.clean_text.strip()
        if len(clean_text) < _MIN_JD_LENGTH:
            raise InvalidJobDescriptionError(
                f"Job description is too short after cleanup ({len(clean_text)} characters)."
            )
        return clean_text, list(sanitization.warnings)

    async def run(self, raw_jd: str) -> JDAgentResult:
        logger.info("resume_agent.jd_agent.started")
        clean_text, warnings = self.validate_intake(raw_jd)
        parsed_jd = await analyze_jd(clean_text)
        logger.info("resume_agent.jd_agent.completed title=%s", parsed_jd.job_title)
        return JDAgentResult(
            parsed_jd=parsed_jd,
            clean_jd_text=clean_text,
            warnings=warnings,
        )


jd_agent = JDAgent()
