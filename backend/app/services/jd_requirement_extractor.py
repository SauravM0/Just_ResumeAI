from __future__ import annotations

import re
import uuid

from app.schemas.resume import JDRequirement


def _make_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _contains_any(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def extract_jd_requirements(job_description: str) -> list[JDRequirement]:
    """
    Deterministically extract normalized requirements from a JD.

    This is intentionally rule-based first so that critical requirements are not
    missed by the LLM. The LLM may later enrich wording, but this function is the
    safety baseline.
    """
    jd = job_description or ""
    requirements: list[JDRequirement] = []

    def add(
        name: str,
        category: str,
        priority: str,
        original_text: str,
        keywords: list[str],
        reason: str,
    ) -> None:
        if any(r.name.lower() == name.lower() for r in requirements):
            return
        requirements.append(
            JDRequirement(
                id=_make_id("req"),
                name=name,
                category=category,
                priority=priority,
                original_text=original_text,
                keywords=keywords,
                reason=reason,
            )
        )

    # Domain/platform critical requirements
    if _contains_any(jd, ["obdx", "oracle banking digital experience"]):
        add(
            name="OBDX hands-on experience",
            category="domain_platform",
            priority="critical",
            original_text="OBDX hands-on experience",
            keywords=["OBDX", "Oracle Banking Digital Experience"],
            reason="The role specifically requires OBDX experience.",
        )

    if _contains_any(jd, ["installation of obdx", "obdx installation"]):
        add(
            name="OBDX installation",
            category="deployment",
            priority="critical",
            original_text="Installation of OBDX",
            keywords=["OBDX installation", "installation of OBDX"],
            reason="The role explicitly requires OBDX installation.",
        )

    if _contains_any(jd, ["cemli", "cemlis"]):
        add(
            name="CEMLI development for OBDX",
            category="responsibility",
            priority="critical",
            original_text="Development of CEMLIs for OBDX",
            keywords=["CEMLI", "CEMLIs", "OBDX customization"],
            reason="The JD explicitly asks for CEMLI development.",
        )

    if _contains_any(jd, ["development workbench"]):
        add(
            name="OBDX Development Workbench",
            category="tooling",
            priority="critical",
            original_text="using Development Workbench",
            keywords=["Development Workbench", "OBDX Workbench"],
            reason="The JD requires working knowledge of Development Workbench.",
        )

    if _contains_any(jd, ["extensibility"]):
        add(
            name="OBDX extensibility",
            category="backend",
            priority="critical",
            original_text="using extensibility",
            keywords=["OBDX extensibility", "extensibility framework"],
            reason="The JD requires OBDX extensibility knowledge.",
        )

    # Core technical requirements
    if _contains_any(jd, ["pl/sql", "plsql"]):
        add(
            name="PL/SQL",
            category="database",
            priority="critical",
            original_text="PL/SQL",
            keywords=["PL/SQL", "PLSQL", "Oracle SQL"],
            reason="PL/SQL is listed as a required skill.",
        )

    if _contains_any(jd, ["java", "microservices", "java/microservices"]):
        add(
            name="Java/Microservices",
            category="backend",
            priority="critical",
            original_text="Java/Microservices",
            keywords=["Java", "Microservices", "Spring Boot", "REST APIs"],
            reason="Java/Microservices is listed as a required skill.",
        )

    if _contains_any(jd, ["ui/ux", "ui development", "ux development"]):
        add(
            name="UI/UX development",
            category="frontend",
            priority="important",
            original_text="UI/UX development",
            keywords=["UI/UX", "UI development", "UX", "responsive UI"],
            reason="UI/UX development is listed as a skill requirement.",
        )

    if _contains_any(jd, ["devops", "git", "jenkins"]):
        add(
            name="DevOps process with Git and Jenkins",
            category="devops",
            priority="important",
            original_text="DevOps process, GIT, Jenkins",
            keywords=["DevOps", "Git", "Jenkins", "CI/CD"],
            reason="The role requires DevOps process knowledge including Git and Jenkins.",
        )

    if _contains_any(jd, ["non-production", "non production", "uat", "sit", "dev environment"]):
        add(
            name="Deployment to non-production environments",
            category="deployment",
            priority="important",
            original_text="Deployment to non-production environments",
            keywords=["DEV", "UAT", "SIT", "non-production deployment"],
            reason="The JD includes non-production deployment responsibility.",
        )

    if _contains_any(jd, ["troubleshooting"]):
        add(
            name="Troubleshooting production or environment issues",
            category="responsibility",
            priority="important",
            original_text="Troubleshooting of issues",
            keywords=["troubleshooting", "debugging", "issue resolution"],
            reason="The role includes troubleshooting responsibilities.",
        )

    if _contains_any(jd, ["ios", "android", "mobile app"]):
        add(
            name="Mobile app development for iOS/Android",
            category="mobile",
            priority="important",
            original_text="Mobile App development for iOS/Android",
            keywords=["Android", "iOS", "Flutter", "Dart", "mobile app"],
            reason="Mobile app development is explicitly requested.",
        )

    if _contains_any(jd, ["uk open banking", "open banking", "psd2"]):
        add(
            name="UK Open Banking knowledge",
            category="domain_knowledge",
            priority="optional",
            original_text="UK Open Banking will be an advantage",
            keywords=["UK Open Banking", "Open Banking", "PSD2", "banking APIs"],
            reason="The JD lists UK Open Banking as an advantage.",
        )

    # Location extraction
    locations = re.findall(r"\b(Bangalore|Chennai|Mumbai|Pune|Bengaluru)\b", jd, flags=re.I)
    if locations:
        unique_locations = sorted({loc.title() for loc in locations})
        add(
            name="Location preference",
            category="location",
            priority="optional",
            original_text=", ".join(unique_locations),
            keywords=unique_locations,
            reason="The JD specifies acceptable job locations.",
        )

    return requirements
