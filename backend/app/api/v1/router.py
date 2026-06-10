"""
API v1 router — aggregates all endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import cover_letter, generations, health, history, jd, metrics, pipeline, profile, resume, resume_fast, settings

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(profile.router)
api_router.include_router(jd.router)
api_router.include_router(metrics.router)
api_router.include_router(resume.router)
api_router.include_router(resume_fast.router)
api_router.include_router(cover_letter.router)
api_router.include_router(pipeline.router)
api_router.include_router(generations.router)
api_router.include_router(history.router)
api_router.include_router(settings.router)
