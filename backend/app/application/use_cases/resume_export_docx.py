"""
DOCX resume export use case.

Orchestrates DOCX export for saved resume generations.
The route layer stays HTTP-shaped; this module owns export validation,
generation, DB updates, and response construction.

SupabaseService = low-level DB adapter (raw PostgREST calls)
Repository      = table/use-case-specific database boundary (encapsulated queries)
"""

from __future__ import annotations

import json
import logging

from app.application.use_cases.resume_export_pdf import (
    _download_response,
    _log_export,
    require_saved_export_data,
)
from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.schemas.supabase import ResumeGenerationUpdate
from app.services.docx_export_service import export_resume_docx

logger = logging.getLogger(__name__)


def export_resume_docx_file(
    user_id: str,
    generation_id: str,
    gen,
    *,
    regenerated: bool = False,
):
    """
    Generate a DOCX from saved resume data and return a FileResponse.

    Preserves all existing headers:
      X-Regenerated, X-Validation-Repaired, X-Validation-Warnings
    """
    recommendation, _, validation_meta = require_saved_export_data(gen)
    docx_path = export_resume_docx(recommendation, generation_id)

    _log_export(user_id, generation_id, "docx_export", {"regenerated": regenerated})

    GenerationRepository().update(
        user_id=user_id,
        generation_id=generation_id,
        data=ResumeGenerationUpdate(
            last_exported_version_id=recommendation.version_id,
        ),
    )

    response = _download_response(
        docx_path,
        generation_id=generation_id,
        file_type="docx",
        candidate_name=recommendation.contact.full_name,
    )
    response.headers["X-Regenerated"] = "true" if regenerated else "false"
    response.headers["X-Validation-Repaired"] = "true" if validation_meta.get("validation_repaired") else "false"
    if validation_meta.get("validation_warnings"):
        response.headers["X-Validation-Warnings"] = json.dumps(validation_meta["validation_warnings"])
    return response
