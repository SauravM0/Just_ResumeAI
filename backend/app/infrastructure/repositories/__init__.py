"""
Repository layer: table/use-case-specific database boundaries.

Repositories wrap SupabaseService (low-level PostgREST adapter) to provide
focused, owner-scoped CRUD operations for each core table. Use cases should
depend on repositories, not raw table calls through SupabaseService.

SupabaseService = low-level DB adapter (raw PostgREST, schema-version-tolerant)
Repository      = table/use-case-specific database boundary (encapsulates queries)
"""

from app.infrastructure.repositories.generation_repository import GenerationRepository
from app.infrastructure.repositories.profile_repository import ProfileRepository
from app.infrastructure.repositories.settings_repository import SettingsRepository
from app.infrastructure.repositories.usage_repository import UsageRepository

__all__ = [
    "GenerationRepository",
    "ProfileRepository",
    "SettingsRepository",
    "UsageRepository",
]
