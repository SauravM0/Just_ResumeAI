from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.schemas.jd import ParsedJD
from app.schemas.profile import MasterProfile
from app.schemas.resume import ResumeRecommendation
from app.services.jd_sanitization_service import (
    ResumeContaminationError,
    assert_parsed_jd_safe,
    assert_render_text_safe,
    assert_resume_recommendation_safe,
    recommendation_to_plain_text,
)
from app.services.resume_validation_gate import ResumeValidationError, validate_resume_for_export

logger = logging.getLogger(__name__)


class ExportGateResult(BaseModel):
    recommendation: ResumeRecommendation
    export_ready: bool = False
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExportGateAgent:
    def run(
        self,
        recommendation: ResumeRecommendation,
        parsed_jd: ParsedJD,
        profile: MasterProfile,
    ) -> ExportGateResult:
        logger.info("resume_agent.export_gate.started")
        try:
            validation = validate_resume_for_export(
                recommendation,
                parsed_jd=parsed_jd,
                profile=profile,
            )
            rec = validation.recommendation
            assert_parsed_jd_safe(parsed_jd)
            assert_resume_recommendation_safe(rec)
            assert_render_text_safe(
                recommendation_to_plain_text(rec),
                artifact="recommendation_plain_text",
            )
        except ResumeValidationError as exc:
            reasons = [
                f"{issue.path}: {issue.message}" if issue.path else issue.message
                for issue in exc.issues
            ]
            logger.warning("resume_agent.export_gate.blocked validation=%s", reasons[:4])
            return ExportGateResult(
                recommendation=recommendation,
                export_ready=False,
                blocked_reasons=reasons,
            )
        except ResumeContaminationError as exc:
            logger.warning("resume_agent.export_gate.blocked contamination=%s", exc)
            return ExportGateResult(
                recommendation=recommendation,
                export_ready=False,
                blocked_reasons=[str(exc)],
            )

        warnings = [
            f"{issue.path}: {issue.message}" if issue.path else issue.message
            for issue in validation.issues
            if issue.severity.value in {"warning", "error"}
        ]
        logger.info("resume_agent.export_gate.completed ready=true warnings=%s", len(warnings))
        return ExportGateResult(
            recommendation=rec,
            export_ready=True,
            warnings=warnings,
        )


export_gate_agent = ExportGateAgent()
