from app.schemas.jd import JDKeyword, ParsedJD
from app.services.jd_sanitization_service import sanitize_parsed_jd


def test_sanitize_parsed_jd_drops_web_navigation_terms_from_keywords():
    parsed = ParsedJD(
        job_title="Java Developer",
        keywords=[
            JDKeyword(keyword="Java", importance="critical"),
            JDKeyword(keyword="Academy", importance="high"),
            JDKeyword(keyword="Then", importance="high"),
            JDKeyword(keyword="Afterwards", importance="medium"),
            JDKeyword(keyword="Join", importance="medium"),
            JDKeyword(keyword="What", importance="medium"),
            JDKeyword(keyword="Others Competitive", importance="medium"),
            JDKeyword(keyword="How", importance="medium"),
            JDKeyword(keyword="Stage", importance="medium"),
            JDKeyword(keyword="Degree", importance="medium"),
        ],
        required_skills=["Java", "Academy", "Then", "Degree"],
        raw_text="Java Developer role requiring Java and Spring Boot experience.",
    )

    cleaned = sanitize_parsed_jd(parsed, source_text=parsed.raw_text)

    assert [keyword.keyword for keyword in cleaned.keywords] == ["Java"]
    assert cleaned.required_skills == ["Java"]
