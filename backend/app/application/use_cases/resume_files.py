"""
File metadata listing use case.

Returns empty file metadata; exports are direct downloads and are not stored
as persistent file records in this codebase.
"""

from __future__ import annotations

from app.services.storage_service import summarize_generation_files


def get_generation_file_metadata(generation_id: str) -> dict:
    """Return empty file metadata for a generation."""
    files: list = []
    return {
        "generation_id": generation_id,
        **summarize_generation_files(files),
        "files": files,
    }
