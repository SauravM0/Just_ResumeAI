"""
Application configuration loaded from environment variables.
Uses pydantic-settings for type-safe config with validation.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LATEX_TEMPLATE_DIR = BACKEND_ROOT / "templates" / "latex"
DEFAULT_LATEX_OUTPUT_DIR = BACKEND_ROOT / "output"


class Settings(BaseSettings):
    """Application settings loaded from .env file or environment variables."""

    # --- App ---
    APP_NAME: str = "JustResume AI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    # --- Gemini AI ---
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_MAX_RETRIES: int = 1
    GEMINI_TEMPERATURE: float = 0.3
    GEMINI_RETRY_BASE_DELAY_SECONDS: float = 1.5
    GEMINI_RETRY_MAX_DELAY_SECONDS: float = 8.0

    # --- LaTeX ---
    LATEX_TEMPLATE_DIR: str = str(DEFAULT_LATEX_TEMPLATE_DIR)
    LATEX_OUTPUT_DIR: str = str(DEFAULT_LATEX_OUTPUT_DIR)

    # --- Session ---
    # Sessions are ephemeral; stored in-memory for MVP.
    # No persistent DB for user profiles (client-side IndexedDB is source of truth).
    SESSION_TTL_MINUTES: int = 120

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton for app settings."""
    return Settings()
