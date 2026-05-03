from app.schemas.jd import JDKeyword, JDRequirement, ParsedJD, SeniorityLevel
from app.schemas.profile import ContactInfo, MasterProfile, Project, Skill, WorkExperience, Education
from app.services.ats_alignment_service import build_ats_alignment_report
from app.services.ats_keyword_planner import build_ats_keyword_plan
from app.ai.resume_fallback import generate_recommendation_without_ai
from app.ai.jd_fallback import analyze_jd_without_ai
from app.services.scoring_service import compute_ats_score


def _obdx_jd() -> ParsedJD:
    raw = """
    Designation : OBDX DEVELOPER :
    Skills:
    PL/SQL
    Java/Microservices
    UI/UX development
    DevOps
    OBDX hands on experience

    Role Description:
    Installation of OBDX
    Development of CEMLIs for OBDX
    Troubleshooting of issues
    Deployment to non-production environments
    Should have knowledge of DevOps process, GIT, Jenkins
    Should have working knowledge on UI/UX development and using Development Workbench
    Should have extensive knowledge on Java/Microservices development w.r.t OBDX and using extensibility
    Should have hands-on experience with Mobile App development for iOS/Android
    Working knowledge of UK Open Banking will be an advantage
    """

    return ParsedJD(
        job_title="OBDX Developer",
        company=None,
        location="Bangalore/Chennai/Mumbai/Pune",
        seniority=SeniorityLevel.MID,
        requirements=[
            JDRequirement(text="OBDX hands on experience", is_required=True, category="domain_platform"),
            JDRequirement(text="Installation of OBDX", is_required=True, category="responsibility"),
            JDRequirement(text="Development of CEMLIs for OBDX", is_required=True, category="responsibility"),
            JDRequirement(text="Development Workbench", is_required=True, category="tool"),
            JDRequirement(text="Mobile App development for iOS/Android", is_required=True, category="mobile"),
            JDRequirement(text="UK Open Banking", is_required=False, category="domain_platform"),
        ],
        responsibilities=[
            "Installation of OBDX",
            "Development of CEMLIs for OBDX",
            "Troubleshooting of issues",
            "Deployment to non-production environments",
        ],
        keywords=[
            JDKeyword(keyword="OBDX", importance="critical"),
            JDKeyword(keyword="PL/SQL", importance="critical"),
            JDKeyword(keyword="Java/Microservices", importance="critical"),
            JDKeyword(keyword="Jenkins", importance="high"),
            JDKeyword(keyword="Development Workbench", importance="critical"),
            JDKeyword(keyword="Mobile App development", importance="high"),
        ],
        required_skills=[
            "PL/SQL",
            "Java/Microservices",
            "UI/UX development",
            "DevOps",
            "OBDX hands on experience",
        ],
        preferred_skills=["UK Open Banking"],
        raw_text=raw,
    )


def _profile_without_obdx() -> MasterProfile:
    return MasterProfile(
        id="profile1",
        contact=ContactInfo(
            full_name="Saurav Madake",
            email="saurav@example.com",
            phone="9172027838",
            location="Pune",
        ),
        summary="Full stack developer with backend, UI and mobile app experience.",
        skills=[
            Skill(name="Java", category="Languages"),
            Skill(name="JavaScript", category="Languages"),
            Skill(name="React.js", category="Frontend"),
            Skill(name="FastAPI", category="Backend"),
            Skill(name="Docker", category="DevOps"),
            Skill(name="Git", category="DevOps"),
            Skill(name="Flutter", category="Mobile"),
            Skill(name="Android development", category="Mobile"),
            Skill(name="SQL", category="Database"),
        ],
        work_experience=[
            WorkExperience(
                id="exp1",
                company="Naukri Safar",
                title="Full Stack Developer",
                start_date="2024-04",
                end_date="2025-05",
                bullets=[
                    "Integrated REST APIs for real-time data synchronization.",
                    "Built responsive user interfaces and optimized platform performance.",
                ],
            )
        ],
        projects=[
            Project(
                id="proj1",
                name="Telematics App",
                technologies=["Flutter", "Dart", "Firebase", "Android"],
                bullets=[
                    "Built cross-platform mobile app for real-time vehicle diagnostics.",
                    "Integrated Firebase Realtime Database for cloud sync.",
                ],
            )
        ],
        education=[
            Education(
                id="edu1",
                institution="MGM University",
                degree="Bachelor of Technology",
                field_of_study="Computer Science and Engineering",
                start_date="2022-06",
                end_date="2026-06",
                gpa="8.16 / 10",
            )
        ],
    )


def test_obdx_alignment_report_tracks_resume_keywords_only():
    jd = _obdx_jd()
    profile = _profile_without_obdx()
    rec = generate_recommendation_without_ai(
        profile=profile,
        parsed_jd=jd,
        session_id="test-session",
    )
    report = build_ats_alignment_report(jd, rec)

    assert report.jd_title_detected == "OBDX Developer"
    assert "PL/SQL" in report.required_skills
    assert "Jenkins" in report.important_ats_keywords
    assert "OBDX Developer" in report.keywords_included
    assert "PL/SQL" in report.keywords_missing
    assert report.suggestions
    assert rec.target_title == "OBDX Developer"


def test_obdx_score_has_no_old_risk_fields_or_caps():
    jd = _obdx_jd()
    profile = _profile_without_obdx()
    rec = generate_recommendation_without_ai(
        profile=profile,
        parsed_jd=jd,
        session_id="test-session",
    )

    score = compute_ats_score(rec, jd)

    assert not hasattr(score, "risk_level")
    assert not hasattr(score, "questions")
    assert not any("risk" in warning.lower() for warning in score.warnings)


def test_obdx_ats_keyword_planner_prioritizes_exact_jd_terms():
    parsed = analyze_jd_without_ai(
        "Designation : OBDX DEVELOPER :\n"
        "Skills:\n"
        "PL/SQL\n"
        "Java/Microservices\n"
        "UI/UX development\n"
        "DevOps\n"
        "OBDX hands on experience\n"
        "Role Description:\n"
        "Installation of OBDX\n"
        "Development of CEMLIs for OBDX\n"
        "Troubleshooting of issues\n"
        "Deployment to non-production environments\n"
        "Should have knowledge of DevOps process, GIT, Jenkins\n"
        "Should have working knowledge on UI/UX development and using Development Workbench\n"
        "Should have extensive knowledge on Java/Microservices development w.r.t OBDX and using extensibility\n"
        "Should have hands-on experience with Mobile App development for iOS/Android\n"
        "Working knowledge of UK Open Banking will be an advantage\n"
    )

    plan = build_ats_keyword_plan(
        parsed_jd=parsed,
        profile=_profile_without_obdx(),
        emphasis=None,
        target_pages=1,
    )
    terms = {term.casefold(): term for term in plan.priority_keywords}
    skills = {term.casefold(): term for term in plan.must_include_skills}
    responsibilities = {term.casefold(): term for term in plan.must_include_responsibilities}
    payload = plan.model_dump()

    assert plan.target_resume_title == "OBDX Developer"
    for term in [
        "PL/SQL",
        "Java",
        "Microservices",
        "UI/UX development",
        "DevOps",
        "Git",
        "Jenkins",
        "CEMLI",
        "Development Workbench",
        "Extensibility",
        "Mobile App development",
        "UK Open Banking",
    ]:
        assert term.casefold() in terms or term.casefold() in skills
    for responsibility in [
        "Installation of OBDX",
        "Troubleshooting of issues",
        "Deployment to non-production environments",
    ]:
        assert responsibility.casefold() in responsibilities
    assert not any(key in payload for key in ("evidence", "truthfulness", "blockers", "unsupported"))
