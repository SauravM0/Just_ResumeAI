"""
Health check endpoint.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Basic health check — returns 200 if the server is running."""
    return {"status": "healthy", "service": "justresume-api"}
