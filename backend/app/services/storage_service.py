"""Supabase Storage service for generated file management."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import httpx

from app.config import get_settings
from app.services.supabase_service import get_supabase_service
from app.schemas.supabase import GeneratedFileCreate

logger = logging.getLogger(__name__)

STORAGE_PATH_TEMPLATE = "users/{user_id}/generations/{generation_id}/resume.{ext}"

FILE_EXT_MAP = {
    "pdf": "pdf",
    "docx": "docx",
    "tex": "tex",
}

CONTENT_TYPE_MAP = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "tex": "text/plain",
}


class StorageServiceError(RuntimeError):
    """Base error for storage service failures."""


class StorageConfigError(StorageServiceError):
    """Raised when Supabase Storage is not configured."""


def expected_storage_path(user_id: str, generation_id: str, file_type: str) -> str:
    """Return the only valid object path for a generated file."""
    ext = FILE_EXT_MAP.get(file_type, file_type)
    return STORAGE_PATH_TEMPLATE.format(
        user_id=user_id,
        generation_id=generation_id,
        ext=ext,
    )


def validate_generation_storage_path(
    storage_path: str,
    *,
    user_id: str,
    generation_id: str,
    file_type: str,
) -> bool:
    """Confirm metadata points to the expected user/generation object path."""
    return storage_path == expected_storage_path(user_id, generation_id, file_type)


def _ensure_configured():
    settings = get_settings()
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise StorageConfigError("Supabase Storage is not configured")


def _client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        headers={
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        },
        timeout=30.0,
    )


def _storage_base() -> str:
    return f"{get_settings().SUPABASE_URL.rstrip('/')}/storage/v1"


def _bucket() -> str:
    return get_settings().SUPABASE_STORAGE_BUCKET


def upload_generated_file(
    user_id: str,
    generation_id: str,
    file_type: str,
    local_path: str,
) -> dict:
    """
    Upload a generated file to Supabase Storage, create a db record, and return a signed URL.

    Args:
        user_id:        User UUID string.
        generation_id:  Generation UUID string.
        file_type:      One of ``pdf``, ``docx``, ``tex``.
        local_path:     Local file path to upload.

    Returns:
        ``signed_url``, ``expires_at``, ``storage_path``, ``file_type``.

    Raises:
        StorageConfigError if Supabase storage is not configured.
        StorageServiceError if the upload or signed-url creation fails.
    """
    _ensure_configured()

    ext = FILE_EXT_MAP.get(file_type, file_type)
    storage_path = STORAGE_PATH_TEMPLATE.format(
        user_id=user_id,
        generation_id=generation_id,
        ext=ext,
    )

    file_bytes = Path(local_path).read_bytes()
    bucket = _bucket()
    base = _storage_base()
    upload_url = f"{base}/object/{bucket}/{storage_path}"
    content_type = CONTENT_TYPE_MAP.get(file_type, "application/octet-stream")

    with _client() as cl:
        resp = cl.post(
            upload_url,
            content=file_bytes,
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        resp.raise_for_status()

    try:
        Path(local_path).unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove local temp file: %s", local_path)

    expires_at = datetime.now(timezone.utc) + timedelta(
        days=get_settings().FILE_EXPIRY_DAYS
    )

    svc = get_supabase_service()
    svc.create_file_record(
        user_id=user_id,
        generation_id=generation_id,
        data=GeneratedFileCreate(
            file_type=file_type,
            storage_path=storage_path,
            expires_at=expires_at,
        ),
    )

    signed_url = create_signed_download_url(storage_path)

    return {
        "signed_url": signed_url,
        "expires_at": expires_at.isoformat(),
        "storage_path": storage_path,
        "file_type": file_type,
    }


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _field(record, name: str):
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def summarize_generation_files(files: list) -> dict:
    """Build UI/API-safe availability fields for generated file metadata."""
    now = datetime.now(timezone.utc)
    file_info = []
    unexpired_expiries: list[datetime] = []
    expired_expiries: list[datetime] = []
    pdf_available = False
    docx_available = False

    for file_record in files:
        expires_at = _as_utc(_field(file_record, "expires_at"))
        is_expired = expires_at < now if expires_at else False
        if expires_at:
            if is_expired:
                expired_expiries.append(expires_at)
            else:
                unexpired_expiries.append(expires_at)

        file_type = _field(file_record, "file_type")
        if file_type == "pdf" and not is_expired:
            pdf_available = True
        if file_type == "docx" and not is_expired:
            docx_available = True

        file_info.append({
            "file_type": file_type,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "is_expired": is_expired,
        })

    has_files = bool(file_info)
    expires_at = None
    if unexpired_expiries:
        expires_at = min(unexpired_expiries)
    elif expired_expiries:
        expires_at = max(expired_expiries)

    return {
        "has_files": has_files,
        "pdf_available": pdf_available,
        "docx_available": docx_available,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "earliest_expiry": expires_at.isoformat() if expires_at else None,
        "is_expired": has_files and not pdf_available and not docx_available,
        "regenerate_available": has_files and not pdf_available and not docx_available,
        "files": file_info,
    }


def create_signed_download_url(
    storage_path: str,
    expires_in_seconds: int = 3600,
) -> str:
    """
    Create a time-limited signed URL for a file stored in Supabase Storage.

    Args:
        storage_path:       Path within the bucket (e.g. ``users/.../resume.pdf``).
        expires_in_seconds: Seconds until the signed URL itself expires (default 1 hour).

    Returns:
        Full HTTPS signed URL.
    """
    _ensure_configured()

    bucket = _bucket()
    base = _storage_base()
    signed_endpoint = f"{base}/object/sign/{bucket}/{storage_path}"

    with _client() as cl:
        resp = cl.post(signed_endpoint, json={"expiresIn": expires_in_seconds})
        resp.raise_for_status()
        data = resp.json()
        signed_path = data.get("signedURL") or data.get("url") or ""

    if signed_path.startswith("http"):
        return signed_path
    return f"{base.rstrip('/')}{signed_path}"


def get_file_status(user_id: str, generation_id: str) -> list[dict]:
    """
    Return file info for all non-deleted files belonging to a generation.

    Each entry includes a fresh signed URL (unless the file is expired).
    """
    svc = get_supabase_service()
    files = svc.get_generation_files(user_id, generation_id)

    now = datetime.now(timezone.utc)
    result = []
    for f in files:
        expires_at = _as_utc(f.expires_at)
        created_at = _as_utc(f.created_at)
        is_expired = expires_at < now if expires_at else False
        signed_url = None
        if not is_expired:
            try:
                if validate_generation_storage_path(
                    f.storage_path,
                    user_id=user_id,
                    generation_id=generation_id,
                    file_type=f.file_type,
                ):
                    signed_url = create_signed_download_url(f.storage_path)
                else:
                    logger.warning(
                        "Refusing to sign unexpected storage path for user=%s generation=%s file_id=%s",
                        user_id,
                        generation_id,
                        f.id,
                    )
            except Exception:
                logger.warning("Failed to create signed URL for %s", f.storage_path)

        result.append({
            "id": str(f.id),
            "file_type": f.file_type,
            "storage_path": f.storage_path,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "is_expired": is_expired,
            "created_at": created_at.isoformat() if created_at else None,
            "signed_url": signed_url,
        })
    return result


def delete_expired_files() -> int:
    """
    Delete expired generated files from Supabase Storage (soft-delete the db rows).

    Returns the number of files processed.
    """
    _ensure_configured()
    svc = get_supabase_service()
    now = datetime.now(timezone.utc)

    try:
        bucket = _bucket()
        base = _storage_base()
        files = _get_all_expired_records()

        deleted_count = 0
        for f in files:
            try:
                with _client() as cl:
                    resp = cl.delete(f"{base}/object/{bucket}/{f.storage_path}")
                    if resp.is_success:
                        svc.mark_file_deleted(f.id, now)
                        deleted_count += 1
            except Exception:
                logger.exception("Failed to delete expired file %s", f.storage_path)

        return deleted_count
    except Exception:
        logger.exception("Failed to delete expired files")
        return 0


def _get_all_expired_records() -> list:
    """Fetch all expired file records from the database."""
    from app.schemas.supabase import GeneratedFileRecord
    settings = get_settings()
    svc = get_supabase_service()

    try:
        client = svc._client
        response = client.get(
            svc._table_url("generated_files"),
            params={
                "select": "*",
                "deleted_at": "is.null",
                "expires_at": f"lt.{datetime.now(timezone.utc).isoformat()}",
            },
        )
        response.raise_for_status()
        return [GeneratedFileRecord.model_validate(r) for r in response.json()]
    except Exception as exc:
        logger.exception("Failed to fetch expired file records")
        raise StorageServiceError("Failed to fetch expired file records") from exc
