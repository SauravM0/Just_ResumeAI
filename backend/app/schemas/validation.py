"""
Standardized validation response object shared across all endpoints.

Every API response that involves JD analysis, resume generation, scoring,
or export includes a `validation_status` field using these types.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ValidationSeverity(str, Enum):
    """How urgently the frontend should surface this status."""
    PASS = "pass"
    WARNING = "warning"
    BLOCKED = "blocked"


class ValidationStatus(BaseModel):
    """
    Standard validation status attached to every endpoint response where
    export readiness is relevant (JD analysis, resume generation, scoring, export).

    Frontends use this to render:
    - **Red blocked cards** when severity=blocked (fatal issues).
    - **Yellow warning cards** when severity=warning (non-fatal issues).
    - Suggested fixes from `repair_actions`.
    - User-facing action buttons from `user_actions`.
    """

    export_ready: bool = Field(
        default=False,
        description="True only when validation gate passes in export mode with zero blocking issues.",
    )
    severity: ValidationSeverity = Field(
        default=ValidationSeverity.PASS,
        description=(
            "'pass' = ready to export, "
            "'warning' = non-fatal issues found, "
            "'blocked' = fatal issues prevent export."
        ),
    )
    blocked_reasons: list[str] = Field(
        default_factory=list,
        description="Human-readable reasons the export is blocked (empty when severity != blocked).",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking warnings the user should review before export.",
    )
    repair_actions: list[str] = Field(
        default_factory=list,
        description="Automated repair actions taken (e.g. 'Downgraded title from Senior to standard.').",
    )
    user_actions: list[str] = Field(
        default_factory=list,
        description="Actions the user should take to resolve issues (e.g. 'Update your profile name.', 'Paste the actual role description.').",
    )


# ─── User-facing message constants ──────────────────────────────────────────

BLOCKED_JD_INVALID = (
    "The job description appears invalid or contaminated. "
    "Please paste the actual role description, not an error message or job-board metadata."
)

BLOCKED_RESUME_CONTAMINATED = (
    "Resume generation was blocked because content from the job description "
    "reached the resume output. Please paste only the role description."
)

WARNING_SENIORITY_ADJUSTED = (
    "JD seniority exceeds candidate profile. "
    "Title was adjusted to avoid unsupported seniority."
)

WARNING_JD_WEAK = (
    "⚠️ This job description is vague. Results may be less targeted."
)

WARNING_FALLBACK_USED = (
    "AI resume generation was temporarily unavailable. "
    "A rule-based fallback was used instead. Review the output carefully "
    "and consider regenerating if the AI service is available."
)

USER_ACTION_EDIT_PROFILE = "Update your master profile to include the skills and experience targeted by this role."
USER_ACTION_EDIT_JD = "Paste a more detailed job description for better results."
USER_ACTION_REVIEW_TITLE = "Review the target title in the resume editor to ensure it matches your actual seniority."
