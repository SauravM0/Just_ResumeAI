"""RAG retrieval service for targeted profile evidence."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.schemas.jd import ParsedJD
from app.services.embedding_service import embed_query

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedEvidence:
    source_id: str
    chunk_type: str
    chunk_text: str
    similarity: float
    metadata: dict[str, Any]
    recency_weight: float = 1.0


@dataclass(frozen=True)
class RequirementEvidence:
    requirement: str
    priority: str
    top_evidence: list[RetrievedEvidence]
    is_covered: bool


async def retrieve_evidence_for_requirements(
    user_id: str,
    parsed_jd: ParsedJD,
    supabase_service,
    top_k: int = 3,
    similarity_threshold: float = 0.6,
) -> list[RequirementEvidence]:
    """Retrieve top profile chunks for each JD requirement, falling back safely."""
    try:
        chunk_count = await asyncio.to_thread(supabase_service.count_profile_embeddings, user_id)
    except Exception as exc:
        logger.warning("rag.mode=fallback reason=status_error user=%s error=%s", user_id, exc)
        return []
    if chunk_count <= 0:
        logger.info("rag.mode=fallback reason=no_embeddings user=%s", user_id)
        return []

    requirements = _requirements_for_retrieval(parsed_jd)
    if not requirements:
        logger.warning("rag.mode=fallback reason=no_requirements user=%s", user_id)
        return []

    results: list[RequirementEvidence] = []
    for requirement_text, priority in requirements:
        try:
            query_embedding = await embed_query(requirement_text)
            rows = await asyncio.to_thread(
                supabase_service.match_profile_chunks,
                user_id=user_id,
                query_embedding=query_embedding,
                match_count=top_k,
                similarity_threshold=similarity_threshold,
            )
            evidence_list = [_row_to_evidence(row) for row in rows]
            is_covered = any(item.similarity >= similarity_threshold for item in evidence_list)
            results.append(RequirementEvidence(
                requirement=requirement_text,
                priority=priority,
                top_evidence=evidence_list,
                is_covered=is_covered,
            ))
        except Exception as exc:
            logger.error("RAG retrieval failed requirement=%s error=%s", requirement_text[:80], exc)

    covered = sum(1 for item in results if item.is_covered)
    if results:
        logger.info("rag.mode=active requirements_covered=%d/%d user=%s", covered, len(results), user_id)
    else:
        logger.info("rag.mode=fallback reason=no_matches user=%s", user_id)
    return results


def _requirements_for_retrieval(parsed_jd: ParsedJD) -> list[tuple[str, str]]:
    if parsed_jd.requirements:
        return [
            (
                requirement.text,
                requirement.priority.value if hasattr(requirement.priority, "value") else str(requirement.priority),
            )
            for requirement in parsed_jd.requirements[:15]
            if requirement.text.strip()
        ]
    return [(skill, "must-have") for skill in (parsed_jd.required_skills or [])[:10] if skill.strip()]


def _row_to_evidence(row: dict[str, Any]) -> RetrievedEvidence:
    metadata = row.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return RetrievedEvidence(
        source_id=str(row.get("source_id") or ""),
        chunk_type=str(row.get("chunk_type") or ""),
        chunk_text=str(row.get("chunk_text") or ""),
        similarity=float(row.get("similarity") or 0.0),
        metadata=metadata,
        recency_weight=float(metadata.get("recency_weight") or 1.0),
    )
