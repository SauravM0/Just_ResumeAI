"""
Application configuration loaded from environment variables.
Uses pydantic-settings for type-safe config with validation.
"""

from functools import lru_cache
import json
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEX_TEMPLATE_DIR = BACKEND_ROOT / "templates" / "latex"
DEFAULT_LATEX_OUTPUT_DIR = BACKEND_ROOT / "output"
DEFAULT_SESSION_DB_PATH = DEFAULT_LATEX_OUTPUT_DIR / "sessions.sqlite3"


class Settings(BaseSettings):
    """Application settings loaded from .env file or environment variables."""

    # --- App ---
    APP_NAME: str = "JustResume AI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    # Keep frontend origins env-driven so local/dev/prod hosts are configured in one place.
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # --- Gemini AI ---
    # Empty is allowed so the backend can still start in environments where AI-backed
    # flows are unavailable or replaced by later fallback behavior.
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_REVIEW_MODEL: str = "gemini-2.5-pro"
    GEMINI_MAX_RETRIES: int = 3
    GEMINI_TEMPERATURE: float = 0.3
    GEMINI_TIMEOUT_SECONDS: float = 45.0
    GEMINI_RETRY_BASE_DELAY_SECONDS: float = 1.5
    GEMINI_RETRY_MAX_DELAY_SECONDS: float = 8.0

    # --- LaTeX ---
    LATEX_TEMPLATE_DIR: str = str(DEFAULT_LATEX_TEMPLATE_DIR)
    LATEX_OUTPUT_DIR: str = str(DEFAULT_LATEX_OUTPUT_DIR)

    # --- Session ---
    # Sessions persist short-lived pipeline state only.
    # The full master profile remains client-side and is not stored server-side.
    SESSION_TTL_MINUTES: int = 120
    SESSION_DB_PATH: str = str(DEFAULT_SESSION_DB_PATH)

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


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton for app settings."""
    return Settings()
