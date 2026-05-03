from __future__ import annotations

import re

from fastapi import Header, HTTPException


_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_DEFAULT_LOCAL_USER_ID = "anonymous-local"


def get_current_user_id(
    x_client_user_id: str | None = Header(default=None, alias="X-Client-User-Id"),
) -> str:
    """
    MVP user scoping dependency.

    The frontend sends a stable anonymous client id.
    Later this function can be replaced with JWT/OAuth auth without changing endpoints.
    """
    user_id = (x_client_user_id or _DEFAULT_LOCAL_USER_ID).strip()

    if not user_id:
        return _DEFAULT_LOCAL_USER_ID

    if not _SAFE_USER_ID_RE.match(user_id):
        raise HTTPException(status_code=400, detail="Invalid client user id")

    return user_id
