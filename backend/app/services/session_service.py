"""
User-scoped session service backed by SQLite.

Sessions persist short-lived pipeline state only. The full master profile remains
client-side and is not stored server-side.
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

DEFAULT_USER_ID = "anonymous-local"


class Session:
    """A single pipeline session tied to one JD analysis and one user."""

    def __init__(
        self,
        session_id: str,
        user_id: str = DEFAULT_USER_ID,
        created_at: float | None = None,
        updated_at: float | None = None,
        expires_at: float | None = None,
        parsed_jd: Optional[ParsedJD] = None,
        recommendation: Optional[ResumeRecommendation] = None,
        latex_source: Optional[str] = None,
        pdf_filename: Optional[str] = None,
        rejected_ids: Optional[list[str]] = None,
    ):
        now = time.time()
        ttl_seconds = get_settings().SESSION_TTL_MINUTES * 60

        self.session_id = session_id
        self.user_id = user_id or DEFAULT_USER_ID
        self.created_at = created_at if created_at is not None else now
        self.updated_at = updated_at if updated_at is not None else now
        self.expires_at = expires_at if expires_at is not None else self.created_at + ttl_seconds
        self.parsed_jd = parsed_jd
        self.recommendation = recommendation
        self.latex_source = latex_source
        self.pdf_filename = pdf_filename
        self.rejected_ids = rejected_ids or []

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


def create_session(user_id: str = DEFAULT_USER_ID) -> Session:
    """Create and persist a new user-scoped session."""
    cleanup_expired_sessions()
    session = Session(session_id=uuid.uuid4().hex, user_id=user_id)
    save_session(session)
    logger.info("Created session %s for user %s", session.session_id, session.user_id)
    return session


def get_session(session_id: str, user_id: str | None = None) -> Optional[Session]:
    """Load a session by ID and optional user ID, deleting it if expired."""
    cleanup_expired_sessions()
    _ensure_db()

    if user_id:
        query = """
            SELECT session_id, user_id, created_at, updated_at, expires_at,
                   parsed_jd_json, recommendation_json, latex_source, pdf_filename,
                   rejected_ids_json
            FROM sessions
            WHERE session_id = ? AND user_id = ?
        """
        params = (session_id, user_id)
    else:
        query = """
            SELECT session_id, user_id, created_at, updated_at, expires_at,
                   parsed_jd_json, recommendation_json, latex_source, pdf_filename,
                   rejected_ids_json
            FROM sessions
            WHERE session_id = ?
        """
        params = (session_id,)

    with _connect() as conn:
        row = conn.execute(query, params).fetchone()

    if row is None:
        return None

    session = _row_to_session(row)
    if session.is_expired():
        delete_session(session_id=session_id, user_id=session.user_id)
        return None

    return session


def save_session(session: Session) -> None:
    """Persist the current state of a session."""
    _ensure_db()
    now = time.time()
    session.updated_at = now

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id,
                user_id,
                created_at,
                updated_at,
                expires_at,
                parsed_jd_json,
                recommendation_json,
                latex_source,
                pdf_filename,
                rejected_ids_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                user_id = excluded.user_id,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                expires_at = excluded.expires_at,
                parsed_jd_json = excluded.parsed_jd_json,
                recommendation_json = excluded.recommendation_json,
                latex_source = excluded.latex_source,
                pdf_filename = excluded.pdf_filename,
                rejected_ids_json = excluded.rejected_ids_json
            """,
            (
                session.session_id,
                session.user_id,
                session.created_at,
                session.updated_at,
                session.expires_at,
                session.parsed_jd.model_dump_json() if session.parsed_jd else None,
                session.recommendation.model_dump_json() if session.recommendation else None,
                session.latex_source,
                session.pdf_filename,
                json.dumps(session.rejected_ids),
            ),
        )


def delete_session(session_id: str, user_id: str | None = None) -> None:
    """Delete a session from persistent storage."""
    _ensure_db()

    with _connect() as conn:
        if user_id:
            conn.execute(
                "DELETE FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            )
        else:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


def cleanup_expired_sessions() -> None:
    """Delete expired sessions."""
    _ensure_db()
    now = time.time()

    with _connect() as conn:
        cursor = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        if cursor.rowcount:
            logger.info("Cleaned up %s expired sessions", cursor.rowcount)


def _row_to_session(row: sqlite3.Row) -> Session:
    return Session(
        session_id=row["session_id"],
        user_id=row["user_id"] or DEFAULT_USER_ID,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        expires_at=row["expires_at"],
        parsed_jd=ParsedJD.model_validate_json(row["parsed_jd_json"]) if row["parsed_jd_json"] else None,
        recommendation=ResumeRecommendation.model_validate_json(row["recommendation_json"])
        if row["recommendation_json"]
        else None,
        latex_source=row["latex_source"],
        pdf_filename=row["pdf_filename"],
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
                user_id TEXT NOT NULL DEFAULT 'anonymous-local',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                parsed_jd_json TEXT,
                recommendation_json TEXT,
                latex_source TEXT,
                pdf_filename TEXT,
                rejected_ids_json TEXT
            )
            """
        )
        _add_missing_columns(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }

    migrations = {
        "user_id": "ALTER TABLE sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT 'anonymous-local'",
        "updated_at": "ALTER TABLE sessions ADD COLUMN updated_at REAL",
        "expires_at": "ALTER TABLE sessions ADD COLUMN expires_at REAL",
        "pdf_filename": "ALTER TABLE sessions ADD COLUMN pdf_filename TEXT",
    }

    for column, statement in migrations.items():
        if column not in existing:
            conn.execute(statement)

    now = time.time()
    ttl_seconds = get_settings().SESSION_TTL_MINUTES * 60
    conn.execute("UPDATE sessions SET updated_at = created_at WHERE updated_at IS NULL")
    conn.execute("UPDATE sessions SET expires_at = created_at + ? WHERE expires_at IS NULL", (ttl_seconds,))
    conn.execute("UPDATE sessions SET user_id = ? WHERE user_id IS NULL OR user_id = ''", (DEFAULT_USER_ID,))


def _db_path() -> Path:
    return Path(get_settings().SESSION_DB_PATH)
