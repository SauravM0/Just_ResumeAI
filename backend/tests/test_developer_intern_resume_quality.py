from __future__ import annotations

from app.ai.resume_fallback import generate_recommendation_without_ai
from app.schemas.jd import JDKeyword, JDRequirement, ParsedJD, SeniorityLevel
from app.schemas.profile import (
    Award,
    Certification,
    ContactInfo,
    DegreeType,
    Education,
    MasterProfile,
    Project,
    Skill,
    WorkExperience,
)


def test_developer_intern_resume_preserves_fresher_strengths() -> None:
    profile = _saurav_profile()
    parsed_jd = _developer_intern_sharepoint_jd()

    rec = generate_recommendation_without_ai(
        profile=profile,
        parsed_jd=parsed_jd,
        session_id="saurav-dev-intern",
        target_pages=1,
    )

    text = _resume_text(rec)
    skills_by_category = {group.category: group.skills for group in rec.skills}
    all_skills = [skill.casefold() for group in rec.skills for skill in group.skills]

    assert "3rd Prize Hackathon" in text
    assert "50+ students mentored" in text
    assert "Saviynt" in text
    assert "OPSWAT" in text
    assert not (rec.summary or "").casefold().startswith("possessing")
    assert text.count("demonstrating strong programming aptitude") <= 1
    assert len(all_skills) == len(set(all_skills))
    assert "CGPA" in text or "9.1" in text
    assert len(rec.projects) >= 2
    assert any(metric in text for metric in ["95%", "5.1", "13:49", "300"])

    database_skills = " ".join(skills_by_category.get("Databases & Data Modelling", [])).casefold()
    for forbidden in ["c/c++", "java", "python", "git"]:
        assert forbidden not in database_skills
    web_skills = " ".join(skills_by_category.get("Web & UI Development", [])).casefold()
    for forbidden in ["docker", "kubernetes", "microservices"]:
        assert forbidden not in web_skills

    technical_skills = " ".join(skill for group in rec.skills for skill in group.skills)
    for forbidden_phrase in ["basic technical knowledge", "analytical skills", "accountability", "collaboration"]:
        assert forbidden_phrase not in technical_skills.casefold()
    for repeated in ["FastAPI", "React", "SQL", "Vector Databases"]:
        assert technical_skills.casefold().count(repeated.casefold()) <= 1

    learning_focus = " ".join(skills_by_category.get("Learning Focus / JD Tools", []))
    assert "SharePoint Application Building" in learning_focus
    assert "Power Pages" in learning_focus
    assert "Power Automate Flow Creation" in learning_focus
    assert len((rec.summary or "").split()) >= 60
    assert all(len(project.bullets) >= 3 for project in rec.projects)


def _saurav_profile() -> MasterProfile:
    return MasterProfile(
        id="saurav-profile",
        contact=ContactInfo(
            full_name="Saurav Kumar",
            email="saurav@example.com",
            phone="+91 99999 99999",
            location="India",
            linkedin_url="https://linkedin.com/in/saurav",
            github_url="https://github.com/saurav",
        ),
        education=[
            Education(
                id="edu-1",
                institution="ABC Institute of Technology",
                degree="B.Tech",
                degree_type=DegreeType.BACHELOR,
                field_of_study="Computer Science Engineering",
                start_date="2022",
                end_date="2026",
                gpa="CGPA 9.1/10",
                honors="No arrears",
                relevant_coursework=["Object-Oriented Programming", "Database Management Systems", "Software Engineering"],
            )
        ],
        skills=[
            Skill(name="C/C++", category="Programming Languages"),
            Skill(name="Java", category="Programming Languages"),
            Skill(name="Python", category="Programming Languages"),
            Skill(name="JavaScript", category="Programming Languages"),
            Skill(name="React", category="Web"),
            Skill(name="FastAPI", category="Backend"),
            Skill(name="SQL", category="Databases"),
            Skill(name="Vector Databases", category="Databases"),
            Skill(name="Git", category="Tools"),
            Skill(name="UI/UX Design", category="Design"),
            Skill(name="Technical Documentation", category="Tools"),
        ],
        projects=[
            Project(
                id="project-ai",
                name="AI Resume Analyzer",
                description="Full-stack application for resume parsing, scoring, and recommendation workflows.",
                technologies=["React", "Python", "FastAPI", "SQL", "Vector Databases"],
                bullets=[
                    "Built resume analysis engine reaching 95% accuracy while mapping candidate skills to job requirements.",
                    "Designed recruiter-readable dashboard and documentation for scoring workflows, improving review clarity.",
                ],
            ),
            Project(
                id="project-web",
                name="Campus Event Portal",
                description="Web application for event discovery, registration, and analytics.",
                technologies=["React", "JavaScript", "SQL"],
                bullets=[
                    "Improved engagement to 5.1 pages/visit and 13:49 average session duration through UI/UX refinements.",
                    "Supported 7.1K monthly visits with reusable components, clean data modelling, and tested registration flows.",
                ],
            ),
            Project(
                id="project-stream",
                name="Real-Time Event Processor",
                description="Backend event-processing project for high-throughput data ingestion.",
                technologies=["Python", "FastAPI", "SQL"],
                bullets=[
                    "Processed 300 events/second with asynchronous FastAPI workers and structured database writes.",
                    "Documented API behavior and unit-tested ingestion paths for reliable automation workflows.",
                ],
            ),
        ],
        work_experience=[
            WorkExperience(
                id="exp-mentor",
                company="Coding Club",
                title="Technical Mentor",
                start_date="2024-01",
                end_date="2025-02",
                description="Mentored juniors on programming and project development.",
                bullets=[
                    "Mentored 50+ students in Python, JavaScript, OOP, Git, and project documentation through weekly sessions.",
                    "Led peer code reviews and helped teams prepare UI flows, database schemas, and unit testing plans.",
                ],
                tags=["leadership", "mentoring"],
            )
        ],
        certifications=[
            Certification(id="cert-sav", name="Saviynt Certified IGA Professional", issuing_org="Saviynt", issue_date="2025"),
            Certification(id="cert-ops", name="OPSWAT Introduction to Critical Infrastructure Protection", issuing_org="OPSWAT", issue_date="2025"),
            Certification(id="cert-inf", name="Infosys Springboard Software Development Program", issuing_org="Infosys", issue_date="2024"),
        ],
        awards=[
            Award(id="award-hack", title="3rd Prize Hackathon", issuer="College Innovation Cell", date="2024", description="Built a working prototype under timed constraints."),
            Award(id="award-mentor", title="50+ students mentored", issuer="Coding Club", date="2024"),
        ],
    )


def _developer_intern_sharepoint_jd() -> ParsedJD:
    raw = """
    Developer Intern role for a Graduate degree candidate with no arrears. Basic understanding of
    application development, automation, UI/UX design, OOP, data modelling, technical documentation,
    unit testing, MS Excel, MS PowerPoint, MS Word, MS Outlook. Training includes SharePoint
    application building, Power Pages, and Power Automate flow creation. Candidate should be
    willing to learn new technologies.
    """
    return ParsedJD(
        job_title="Developer Intern",
        seniority=SeniorityLevel.INTERN,
        raw_text=raw,
        required_education="Graduate degree",
        requirements=[
            JDRequirement(text="Graduate degree", is_required=True, category="education"),
            JDRequirement(text="No arrears", is_required=True, category="education"),
            JDRequirement(text="Basic understanding of application development", is_required=True, category="technical_skill"),
        ],
        responsibilities=[
            "Application development",
            "Automation",
            "UI/UX design",
            "Technical documentation",
            "Unit testing",
        ],
        required_skills=["OOP", "Data Modelling", "UI/UX Design", "Technical Documentation", "Unit Testing"],
        preferred_skills=["JavaScript", "React", "Python", "FastAPI"],
        tools_platforms=["MS Excel", "MS PowerPoint", "MS Word", "MS Outlook", "SharePoint", "Power Pages", "Power Automate"],
        programming_languages=["JavaScript", "Python"],
        databases=["SQL"],
        domain_platform_terms=["SharePoint", "Power Pages", "Power Automate"],
        keywords=[
            JDKeyword(keyword="Developer Intern", importance="critical"),
            JDKeyword(keyword="SharePoint Application Building", importance="high"),
            JDKeyword(keyword="Power Automate Flow Creation", importance="high"),
        ],
    )


def _resume_text(rec) -> str:
    parts: list[str] = [
        rec.target_title,
        rec.summary or "",
        " ".join(skill for group in rec.skills for skill in [group.category, *group.skills]),
        " ".join(f"{edu.degree} {edu.field_of_study or ''} {edu.institution} {edu.gpa or ''}" for edu in rec.education),
        " ".join(bullet.text for exp in rec.experience for bullet in exp.bullets),
        " ".join(f"{project.name} {' '.join(project.technologies)} {' '.join(bullet.text for bullet in project.bullets)}" for project in rec.projects),
        " ".join(f"{cert.name} {cert.issuing_org or ''}" for cert in rec.certifications),
        " ".join(f"{item.title} {item.description or ''}" for item in rec.achievements),
    ]
    return "\n".join(parts)
