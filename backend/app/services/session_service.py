"""
Session service backed by SQLite for short-lived pipeline persistence.

Each JD analysis creates a session that tracks parsed JD, recommendation,
rendered LaTeX, and rejected item IDs. Sessions survive backend restarts
until SESSION_TTL_MINUTES expiry.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from app.config import get_settings
from app.schemas.jd import ParsedJD
from app.schemas.resume import ResumeRecommendation

logger = logging.getLogger(__name__)


class Session:
    """A single pipeline session tied to one JD analysis."""

    def __init__(
        self,
        session_id: str,
        created_at: float | None = None,
        parsed_jd: Optional[ParsedJD] = None,
        recommendation: Optional[ResumeRecommendation] = None,
        latex_source: Optional[str] = None,
        rejected_ids: Optional[list[str]] = None,
    ):
        self.session_id = session_id
        self.created_at = created_at if created_at is not None else time.time()
        self.parsed_jd = parsed_jd
        self.recommendation = recommendation
        self.latex_source = latex_source
        self.rejected_ids = rejected_ids or []

    def is_expired(self) -> bool:
        settings = get_settings()
        return (time.time() - self.created_at) > (settings.SESSION_TTL_MINUTES * 60)


def create_session() -> Session:
    """Create and persist a new session."""
    cleanup_expired_sessions()
    session = Session(session_id=uuid.uuid4().hex)
    save_session(session)
    logger.info("Created session %s", session.session_id)
    return session


def get_session(session_id: str) -> Optional[Session]:
    """Load a session by ID, deleting it if expired."""
    cleanup_expired_sessions()
    _ensure_db()

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT session_id, created_at, parsed_jd_json, recommendation_json, latex_source, rejected_ids_json
            FROM sessions
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()

    if row is None:
        return None

    session = _row_to_session(row)
    if session.is_expired():
        delete_session(session_id)
        return None
    return session


def save_session(session: Session) -> None:
    """Persist the current state of a session."""
    _ensure_db()

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id,
                created_at,
                parsed_jd_json,
                recommendation_json,
                latex_source,
                rejected_ids_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                created_at = excluded.created_at,
                parsed_jd_json = excluded.parsed_jd_json,
                recommendation_json = excluded.recommendation_json,
                latex_source = excluded.latex_source,
                rejected_ids_json = excluded.rejected_ids_json
            """,
            (
                session.session_id,
                session.created_at,
                session.parsed_jd.model_dump_json() if session.parsed_jd else None,
                session.recommendation.model_dump_json() if session.recommendation else None,
                session.latex_source,
                json.dumps(session.rejected_ids),
            ),
        )


def delete_session(session_id: str) -> None:
    """Delete a session from persistent storage."""
    _ensure_db()
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def cleanup_expired_sessions() -> None:
    """Delete sessions older than SESSION_TTL_MINUTES."""
    _ensure_db()
    cutoff = time.time() - (get_settings().SESSION_TTL_MINUTES * 60)
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE created_at < ?", (cutoff,))
        if cursor.rowcount:
            logger.info("Cleaned up %s expired sessions", cursor.rowcount)


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        session_id=row["session_id"],
        created_at=row["created_at"],
        parsed_jd=ParsedJD.model_validate_json(row["parsed_jd_json"]) if row["parsed_jd_json"] else None,
        recommendation=ResumeRecommendation.model_validate_json(row["recommendation_json"])
        if row["recommendation_json"]
        else None,
        latex_source=row["latex_source"],
        rejected_ids=json.loads(row["rejected_ids_json"]) if row["rejected_ids_json"] else [],
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_db() -> None:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                parsed_jd_json TEXT,
                recommendation_json TEXT,
                latex_source TEXT,
                rejected_ids_json TEXT
            )
            """
        )


def _db_path() -> Path:
    return Path(get_settings().SESSION_DB_PATH)
