"""
JD Cache Service — caches parsed JD results keyed by SHA-256 content hash.

Reduces redundant Gemini API calls when the same job description is submitted
multiple times (e.g., retries, shared JDs across users, re-generation).

Cache entries expire after 24 hours.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.schemas.ats_planner import ATSKeywordPlannerOutput
from app.schemas.jd import ParsedJD
from app.services.supabase_service import (
    SupabaseDatabaseError,
    SupabaseServiceConfigError,
    get_supabase_service,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_HOURS = 24


async def get_cached_jd(raw_jd: str) -> tuple[ParsedJD | None, ATSKeywordPlannerOutput | None]:
    """
    Try to get a cached parsed JD by content hash.

    Returns (parsed_jd, ats_plan) on cache hit, or (None, None) on miss/error.
    """
    jd_hash = _compute_hash(raw_jd)
    try:
        svc = get_supabase_service()
        result = svc._select_maybe_single(
            "jd_cache",
            filters={"jd_hash": jd_hash},
        )
        if result is None:
            logger.debug("jd_cache.miss hash=%s", jd_hash[:12])
            return None, None

        expires_at = result.get("expires_at")
        if expires_at:
            expires = _parse_timestamp(expires_at)
            if expires and expires < datetime.now(timezone.utc):
                logger.debug("jd_cache.expired hash=%s expires=%s", jd_hash[:12], expires_at)
                return None, None

        parsed_jd_json = result.get("parsed_jd_json")
        if not parsed_jd_json:
            return None, None

        parsed_jd = ParsedJD(**json.loads(parsed_jd_json))

        ats_plan = None
        ats_plan_json = result.get("ats_plan_json")
        if ats_plan_json:
            try:
                ats_plan = ATSKeywordPlannerOutput(**json.loads(ats_plan_json))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("jd_cache corrupt ats_plan_json hash=%s: %s", jd_hash[:12], exc)

        logger.info("jd_cache.hit hash=%s title=%s", jd_hash[:12], parsed_jd.job_title)
        return parsed_jd, ats_plan

    except (SupabaseDatabaseError, SupabaseServiceConfigError) as exc:
        logger.debug("jd_cache lookup error (non-fatal): %s", exc)
        return None, None
    except Exception as exc:
        logger.warning("jd_cache unexpected error (non-fatal): %s", exc)
        return None, None


async def cache_jd_result(
    raw_jd: str,
    parsed_jd: ParsedJD,
    ats_plan: ATSKeywordPlannerOutput | None = None,
) -> bool:
    """
    Cache a parsed JD result for 24 hours.

    Returns True on success, False on non-fatal error.
    """
    jd_hash = _compute_hash(raw_jd)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=_CACHE_TTL_HOURS)).isoformat()

    try:
        svc = get_supabase_service()
        payload = {
            "jd_hash": jd_hash,
            "parsed_jd_json": parsed_jd.model_dump_json(),
            "ats_plan_json": ats_plan.model_dump_json() if ats_plan else None,
            "expires_at": expires_at,
        }
        svc._upsert_single("jd_cache", payload, on_conflict="jd_hash")
        logger.debug("jd_cache.cached hash=%s expires=%s", jd_hash[:12], expires_at)
        return True
    except (SupabaseDatabaseError, SupabaseServiceConfigError) as exc:
        logger.debug("jd_cache write error (non-fatal): %s", exc)
        return False
    except Exception as exc:
        logger.warning("jd_cache write unexpected error (non-fatal): %s", exc)
        return False


async def clear_expired_cache_entries() -> int:
    """
    Remove expired jd_cache entries.

    Returns number of deleted rows.
    """
    try:
        svc = get_supabase_service()
        now = datetime.now(timezone.utc).isoformat()
        response = svc._client.delete(
            svc._table_url("jd_cache"),
            params={"expires_at": f"lt.{now}"},
            headers={"Prefer": "return=representation"},
        )
        response.raise_for_status()
        deleted = len(response.json()) if isinstance(response.json(), list) else 0
        if deleted:
            logger.info("jd_cache cleanup: deleted %s expired entries", deleted)
        return deleted
    except Exception as exc:
        logger.warning("jd_cache cleanup error: %s", exc)
        return 0


def _compute_hash(raw_jd: str) -> str:
    return hashlib.sha256(raw_jd.encode("utf-8")).hexdigest()


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
