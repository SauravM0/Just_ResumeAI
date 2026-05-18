import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging
import os

from app.api.v1.router import api_router
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

settings = get_settings()

REQUIRED_EVERYWHERE = [
    "SUPABASE_URL",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_SERVICE_ROLE_KEY",
]


def validate_environment():
    """Validate required environment variables on startup.

    Prints clear error messages without exposing secret values.
    Exits the process if critical variables are missing.
    """
    missing_required = settings.check_required(*REQUIRED_EVERYWHERE)
    if missing_required:
        logger.error(
            "Missing required environment variables: %s. "
            "The application cannot start without these. "
            "Add them to your .env file or deployment environment.",
            ", ".join(missing_required),
        )

    is_production = settings.APP_ENV.lower() in {"prod", "production"}

    if is_production:
        if settings.DEBUG:
            logger.warning("DEBUG is enabled in production. Set DEBUG=false for security.")

        if not settings.CORS_ORIGINS:
            logger.error(
                "CORS_ORIGINS is empty in production. "
                "Set CORS_ORIGINS to your frontend domain(s), e.g. https://my-app.vercel.app"
            )

    if missing_required:
        logger.error(
            "Startup aborted due to missing required environment variables. "
            "See errors above. No secrets have been printed."
        )
        sys.exit(1)


validate_environment()

app = FastAPI(title="JustResume AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition", "X-Compile-Warnings", "X-Regenerated"],
)

app.include_router(api_router)


@app.on_event("startup")
async def startup():
    """Initialize application on startup."""
    os.makedirs(settings.LATEX_OUTPUT_DIR, exist_ok=True)

    logger.info("=" * 50)
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Environment: %s", settings.APP_ENV)
    logger.info("Debug mode: %s", settings.DEBUG)
    logger.info("CORS origins: %s", settings.CORS_ORIGINS)
    logger.info("LaTeX template dir: %s", settings.LATEX_TEMPLATE_DIR)
    logger.info("LaTeX output dir: %s", settings.LATEX_OUTPUT_DIR)
    logger.info("File expiry: %d days", settings.FILE_EXPIRY_DAYS)
    logger.info(
        "Gemini model: %s (review: %s)",
        settings.GEMINI_MODEL,
        settings.GEMINI_REVIEW_MODEL,
    )
    logger.info("Supabase storage bucket: %s", settings.SUPABASE_STORAGE_BUCKET)
    logger.info("Supabase URL: %s", "configured" if settings.SUPABASE_URL else "MISSING")
    logger.info("Supabase JWT secret: %s", "configured" if settings.SUPABASE_JWT_SECRET else "MISSING")
    logger.info("Supabase service role key: %s", "configured" if settings.SUPABASE_SERVICE_ROLE_KEY else "MISSING")
    logger.info("Gemini API key: %s", "configured" if settings.GEMINI_API_KEY else "MISSING")
    logger.info("=" * 50)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    reload_enabled = settings.DEBUG and not (settings.APP_ENV.lower() in {"prod", "production"})
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload_enabled)
