"""Profile embedding service for RAG retrieval."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings
from app.schemas.profile import MasterProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProfileChunk:
    source_id: str
    chunk_type: str
    text: str
    metadata: dict[str, Any]


def chunk_profile(profile: MasterProfile) -> list[ProfileChunk]:
    """Split a MasterProfile into compact semantic chunks for embedding."""
    chunks: list[ProfileChunk] = []

    for index, exp in enumerate(profile.work_experience):
        text = _clean_join(
            [
                f"Work Experience at {exp.company} as {exp.title}.",
                exp.description or "",
                f"Key accomplishments: {' '.join(exp.bullets[:5])}." if exp.bullets else "",
                f"Technologies: {' '.join(exp.tags)}." if exp.tags else "",
            ]
        )
        if text:
            chunks.append(ProfileChunk(
                source_id=exp.id or f"work:{index}",
                chunk_type="experience",
                text=text,
                metadata={
                    "type": "experience",
                    "source_id": exp.id or f"work:{index}",
                    "company": exp.company,
                    "title": exp.title,
                    "start_date": exp.start_date,
                    "end_date": exp.end_date,
                    "is_current": exp.is_current,
                    "recency_weight": _recency_weight(exp.end_date, exp.start_date, is_current=exp.is_current),
                    "needs_rewrite": exp.needs_rewrite,
                    "tags": exp.tags,
                },
            ))

    for index, project in enumerate(profile.projects):
        text = _clean_join(
            [
                f"Project: {project.name}.",
                project.description or "",
                f"Technologies used: {' '.join(project.technologies)}." if project.technologies else "",
                f"Key work: {' '.join(project.bullets[:4])}." if project.bullets else "",
            ]
        )
        if text:
            chunks.append(ProfileChunk(
                source_id=project.id or f"project:{index}",
                chunk_type="project",
                text=text,
                metadata={
                    "type": "project",
                    "source_id": project.id or f"project:{index}",
                    "name": project.name,
                    "technologies": project.technologies,
                    "start_date": project.start_date,
                    "end_date": project.end_date,
                    "recency_weight": _recency_weight(project.end_date, project.start_date, default=0.9),
                    "needs_rewrite": project.needs_rewrite,
                },
            ))

    if profile.skills:
        skill_groups: dict[str, list[str]] = {}
        for skill in profile.skills:
            category = skill.category or "uncategorized"
            label = skill.name if skill.level is None else f"{skill.name} ({skill.level.value})"
            skill_groups.setdefault(category, []).append(label)
        skill_names = [skill.name for skill in profile.skills]
        chunks.append(ProfileChunk(
            source_id="skills",
            chunk_type="skills",
            text=_clean_join([
                f"Technical skills: {' '.join(skill_names)}.",
                "Categorised: " + "; ".join(f"{category}: {', '.join(values)}" for category, values in skill_groups.items()),
            ]),
            metadata={
                "type": "skills",
                "source_id": "skills",
                "recency_weight": 1.0,
                "item_count": len(profile.skills),
                "categories": list(skill_groups),
            },
        ))

    for index, edu in enumerate(profile.education):
        text = _clean_join(
            [
                f"Education: {edu.degree} in {edu.field_of_study or 'not specified'} from {edu.institution}.",
                f"GPA: {edu.gpa or 'not specified'}.",
                f"Honors: {edu.honors}." if edu.honors else "",
                f"Relevant coursework: {' '.join(edu.relevant_coursework[:8])}." if edu.relevant_coursework else "",
            ]
        )
        if text:
            chunks.append(ProfileChunk(
                source_id=edu.id or f"education:{index}",
                chunk_type="education",
                text=text,
                metadata={
                    "type": "education",
                    "source_id": edu.id or f"education:{index}",
                    "institution": edu.institution,
                    "degree": edu.degree,
                    "recency_weight": _recency_weight(edu.end_date, edu.start_date, default=0.7),
                },
            ))

    if profile.certifications:
        chunks.append(ProfileChunk(
            source_id="certifications",
            chunk_type="certifications",
            text="Certifications: " + "; ".join(
                f"{cert.name} from {cert.issuing_org or 'unknown'}"
                for cert in profile.certifications
            ),
            metadata={
                "type": "certifications",
                "source_id": "certifications",
                "recency_weight": 0.8,
                "item_count": len(profile.certifications),
                "source_ids": [cert.id for cert in profile.certifications],
            },
        ))

    if profile.awards:
        chunks.append(ProfileChunk(
            source_id="achievements",
            chunk_type="achievements",
            text="Achievements and awards: " + "; ".join(
                f"{award.title}: {award.description or ''}".strip(": ")
                for award in profile.awards
            ),
            metadata={
                "type": "achievements",
                "source_id": "achievements",
                "recency_weight": 0.9,
                "item_count": len(profile.awards),
                "source_ids": [award.id for award in profile.awards],
            },
        ))

    return chunks


async def embed_text(text: str) -> list[float]:
    """Embed profile chunk text with Gemini for document retrieval."""
    return await _embed_content(text, task_type="RETRIEVAL_DOCUMENT")


async def embed_query(text: str) -> list[float]:
    """Embed a query or JD requirement for similarity search."""
    return await _embed_content(text, task_type="RETRIEVAL_QUERY")


async def embed_and_store_profile(
    user_id: str,
    profile: MasterProfile,
    supabase_service,
) -> int:
    """
    Chunk, embed, and store a full profile refresh.

    Failures are intentionally non-fatal so profile saves never break when RAG
    infrastructure or Gemini embeddings are unavailable.
    """
    try:
        settings = get_settings()
        if not settings.ENABLE_RAG_EMBEDDINGS:
            logger.info("embed_and_store_profile: disabled user=%s", user_id)
            return 0

        chunks = chunk_profile(profile)
        if not chunks:
            logger.warning("embed_and_store_profile: no chunks generated for user %s", user_id)
            return 0

        rows: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            if index > 0 and index % 5 == 0:
                await asyncio.sleep(0.1)
            try:
                embedding = await embed_text(chunk.text)
            except Exception as exc:
                logger.error("Failed to embed chunk source_id=%s error=%s", chunk.source_id, exc)
                continue
            rows.append({
                "user_id": user_id,
                "profile_id": profile.id,
                "source_id": chunk.source_id,
                "chunk_type": chunk.chunk_type,
                "chunk_text": chunk.text,
                "embedding": embedding,
                "metadata": chunk.metadata,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

        if not rows:
            logger.warning("embed_and_store_profile: no embeddings produced for user %s", user_id)
            return 0

        count = await asyncio.to_thread(supabase_service.replace_profile_embeddings, user_id, rows)
        logger.info("embed_and_store_profile: stored %d chunks for user %s", count, user_id)
        return count
    except Exception as exc:
        logger.error("embed_and_store_profile.failed user=%s error=%s", user_id, exc)
        return 0


async def _embed_content(text: str, *, task_type: str) -> list[float]:
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is required for embeddings")
    return await asyncio.to_thread(_embed_content_sync, text, task_type, settings.GEMINI_API_KEY, settings.EMBEDDING_MODEL)


def _embed_content_sync(text: str, task_type: str, api_key: str, model: str) -> list[float]:
    client = genai.Client(api_key=api_key)
    response = client.models.embed_content(
        model=model,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    embeddings = response.embeddings or []
    if not embeddings or embeddings[0].values is None:
        raise RuntimeError("Gemini returned no embedding values")
    values = [float(value) for value in embeddings[0].values]
    expected_dims = get_settings().EMBEDDING_DIMS
    if len(values) != expected_dims:
        raise RuntimeError(f"Expected {expected_dims} embedding dimensions, got {len(values)}")
    return values


def _recency_weight(
    primary_date: str | None,
    fallback_date: str | None = None,
    *,
    is_current: bool = False,
    default: float = 0.9,
) -> float:
    if is_current:
        return 1.15
    parsed = _parse_year(primary_date) or _parse_year(fallback_date)
    if parsed is None:
        return default
    age = date.today().year - parsed
    if age <= 2:
        return 1.10
    if age <= 5:
        return 1.0
    if age <= 10:
        return 0.85
    return 0.70


def _parse_year(value: str | None) -> int | None:
    match = re.search(r"(?:19|20)\d{2}", value or "")
    return int(match.group(0)) if match else None


def _clean_join(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(part.strip() for part in parts if part and part.strip())).strip()
