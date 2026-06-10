from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import resume_fast
from app.dependencies.auth import get_current_user_id


class StubFastResumeService:
    def __init__(self) -> None:
        self.calls = 0
        self.confirm_calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        return {
            "generation_id": "fast-test-generation",
            "persisted": False,
            "resume_json": {
                "generation_id": "fast-test-generation",
                "target_title": "Backend Engineer",
                "summary": "Backend engineer focused on Python APIs.",
                "experience": [],
                "skills": [{"category": "Backend", "skills": ["Python", "FastAPI"]}],
            },
            "ats_score": 82,
            "matched_keywords": ["Python", "FastAPI"],
            "missing_keywords": ["Kubernetes"],
            "extracted_keywords": ["Python", "FastAPI", "Kubernetes"],
            "confirmed_keywords": [],
            "score_breakdown": {
                "exact_jd_keywords": 80,
                "required_skills": 75,
                "title_seniority_alignment": 90,
                "standard_sections": 85,
                "parseability": 90,
            },
            "score_explanation": ["Exact JD keyword match: 80%"],
            "improvement_suggestions": ["Add Kubernetes if supported by profile evidence."],
            "score_disclaimer": "Fast deterministic estimate for comparison, not a guaranteed ATS result.",
        }

    def confirm_keywords(self, **kwargs):
        self.confirm_calls += 1
        return {
            "generation_id": kwargs["generation_id"],
            "confirmed_keywords": [
                {"keyword": "Kubernetes", "level": "project"},
                {"keyword": "Terraform", "level": "no"},
            ],
            "usable_keywords": [
                {"keyword": "Kubernetes", "level": "project"},
            ],
        }


def test_fast_generate_returns_resume_json_and_ats_score():
    app = FastAPI()
    service = StubFastResumeService()
    app.include_router(resume_fast.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_id] = lambda: "test-user"
    app.dependency_overrides[resume_fast.get_fast_resume_service] = lambda: service

    client = TestClient(app)
    response = client.post(
        "/api/v1/resume/fast-generate",
        json={
            "save_to_database": False,
            "raw_jd_text": (
                "We need a Backend Engineer with Python, FastAPI, REST APIs, "
                "PostgreSQL, Docker, Kubernetes, and production ownership experience."
            ),
            "job_title": "Backend Engineer",
            "profile": {
                "id": "profile-1",
                "version": 1,
                "contact": {
                    "full_name": "Test User",
                    "email": "test@example.com",
                },
                "summary": "Backend engineer.",
                "work_experience": [
                    {
                        "id": "work-1",
                        "company": "Example Co",
                        "title": "Software Engineer",
                        "start_date": "2021-01",
                        "is_current": True,
                        "bullets": ["Built Python APIs with FastAPI."],
                    }
                ],
                "skills": [
                    {"name": "Python", "category": "Programming Languages"},
                    {"name": "FastAPI", "category": "Backend"},
                ],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resume_json"]["target_title"] == "Backend Engineer"
    assert body["ats_score"] == 82
    assert body["matched_keywords"] == ["Python", "FastAPI"]
    assert "pdf" not in body
    assert "docx" not in body
    assert service.calls == 1


def test_confirm_keywords_stores_temporary_fast_context():
    app = FastAPI()
    service = StubFastResumeService()
    app.include_router(resume_fast.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user_id] = lambda: "test-user"
    app.dependency_overrides[resume_fast.get_fast_resume_service] = lambda: service

    client = TestClient(app)
    response = client.post(
        "/api/v1/resume/fast-test-generation/confirm-keywords",
        json={
            "keywords": [
                {"keyword": "Kubernetes", "level": "project"},
                {"keyword": "Terraform", "level": "no"},
            ]
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generation_id"] == "fast-test-generation"
    assert body["usable_keywords"] == [{"keyword": "Kubernetes", "level": "project"}]
    assert service.confirm_calls == 1
