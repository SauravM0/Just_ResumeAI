"""
Application configuration loaded from environment variables.
Uses pydantic-settings for type-safe config with validation.
"""

from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEX_TEMPLATE_DIR = BACKEND_ROOT / "templates" / "latex"
DEFAULT_LATEX_OUTPUT_DIR = BACKEND_ROOT / "output"


class Settings(BaseSettings):
    """Application settings loaded from .env file or environment variables."""

    # --- App ---
    APP_NAME: str = "JustResume AI"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "development"
    DEBUG: bool = False
    # Keep frontend origins env-driven so local/dev/prod hosts are configured in one place.
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Gemini AI ---
    # Empty is allowed so the backend can still start in environments where AI-backed
    # flows are unavailable or replaced by later fallback behavior.
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"
    GEMINI_REVIEW_MODEL: str = "gemini-2.0-pro"
    GEMINI_MAX_RETRIES: int = 3
    GEMINI_TEMPERATURE: float = 0.3
    GEMINI_MAX_TOKENS: int = 8192
    GEMINI_TIMEOUT_SECONDS: float = 45.0
    GEMINI_RETRY_BASE_DELAY_SECONDS: float = 1.5
    GEMINI_RETRY_MAX_DELAY_SECONDS: float = 8.0

    # --- Supabase auth, database, and storage ---
    SUPABASE_URL: str = ""
    SUPABASE_JWT_SECRET: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "generated-resumes"

    # --- RAG / Embeddings ---
    ENABLE_RAG_EMBEDDINGS: bool = True
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMS: int = 768
    SIMILARITY_THRESHOLD: float = 0.55

    # --- Feature flags ---
    ENABLE_JD_CACHE: bool = True
    ENABLE_RECRUITER_REVIEW: bool = True
    # Auth access modes:
    #   "allowlist" - require the user's email in public.allowed_users.
    #   "google" - allow any Supabase-authenticated user whose provider is Google.
    AUTH_ACCESS_MODE: str = "allowlist"
    ALLOW_ALL_AUTHENTICATED_USERS: bool = False

    # --- Caching ---
    JD_CACHE_TTL_HOURS: int = 24

    # --- Rate limiting ---
    MAX_GENERATION_REQUESTS_PER_HOUR: int = 5
    MAX_JD_ANALYSIS_REQUESTS_PER_HOUR: int = 15
    MAX_REQUEST_BODY_SIZE_KB: int = 512
    ENABLE_GENERATION_LIMITS: bool = True
    HOURLY_GENERATION_LIMIT_PER_USER: int = 5
    DAILY_GENERATION_LIMIT_PER_USER: int = 20
    MAX_ACTIVE_GENERATIONS_PER_USER: int = 2

    # --- API limits ---
    MAX_JD_TEXT_LENGTH: int = 15_000
    MAX_RAW_JD_CHARS: int = 15_000
    MAX_PROFILE_PAYLOAD_CHARS: int = 120_000
    MAX_ALIGNMENT_TEXT_CHARS: int = 6_000

    # --- SSE streaming ---
    SSE_KEEPALIVE_INTERVAL: int = 15

    # --- Error handling ---
    # When True and DEBUG is enabled, internal exception details are included in error responses.
    # Set to False in production to avoid leaking stack traces or implementation details.
    EXPOSE_ERROR_DETAILS: bool = False

    # --- Generated files ---
    FILE_EXPIRY_DAYS: int = 7

    # --- LaTeX ---
    LATEX_TEMPLATE_DIR: str = str(DEFAULT_LATEX_TEMPLATE_DIR)
    LATEX_OUTPUT_DIR: str = str(DEFAULT_LATEX_OUTPUT_DIR)
    LATEX_EXTRACTION_CALIBRATION: float = 8.0
    DEFAULT_ATS_OPTIMIZATION_MODE: str = "aggressive"

    # --- Queue / Background Jobs ---
    # REDIS_URL: Redis connection string used when GENERATION_EXECUTOR=worker.
    REDIS_URL: str = "redis://localhost:6379/0"
    # GENERATION_EXECUTOR: controls how generation jobs are dispatched.
    #   "in-process" (default) — runs generation via asyncio.create_task.
    #   "worker" — enqueues jobs to Redis/RQ for a separate worker process.
    GENERATION_EXECUTOR: str = "in-process"
    # GENERATION_QUEUE_NAME: Redis/RQ queue key for generation jobs.
    GENERATION_QUEUE_NAME: str = "generations"
    # GENERATION_MAX_RETRIES: max retry attempts for failed generation jobs.
    GENERATION_MAX_RETRIES: int = 3

    # --- Stale Generation Sweeper ---
    # STALE_GENERATION_TIMEOUT_MINUTES: how long a running/queued generation can
    #   stay without progress before the sweeper considers it stale.
    STALE_GENERATION_TIMEOUT_MINUTES: int = 10
    # GENERATION_STALE_SWEEPER_ENABLED: set true to auto-start the sweeper loop.
    #   Defaults to false so the sweeper never runs unexpectedly in production.
    GENERATION_STALE_SWEEPER_ENABLED: bool = False
    # GENERATION_STALE_SWEEPER_INTERVAL_SECONDS: sleep between sweep iterations.
    GENERATION_STALE_SWEEPER_INTERVAL_SECONDS: int = 60

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("DEBUG", mode="before")
    @classmethod
    def _parse_debug(cls, value):
        if isinstance(value, str) and value.lower() in {"release", "prod", "production"}:
            return False
        return value

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value):
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                return json.loads(raw)
            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value

    @field_validator("GENERATION_EXECUTOR", mode="before")
    @classmethod
    def _validate_generation_executor(cls, value):
        allowed = {"in-process", "worker"}
        if isinstance(value, str):
            lower = value.lower().strip()
            if lower not in allowed:
                raise ValueError(
                    f"GENERATION_EXECUTOR must be one of {allowed}, got '{value}'"
                )
            return lower
        return value

    @field_validator("AUTH_ACCESS_MODE", mode="before")
    @classmethod
    def _validate_auth_access_mode(cls, value):
        allowed = {"allowlist", "google"}
        if isinstance(value, str):
            lower = value.lower().strip()
            if lower not in allowed:
                raise ValueError(
                    f"AUTH_ACCESS_MODE must be one of {allowed}, got '{value}'"
                )
            return lower
        return value

    def check_required(self, *names: str) -> list[str]:
        """Return list of required env var names that are empty."""
        return [name for name in names if not getattr(self, name, None)]

    def get_feature_flags(self) -> dict[str, bool]:
        """Return all ENABLE_* settings as a flat dict for health/status endpoints."""
        return {
            key: bool(getattr(self, key))
            for key in dir(self)
            if key.startswith("ENABLE_") and isinstance(getattr(self, key), bool)
        }

    @model_validator(mode="after")
    def _validate_production_settings(self):
        is_production = self.APP_ENV.lower() in {"prod", "production"}

        # Basic verification for all environments
        missing = self.check_required(
            "SUPABASE_URL",
            "SUPABASE_JWT_SECRET",
            "SUPABASE_SERVICE_ROLE_KEY",
        )
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}. "
                f"Please copy .env.example to .env and fill in the values."
            )

        if is_production:
            prod_missing = self.check_required(
                "GEMINI_API_KEY",
                "SUPABASE_STORAGE_BUCKET",
            )
            if prod_missing:
                raise ValueError(
                    f"Production environment requires additional variables: {', '.join(prod_missing)}. "
                    f"Set them in your deployment platform (e.g. Render, Railway)."
                )

            if not self.CORS_ORIGINS:
                raise ValueError(
                    "CORS_ORIGINS must be configured in production to allow your frontend to connect. "
                    "Example: CORS_ORIGINS=https://app.fundocareer.com"
                )

            if any(origin.strip() == "*" for origin in self.CORS_ORIGINS):
                raise ValueError(
                    "Wildcard CORS_ORIGINS ('*') are strictly prohibited in production for security reasons."
                )

            if self.ALLOW_ALL_AUTHENTICATED_USERS:
                raise ValueError(
                    "ALLOW_ALL_AUTHENTICATED_USERS must remain false in production. "
                    "Use allowed_users for production access control."
                )
        return self


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton for app settings."""
    return Settings()
