from __future__ import annotations

import logging

from pydantic import BaseModel

from app.schemas.profile import MasterProfile

logger = logging.getLogger(__name__)

_WEAK_BULLET_PHRASES = (
    "basic technical knowledge",
    "analytical skills",
    "showcasing",
    "demonstrating",
    "responsible for",
    "worked on",
)


class ProfileAgentResult(BaseModel):
    profile: MasterProfile


class ProfileAgent:
    def run(self, candidate_profile: MasterProfile | dict) -> ProfileAgentResult:
        logger.info("resume_agent.profile_agent.started")
        profile = (
            candidate_profile
            if isinstance(candidate_profile, MasterProfile)
            else MasterProfile.model_validate(candidate_profile)
        )
        result = ProfileAgentResult(profile=_flag_weak_profile_bullets(profile))
        logger.info(
            "resume_agent.profile_agent.completed experiences=%s projects=%s skills=%s",
            len(result.profile.work_experience),
            len(result.profile.projects),
            len(result.profile.skills),
        )
        return result


def _flag_weak_profile_bullets(profile: MasterProfile) -> MasterProfile:
    work_experience = []
    for experience in profile.work_experience:
        corpus = " ".join(experience.bullets).casefold()
        needs_rewrite = (
            experience.needs_rewrite
            or any(phrase in corpus for phrase in _WEAK_BULLET_PHRASES)
            or any(len(bullet.strip()) < 80 for bullet in experience.bullets)
        )
        work_experience.append(experience.model_copy(update={"needs_rewrite": needs_rewrite}))

    projects = []
    for project in profile.projects:
        corpus = " ".join(project.bullets).casefold()
        needs_rewrite = (
            project.needs_rewrite
            or any(phrase in corpus for phrase in _WEAK_BULLET_PHRASES)
            or any(len(bullet.strip()) < 80 for bullet in project.bullets)
        )
        projects.append(project.model_copy(update={"needs_rewrite": needs_rewrite}))

    return profile.model_copy(
        update={
            "work_experience": work_experience,
            "projects": projects,
        }
    )


profile_agent = ProfileAgent()
