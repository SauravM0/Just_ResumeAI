from app.application.use_cases.parsed_jd_compat import (
    build_fast_parsed_jd_json,
    normalize_saved_parsed_jd,
)


def test_normalize_saved_parsed_jd_accepts_fast_keyword_strings():
    parsed = normalize_saved_parsed_jd(
        {"mode": "fast_deterministic", "keywords": ["Python", "FastAPI"]},
        job_title="Backend Engineer",
        company="Example Co",
        raw_text="Backend role requiring Python and FastAPI.",
    )

    assert parsed.job_title == "Backend Engineer"
    assert parsed.company == "Example Co"
    assert [keyword.keyword for keyword in parsed.keywords] == ["Python", "FastAPI"]
    assert all(keyword.importance == "high" for keyword in parsed.keywords)
    assert parsed.raw_text == "Backend role requiring Python and FastAPI."


def test_build_fast_parsed_jd_json_persists_structured_keywords():
    payload = build_fast_parsed_jd_json(
        keywords=["Python", "FastAPI"],
        job_title="Backend Engineer",
        company=None,
        raw_text="Backend role requiring Python and FastAPI.",
    )

    assert payload["job_title"] == "Backend Engineer"
    assert payload["keywords"] == [
        {"keyword": "Python", "frequency": 1, "importance": "high"},
        {"keyword": "FastAPI", "frequency": 1, "importance": "high"},
    ]
    assert payload["mode"] == "fast_deterministic"
