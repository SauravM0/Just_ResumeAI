
import asyncio
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.schemas.profile import MasterProfile, ContactInfo
from app.schemas.pipeline import PipelineOptimizedGenerateRequest
import json
import logging

logging.basicConfig(level=logging.DEBUG)

async def main():
    profile = MasterProfile(
        id="123e4567-e89b-12d3-a456-426614174000",
        contact=ContactInfo(full_name="John Doe", email="john@example.com")
    )
    request_data = {
        "profile": profile.model_dump(),
        "raw_jd_text": "Software Engineer with 10 years of experience in Python and FastAPI. " * 5,
        "target_pages": 1,
        "allow_two_pages_for_senior": True,
        "generate_pdf": True,
        "ats_optimization_mode": "aggressive"
    }

    # Mock get_current_user
    app.dependency_overrides = {}
    from app.dependencies.auth import get_current_user
    from pydantic import BaseModel
    class MockUser(BaseModel):
        user_id: str = "123e4567-e89b-12d3-a456-426614174000"
    app.dependency_overrides[get_current_user] = lambda: MockUser()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/pipeline/generate/start", json=request_data)
        print("Status code:", response.status_code)
        print("Response body:", response.text)

asyncio.run(main())

