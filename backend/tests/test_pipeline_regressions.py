from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.ai.gemini_client import GeminiClientError
from app.ai.jd_fallback import analyze_jd_without_ai
from app.ai.resume_fallback import generate_recommendation_without_ai
from app.config import get_settings
from app.main import app
from app.schemas.jd import JDKeyword, ParsedJD, SeniorityLevel
from app.schemas.profile import ContactInfo, Education, MasterProfile, Project, Skill, WorkExperience
from app.schemas.resume import BulletStatus
from app.services.pdf_compile_service import PDFCompileError, compile_pdf
from app.services.latex_render_service import render_latex
from app.services.session_service import create_session, get_session, save_session
from app.services.eligibility_service import check_eligibility


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def isolated_backend_state(tmp_path: Path):
    settings = get_settings()
    original_db_path = settings.SESSION_DB_PATH
    original_output_dir = settings.LATEX_OUTPUT_DIR

    settings.SESSION_DB_PATH = str(tmp_path / "sessions.sqlite3")
    settings.LATEX_OUTPUT_DIR = str(tmp_path / "output")

    yield

    settings.SESSION_DB_PATH = original_db_path
    settings.LATEX_OUTPUT_DIR = original_output_dir


def _sample_profile() -> MasterProfile:
    return MasterProfile(
        id="profile-1",
        contact=ContactInfo(
            full_name="Alex Example",
            email="alex@example.com",
            phone="555-0101",
            linkedin_url="https://linkedin.com/in/alex",
        ),
        summary="Backend engineer building APIs and automation workflows.",
        work_experience=[
            WorkExperience(
                id="exp-1",
                company="Acme",
                title="Backend Engineer",
                start_date="2022-01",
                end_date="2024-01",
                description="Built Python APIs and SQL-backed services.",
                bullets=[
                    "Built Python APIs for internal automation workflows.",
                    "Improved SQL query performance for reporting systems.",
                ],
                tags=["backend", "python", "api"],
            ),
            WorkExperience(
                id="exp-2",
                company="LegacyCo",
                title="Support Specialist",
                start_date="2020-01",
                end_date="2021-12",
                description="Handled support requests and documentation.",
                bullets=["Resolved support tickets and documented recurring issues."],
                tags=["support"],
            ),
        ],
        education=[
            Education(id="edu-1", institution="State University", degree="BS", field_of_study="Computer Science")
        ],
        skills=[
            Skill(name="Python", category="Languages"),
            Skill(name="FastAPI", category="Frameworks"),
            Skill(name="SQL", category="Databases"),
        ],
        projects=[
            Project(
                id="proj-1",
                name="Resume Parser",
                description="FastAPI service for parsing resumes and extracting skills.",
                technologies=["Python", "FastAPI"],
                bullets=["Developed a parser service with Python and FastAPI."],
            )
        ],
        certifications=[],
    )


def _sample_parsed_jd() -> ParsedJD:
    return ParsedJD(
        job_title="Backend Engineer",
        seniority=SeniorityLevel.MID,
        required_skills=["Python", "FastAPI", "SQL"],
        preferred_skills=["AWS"],
        responsibilities=["Build backend APIs", "Improve database-backed services"],
        keywords=[
            JDKeyword(keyword="Python", importance="critical"),
            JDKeyword(keyword="FastAPI", importance="high"),
            JDKeyword(keyword="SQL", importance="critical"),
            JDKeyword(keyword="backend engineer", importance="high"),
        ],
    )


def _create_session_with_jd() -> str:
    session = create_session()
    session.parsed_jd = _sample_parsed_jd()
    save_session(session)
    return session.session_id


def test_resume_recommend_fallback_returns_200(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    session_id = _create_session_with_jd()

    async def fail_generate_recommendation(*args, **kwargs):
        raise GeminiClientError("forced failure")

    monkeypatch.setattr(
        "app.api.v1.endpoints.resume.generate_recommendation",
        fail_generate_recommendation,
    )

    response = client.post(
        "/api/v1/resume/recommend",
        json={
            "session_id": session_id,
            "profile": _sample_profile().model_dump(mode="json"),
            "rejected_item_ids": ["exp-2"],
        },
    )

    assert response.status_code == 200
    payload = response.json()["recommendation"]
    assert payload["session_id"] == session_id
    assert "deterministic fallback ranking" in payload["warnings"][0]
    assert all(exp["source_id"] != "exp-2" for exp in payload["experience"])


def test_resume_regenerate_fallback_returns_200_and_preserves_locked_bullet(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    profile = _sample_profile()
    session_id = _create_session_with_jd()

    session = get_session(session_id)
    assert session is not None
    session.recommendation = generate_recommendation_without_ai(
        profile=profile,
        parsed_jd=session.parsed_jd,
        session_id=session_id,
    )
    locked_bullet_id = session.recommendation.experience[0].bullets[0].id
    session.recommendation.experience[0].bullets[0].text = "LOCKED TEXT"
    session.recommendation.experience[0].bullets[0].status = BulletStatus.LOCKED
    save_session(session)

    async def fail_generate_recommendation(*args, **kwargs):
        raise GeminiClientError("forced failure")

    monkeypatch.setattr(
        "app.api.v1.endpoints.resume.generate_recommendation",
        fail_generate_recommendation,
    )

    response = client.post(
        "/api/v1/resume/regenerate",
        json={
            "session_id": session_id,
            "profile": profile.model_dump(mode="json"),
            "locked_bullet_ids": [locked_bullet_id],
            "rejected_item_ids": ["exp-2"],
        },
    )

    assert response.status_code == 200
    payload = response.json()["recommendation"]
    locked_bullets = [
        bullet
        for exp in payload["experience"]
        for bullet in exp["bullets"]
        if bullet["id"] == locked_bullet_id
    ]
    assert locked_bullets
    assert locked_bullets[0]["text"] == "LOCKED TEXT"
    assert locked_bullets[0]["status"] == "locked"
    assert all(exp["source_id"] != "exp-2" for exp in payload["experience"])


def test_render_pdf_requires_session_latex_and_ignores_client_payload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    session_id = _create_session_with_jd()

    missing_response = client.post(
        "/api/v1/resume/render-pdf",
        json={"session_id": session_id, "latex_source": "\\documentclass{article}"},
    )
    assert missing_response.status_code == 400
    assert "Call /render-latex first" in missing_response.json()["detail"]

    session = get_session(session_id)
    assert session is not None
    session.latex_source = "SERVER_OWNED_LATEX"
    save_session(session)

    pdf_path = tmp_path / "output" / "resume_test.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(b"%PDF-1.4 test")

    compile_mock = AsyncMock(return_value=(str(pdf_path), ["warn"]))
    monkeypatch.setattr("app.api.v1.endpoints.resume.compile_pdf", compile_mock)

    response = client.post(
        "/api/v1/resume/render-pdf",
        json={"session_id": session_id, "latex_source": "CLIENT_TAMPERED_LATEX"},
    )

    assert response.status_code == 200
    assert response.json()["compile_success"] is True
    assert compile_mock.await_args.kwargs["latex_source"] == "SERVER_OWNED_LATEX"


@pytest.mark.parametrize(
    "unsafe_latex",
    [
        r"\\documentclass{article}\\begin{document}\\input{/etc/passwd}\\end{document}",
        r"\\documentclass{article}\\begin{document}\\input{somefile}\\end{document}",
        r"\\documentclass{article}\\begin{document}\\write18{touch hacked}\\end{document}",
    ],
)
def test_compile_service_rejects_unsafe_latex(unsafe_latex: str):
    with pytest.raises(PDFCompileError, match="Unsafe LaTeX detected"):
        asyncio.run(compile_pdf(unsafe_latex, "unsafe-session"))


def test_rendered_template_uses_no_input_and_compiles_via_local_service(
    monkeypatch: pytest.MonkeyPatch,
):
    recommendation = generate_recommendation_without_ai(
        profile=_sample_profile(),
        parsed_jd=_sample_parsed_jd(),
        session_id="rendered-template-session",
    )
    latex_source = render_latex(recommendation)

    assert r"\input" not in latex_source
    assert r"\pdfgentounicode=1" in latex_source

    monkeypatch.setattr("app.services.pdf_compile_service.shutil.which", lambda cmd: "/usr/bin/pdflatex")

    async def fake_create_subprocess_exec(*args, cwd: str, **kwargs):
        tmpdir = Path(cwd)
        (tmpdir / "main.pdf").write_bytes(b"%PDF-1.4 rendered-template")
        (tmpdir / "main.log").write_text("", encoding="utf-8")

        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return b"", b""

        return FakeProcess()

    monkeypatch.setattr(
        "app.services.pdf_compile_service.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    pdf_path, warnings = asyncio.run(compile_pdf(latex_source, "rendered-template-session"))

    assert pdf_path.endswith(".pdf")
    assert Path(pdf_path).exists()
    assert warnings == []


def test_jd_fallback_marks_preferred_section_items_as_non_required():
    parsed = analyze_jd_without_ai(
        "Backend Engineer\n"
        "Acme\n"
        "Remote\n"
        "Requirements:\n"
        "- Python experience\n"
        "Preferred Qualifications:\n"
        "- Kubernetes experience\n"
    )

    requirement_map = {req.text: req for req in parsed.requirements}

    assert requirement_map["Python experience"].is_required is True
    assert requirement_map["Kubernetes experience"].is_required is False


def test_jd_fallback_extracts_full_multi_word_city():
    parsed = analyze_jd_without_ai(
        "Data Analyst\n"
        "Bright Corp\n"
        "New York, NY\n"
        "Requirements:\n"
        "- SQL experience\n"
    )

    assert parsed.location == "New York, NY"


def test_jd_fallback_classifies_communication_as_soft_skill():
    parsed = analyze_jd_without_ai(
        "Business Analyst\n"
        "Bright Corp\n"
        "Austin, TX\n"
        "Requirements:\n"
        "- Must have communication skills\n"
    )

    requirement = next(req for req in parsed.requirements if req.text == "Must have communication skills")
    assert requirement.category == "soft_skill"


def test_jd_fallback_item_level_required_overrides_preferred_section():
    parsed = analyze_jd_without_ai(
        "Product Manager\n"
        "Acme\n"
        "San Francisco, CA\n"
        "Preferred Qualifications:\n"
        "- Required: strong written communication\n"
    )

    requirement = next(req for req in parsed.requirements if req.text == "Required: strong written communication")
    assert requirement.is_required is True
    assert requirement.category == "soft_skill"


def test_happy_path_smoke_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    async def fake_analyze_jd(raw_text: str) -> ParsedJD:
        return _sample_parsed_jd()

    async def fake_generate_recommendation(*args, **kwargs):
        return generate_recommendation_without_ai(
            profile=kwargs["profile"],
            parsed_jd=kwargs["parsed_jd"],
            session_id=kwargs["session_id"],
            emphasis=kwargs.get("emphasis"),
            rejected_ids=kwargs.get("rejected_ids"),
            locked_bullets=kwargs.get("locked_bullets"),
        )

    async def fake_compile_pdf(*, latex_source: str, session_id: str):
        pdf_path = tmp_path / "output" / f"resume_{session_id}.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4 happy-path")
        assert latex_source
        return str(pdf_path), []

    monkeypatch.setattr("app.api.v1.endpoints.jd.analyze_jd", fake_analyze_jd)
    monkeypatch.setattr("app.api.v1.endpoints.resume.generate_recommendation", fake_generate_recommendation)
    monkeypatch.setattr("app.api.v1.endpoints.resume.compile_pdf", fake_compile_pdf)

    analyze_response = client.post(
        "/api/v1/jd/analyze",
        json={"raw_jd_text": "Backend Engineer\nAcme\nRemote\nRequirements:\n- Python\n- FastAPI\n- SQL\nResponsibilities:\n- Build APIs\n- Improve services\n" * 3},
    )
    assert analyze_response.status_code == 200
    session_id = analyze_response.json()["session_id"]

    recommend_response = client.post(
        "/api/v1/resume/recommend",
        json={
            "session_id": session_id,
            "profile": _sample_profile().model_dump(mode="json"),
            "rejected_item_ids": [],
        },
    )
    assert recommend_response.status_code == 200
    recommendation = recommend_response.json()["recommendation"]

    render_latex_response = client.post(
        "/api/v1/resume/render-latex",
        json={"session_id": session_id, "recommendation": recommendation},
    )
    assert render_latex_response.status_code == 200
    assert render_latex_response.json()["latex_source"]

    render_pdf_response = client.post(
        "/api/v1/resume/render-pdf",
        json={"session_id": session_id},
    )
    assert render_pdf_response.status_code == 200
    assert render_pdf_response.json()["compile_success"] is True


def test_pipeline_generate_happy_path_with_mocked_ai(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_analyze_jd(raw_text: str) -> ParsedJD:
        parsed = _sample_parsed_jd()
        parsed.raw_text = raw_text
        return parsed

    async def fake_generate_recommendation(*args, **kwargs):
        return generate_recommendation_without_ai(
            profile=kwargs["profile"],
            parsed_jd=kwargs["parsed_jd"],
            session_id=kwargs["session_id"],
            emphasis=kwargs.get("emphasis"),
        )

    monkeypatch.setattr("app.api.v1.endpoints.pipeline.analyze_jd", fake_analyze_jd)
    monkeypatch.setattr("app.api.v1.endpoints.pipeline.generate_recommendation", fake_generate_recommendation)

    response = client.post(
        "/api/v1/pipeline/generate",
        json={
            "profile": _sample_profile().model_dump(mode="json"),
            "raw_jd_text": "Backend Engineer\nAcme\nRemote\nRequirements:\n- Python\n- FastAPI\n- SQL\nResponsibilities:\n- Build APIs\n" * 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["recommendation"]["session_id"] == payload["session_id"]
    assert payload["ats_score"]["overall_score"] >= 0
    assert "\\documentclass" in payload["latex_source"]
    assert any(step["name"] == "render_latex" and step["status"] == "success" for step in payload["steps"])


def test_pipeline_generate_fallback_when_gemini_recommendation_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_analyze_jd(raw_text: str) -> ParsedJD:
        parsed = _sample_parsed_jd()
        parsed.raw_text = raw_text
        return parsed

    async def fail_generate_recommendation(*args, **kwargs):
        raise GeminiClientError("forced recommendation failure")

    monkeypatch.setattr("app.api.v1.endpoints.pipeline.analyze_jd", fake_analyze_jd)
    monkeypatch.setattr("app.api.v1.endpoints.pipeline.generate_recommendation", fail_generate_recommendation)

    response = client.post(
        "/api/v1/pipeline/generate",
        json={
            "profile": _sample_profile().model_dump(mode="json"),
            "raw_jd_text": "Backend Engineer\nAcme\nRemote\nRequirements:\n- Python\n- FastAPI\n- SQL\nResponsibilities:\n- Build APIs\n" * 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "deterministic fallback ranking" in payload["recommendation"]["warnings"][0]
    assert any("deterministic fallback used" in warning for warning in payload["warnings"])


def test_eligibility_hard_mismatch_for_cs_2026_against_2024_2025_apprentice_jd():
    profile = _sample_profile()
    profile.education[0].field_of_study = "Computer Science"
    profile.education[0].end_date = "2026-05"

    parsed = ParsedJD(
        job_title="Graduate Apprentice Trainee",
        raw_text=(
            "Graduate Apprentice Trainee requires Mechanical/Automobile/Electrical/"
            "Electronics/Civil engineering branches. Eligible batches: 2024/2025 only."
        ),
    )

    result = check_eligibility(profile, parsed)

    assert result.status == "hard_mismatch"
    assert any("Branch mismatch" in issue for issue in result.blocking_issues)
    assert any("Graduating batch mismatch" in issue for issue in result.blocking_issues)


def test_pipeline_render_latex_succeeds_after_pipeline(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_analyze_jd(raw_text: str) -> ParsedJD:
        parsed = _sample_parsed_jd()
        parsed.raw_text = raw_text
        return parsed

    async def fake_generate_recommendation(*args, **kwargs):
        return generate_recommendation_without_ai(
            profile=kwargs["profile"],
            parsed_jd=kwargs["parsed_jd"],
            session_id=kwargs["session_id"],
        )

    monkeypatch.setattr("app.api.v1.endpoints.pipeline.analyze_jd", fake_analyze_jd)
    monkeypatch.setattr("app.api.v1.endpoints.pipeline.generate_recommendation", fake_generate_recommendation)

    pipeline_response = client.post(
        "/api/v1/pipeline/generate",
        json={
            "profile": _sample_profile().model_dump(mode="json"),
            "raw_jd_text": "Backend Engineer\nAcme\nRemote\nRequirements:\n- Python\n- FastAPI\n- SQL\nResponsibilities:\n- Build APIs\n" * 3,
        },
    )
    assert pipeline_response.status_code == 200
    payload = pipeline_response.json()

    render_response = client.post(
        "/api/v1/resume/render-latex",
        json={"session_id": payload["session_id"], "recommendation": payload["recommendation"]},
    )

    assert render_response.status_code == 200
    assert render_response.json()["latex_source"]


def test_pipeline_pdf_failure_does_not_destroy_response(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_analyze_jd(raw_text: str) -> ParsedJD:
        parsed = _sample_parsed_jd()
        parsed.raw_text = raw_text
        return parsed

    async def fake_generate_recommendation(*args, **kwargs):
        return generate_recommendation_without_ai(
            profile=kwargs["profile"],
            parsed_jd=kwargs["parsed_jd"],
            session_id=kwargs["session_id"],
        )

    async def fail_compile_pdf(*, latex_source: str, session_id: str):
        raise PDFCompileError("pdflatex failed", ["forced pdf failure"])

    monkeypatch.setattr("app.api.v1.endpoints.pipeline.analyze_jd", fake_analyze_jd)
    monkeypatch.setattr("app.api.v1.endpoints.pipeline.generate_recommendation", fake_generate_recommendation)
    monkeypatch.setattr("app.api.v1.endpoints.pipeline.compile_pdf", fail_compile_pdf)

    response = client.post(
        "/api/v1/pipeline/generate",
        json={
            "profile": _sample_profile().model_dump(mode="json"),
            "raw_jd_text": "Backend Engineer\nAcme\nRemote\nRequirements:\n- Python\n- FastAPI\n- SQL\nResponsibilities:\n- Build APIs\n" * 3,
            "generate_pdf": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["latex_source"]
    assert payload["pdf"]["compile_success"] is False
    assert "forced pdf failure" in payload["pdf"]["compile_errors"]
    assert any("PDF compile failed" in warning for warning in payload["warnings"])


def test_fallback_mode_does_not_introduce_fake_metrics():
    profile = _sample_profile()
    for exp in profile.work_experience:
        exp.bullets = ["Built Python APIs for internal automation workflows."]
        exp.description = "Built Python APIs."
    for project in profile.projects:
        project.bullets = ["Developed a parser service with Python and FastAPI."]

    recommendation = generate_recommendation_without_ai(
        profile=profile,
        parsed_jd=_sample_parsed_jd(),
        session_id="no-fake-metrics",
    )
    generated_text = " ".join(
        [recommendation.summary or ""]
        + [bullet["text"] if isinstance(bullet, dict) else bullet.text for exp in recommendation.experience for bullet in exp.bullets]
        + [bullet.text for project in recommendation.projects for bullet in project.bullets]
    )

    assert not re.search(r"\b\d+%|\$\d+|\b\d+x\b", generated_text, re.IGNORECASE)
