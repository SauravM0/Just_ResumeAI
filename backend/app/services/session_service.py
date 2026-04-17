"""
Session service — ephemeral in-memory session store.

Each JD analysis creates a session that tracks the pipeline state.
Sessions are NOT persisted to disk (no DB). They expire after SESSION_TTL_MINUTES.

Assumption: single-server deployment for MVP. For horizontal scaling,
replace with Redis or similar.
"""

from __future__ import annotations

import uuid
import time
import logging
from typing import Optional

from app.config import get_settings
from app.schemas.jd import ParsedJD
from app.schemas.resume import ResumeRecommendation

logger = logging.getLogger(__name__)


class Session:
    """A single pipeline session tied to one JD analysis."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self.parsed_jd: Optional[ParsedJD] = None
        self.recommendation: Optional[ResumeRecommendation] = None
        self.latex_source: Optional[str] = None
        self.rejected_ids: list[str] = []

    def is_expired(self) -> bool:
        settings = get_settings()
        return (time.time() - self.created_at) > (settings.SESSION_TTL_MINUTES * 60)


# ─── In-memory store ────────────────────────────────────────────────────────

_sessions: dict[str, Session] = {}


def create_session() -> Session:
    """Create a new session and return it."""
    session_id = uuid.uuid4().hex
    session = Session(session_id)
    _sessions[session_id] = session
    _cleanup_expired()
    logger.info(f"Created session {session_id}")
    return session


def get_session(session_id: str) -> Optional[Session]:
    """Get a session by ID, or None if not found / expired."""
    session = _sessions.get(session_id)
    if session is None:
        return None
    if session.is_expired():
        _sessions.pop(session_id, None)
        return None
    return session


def _cleanup_expired():
    """Remove expired sessions (simple GC on each create)."""
    expired = [sid for sid, s in _sessions.items() if s.is_expired()]
    for sid in expired:
        _sessions.pop(sid, None)
    if expired:
        logger.info(f"Cleaned up {len(expired)} expired sessions")
