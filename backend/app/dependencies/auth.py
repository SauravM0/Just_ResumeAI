from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import binascii
import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx

from app.config import get_settings
from app.services.supabase_service import SupabaseDatabaseError, SupabaseServiceConfigError, get_supabase_service

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None
    expires_at: datetime
    claims: dict[str, Any]


class AuthError(Exception):
    """Base class for authentication failures."""


class MissingTokenError(AuthError):
    """Raised when the Authorization bearer token is missing."""


class InvalidAuthTokenError(AuthError):
    """Raised when a token is malformed or fails verification."""


class ExpiredAuthTokenError(AuthError):
    """Raised when a token is expired."""


def verify_supabase_jwt(token: str) -> CurrentUser:
    settings = get_settings()
    header, claims = _decode_unverified_jwt(token)
    token_alg = header.get("alg")

    if token_alg == "HS256":
        if not settings.SUPABASE_JWT_SECRET:
            logger.error("SUPABASE_JWT_SECRET is not configured")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication is not configured",
            )

        try:
            claims = _decode_and_verify_hs256(token, settings.SUPABASE_JWT_SECRET.strip())
        except InvalidAuthTokenError:
            # Supabase projects can be migrated to new signing keys while legacy
            # HS256 secrets still exist. Let Supabase Auth make the final call.
            return _verify_token_with_supabase_auth(token, claims)

        _validate_supabase_claims(claims, settings.SUPABASE_URL)
        return _current_user_from_claims(claims)

    if not isinstance(token_alg, str) or not token_alg:
        raise InvalidAuthTokenError("Token algorithm is missing")

    return _verify_token_with_supabase_auth(token, claims)


def _current_user_from_claims(claims: dict[str, Any]) -> CurrentUser:
    subject = claims.get("sub")
    expires_at = claims.get("exp")
    if not isinstance(subject, str) or not subject:
        raise InvalidAuthTokenError("Token is missing subject")
    if not isinstance(expires_at, int):
        raise InvalidAuthTokenError("Token is missing expiry")

    email = claims.get("email")
    if not isinstance(email, str):
        user_metadata = claims.get("user_metadata")
        email = user_metadata.get("email") if isinstance(user_metadata, dict) else None
    if isinstance(email, str):
        email = email.strip().lower()

    return CurrentUser(
        user_id=subject,
        email=email,
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        claims=claims,
    )


def _verify_token_with_supabase_auth(token: str, fallback_claims: dict[str, Any]) -> CurrentUser:
    settings = get_settings()
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        logger.error("Supabase Auth verification is not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication is not configured",
        )

    try:
        response = httpx.get(
            f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/user",
            headers={
                "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
                "Authorization": f"Bearer {token}",
            },
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}:
            raise InvalidAuthTokenError("Invalid authentication token") from exc
        logger.exception("Supabase Auth token verification failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable",
        ) from exc
    except httpx.HTTPError as exc:
        logger.exception("Supabase Auth token verification failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is unavailable",
        ) from exc

    user = response.json()
    user_id = user.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise InvalidAuthTokenError("Token is missing subject")

    email = user.get("email")
    if isinstance(email, str):
        email = email.strip().lower()
    else:
        email = None

    expires_at = fallback_claims.get("exp")
    if not isinstance(expires_at, int):
        expires_at = int(datetime.now(tz=timezone.utc).timestamp())

    claims = {**fallback_claims, "sub": user_id, "email": email}
    return CurrentUser(
        user_id=user_id,
        email=email,
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
        claims=claims,
    )


def _decode_and_verify_hs256(token: str, secret: str) -> dict[str, Any]:
    header, payload = _decode_unverified_jwt(token)
    encoded_header, encoded_payload, encoded_signature = token.split(".")
    try:
        signature = _base64url_decode(encoded_signature)
    except (ValueError, binascii.Error) as exc:
        raise InvalidAuthTokenError("Malformed authentication token") from exc

    if header.get("alg") != "HS256":
        raise InvalidAuthTokenError("Unsupported token algorithm")

    signed_content = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        signed_content,
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise InvalidAuthTokenError("Invalid authentication token")

    expires_at = payload.get("exp")
    if not isinstance(expires_at, int):
        raise InvalidAuthTokenError("Token is missing expiry")
    if expires_at <= int(datetime.now(tz=timezone.utc).timestamp()):
        raise ExpiredAuthTokenError("Token has expired")

    return payload


def _decode_unverified_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parts = token.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise InvalidAuthTokenError("Malformed authentication token")

    encoded_header, encoded_payload, _encoded_signature = parts
    try:
        header = json.loads(_base64url_decode(encoded_header))
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError, binascii.Error) as exc:
        raise InvalidAuthTokenError("Malformed authentication token") from exc

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise InvalidAuthTokenError("Malformed authentication token")
    return header, payload


def _validate_supabase_claims(claims: dict[str, Any], supabase_url: str) -> None:
    audience = claims.get("aud")
    if isinstance(audience, str):
        audiences = {audience}
    elif isinstance(audience, list):
        audiences = {item for item in audience if isinstance(item, str)}
    else:
        audiences = set()
    if "authenticated" not in audiences:
        raise InvalidAuthTokenError("Token audience is not allowed")

    if claims.get("role") != "authenticated":
        raise InvalidAuthTokenError("Token role is not allowed")

    issued_at = claims.get("iat")
    not_before = claims.get("nbf")
    now = int(datetime.now(tz=timezone.utc).timestamp())
    if isinstance(issued_at, int) and issued_at > now + 60:
        raise InvalidAuthTokenError("Token issued-at time is invalid")
    if isinstance(not_before, int) and not_before > now:
        raise InvalidAuthTokenError("Token is not active")

    issuer = claims.get("iss")
    expected_issuer = f"{supabase_url.rstrip('/')}/auth/v1" if supabase_url else None
    if expected_issuer and (not isinstance(issuer, str) or issuer.rstrip("/") != expected_issuer):
        raise InvalidAuthTokenError("Token issuer is not allowed")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        current_user = verify_supabase_jwt(credentials.credentials)
    except ExpiredAuthTokenError:
        logger.info("Rejected expired Supabase JWT")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidAuthTokenError:
        logger.info("Rejected invalid Supabase JWT")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _require_allowed_user(current_user)
    return current_user


def get_current_user_id(current_user: CurrentUser = Depends(get_current_user)) -> str:
    return current_user.user_id


def _require_allowed_user(current_user: CurrentUser) -> None:
    if not current_user.email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authenticated email is required")
    try:
        if not get_supabase_service().is_allowed_user(current_user.email):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access is not allowlisted")
    except HTTPException:
        raise
    except SupabaseServiceConfigError as exc:
        logger.error("Supabase allowlist service is not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Access control is not configured",
        ) from exc
    except SupabaseDatabaseError as exc:
        logger.exception("Failed to verify allowlist")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Access control is unavailable",
        ) from exc
