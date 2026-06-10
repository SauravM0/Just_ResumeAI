from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

from fastapi import Request

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def normalize_request_id(value: str | None) -> str:
    """Return a safe request id from the client header, or generate a new UUID."""
    candidate = (value or "").strip()
    if _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return str(uuid4())


def get_request_id(request: Request | None) -> str:
    if request is None:
        return ""
    return str(getattr(request.state, "request_id", "") or "")


def set_request_user(request: Request | None, user_id: str | None) -> None:
    if request is not None and user_id:
        request.state.user_id = str(user_id)


def get_request_user(request: Request | None) -> str:
    if request is None:
        return ""
    return str(getattr(request.state, "user_id", "") or "")


def generation_id_from_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    markers = {"resume", "history", "generations", "cover-letter"}
    for index, part in enumerate(parts[:-1]):
        if part in markers:
            return parts[index + 1]
    if "pipeline" in parts and "generate" in parts:
        try:
            candidate = parts[parts.index("generate") + 1]
        except (ValueError, IndexError):
            return ""
        return "" if candidate in {"start", "optimized"} else candidate
    return ""


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    payload = {"event": event, **{key: value for key, value in fields.items() if value not in (None, "")}}
    logger.log(level, json.dumps(payload, default=str, sort_keys=True))
