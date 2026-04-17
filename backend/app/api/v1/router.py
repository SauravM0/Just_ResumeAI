"""
API v1 router — aggregates all endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import health, jd, resume, cover_letter

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(jd.router)
api_router.include_router(resume.router)
api_router.include_router(cover_letter.router)
