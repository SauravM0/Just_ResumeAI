"""Compatibility helpers for saved parsed JD payloads."""

from __future__ import annotations

from typing import Any

from app.schemas.jd import JDKeyword, ParsedJD
from app.services.jd_sanitization_service import sanitize_parsed_jd


def normalize_saved_parsed_jd(
    value: Any,
    *,
    job_title: str | None = None,
    company: str | None = None,
    raw_text: str | None = None,
) -> ParsedJD:
    """Return a valid ParsedJD from current or legacy/fast saved payloads."""
    if isinstance(value, ParsedJD):
        parsed = value
    elif isinstance(value, dict):
        payload = dict(value)
        payload.setdefault("job_title", job_title or "Target Role")
        if company and not payload.get("company"):
            payload["company"] = company
        if raw_text and not payload.get("raw_text"):
            payload["raw_text"] = raw_text
        payload["keywords"] = _normalize_keywords(payload.get("keywords"))
        parsed = ParsedJD.model_validate(payload)
    else:
        parsed = ParsedJD(
            job_title=job_title or "Target Role",
            company=company,
            raw_text=raw_text or "",
        )
    return sanitize_parsed_jd(parsed)


def build_fast_parsed_jd_json(
    *,
    keywords: list[str],
    job_title: str | None = None,
    company: str | None = None,
    raw_text: str | None = None,
) -> dict[str, Any]:
    parsed = normalize_saved_parsed_jd(
        {
            "job_title": job_title or "Target Role",
            "company": company,
            "raw_text": raw_text or "",
            "keywords": keywords,
            "required_skills": keywords,
            "mode": "fast_deterministic",
        },
        job_title=job_title,
        company=company,
        raw_text=raw_text,
    )
    data = parsed.model_dump(mode="json")
    data["mode"] = "fast_deterministic"
    return data


def _normalize_keywords(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    keywords: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, JDKeyword):
            keywords.append(item.model_dump(mode="json"))
            continue
        if isinstance(item, dict):
            keyword = str(item.get("keyword") or "").strip()
            if keyword:
                keywords.append({**item, "keyword": keyword})
            continue
        keyword = str(item or "").strip()
        if keyword:
            keywords.append({"keyword": keyword, "frequency": 1, "importance": "high"})
    return keywords
