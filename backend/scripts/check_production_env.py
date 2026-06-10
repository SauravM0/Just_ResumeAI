"""Validate production environment settings without contacting services."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


SECRET_NAMES = {
    "GEMINI_API_KEY",
    "REDIS_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_SERVICE_ROLE_KEY",
    "VITE_SUPABASE_ANON_KEY",
}

BACKEND_REQUIRED = {
    "APP_ENV",
    "DEBUG",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "GEMINI_API_KEY",
    "CORS_ORIGINS",
    "ALLOW_ALL_AUTHENTICATED_USERS",
    "GENERATION_EXECUTOR",
    "GENERATION_QUEUE_NAME",
    "GENERATION_MAX_RETRIES",
    "STALE_GENERATION_TIMEOUT_MINUTES",
    "GENERATION_STALE_SWEEPER_ENABLED",
    "GENERATION_STALE_SWEEPER_INTERVAL_SECONDS",
    "LATEX_OUTPUT_DIR",
}

FRONTEND_REQUIRED = {
    "VITE_API_BASE",
    "VITE_SUPABASE_URL",
    "VITE_SUPABASE_ANON_KEY",
}

VALID_EXECUTORS = {"in-process", "worker"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check production env readiness without printing secrets or "
            "calling external services."
        )
    )
    parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        help="Optional .env file to read. Can be passed more than once.",
    )
    parser.add_argument(
        "--include-frontend",
        action="store_true",
        help="Also require frontend VITE_* variables.",
    )
    return parser.parse_args()


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"env file not found: {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = strip_inline_comment(value.strip()).strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def strip_inline_comment(value: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            previous = value[index - 1] if index else " "
            if previous.isspace():
                return value[:index]
    return value


def merged_env(env_files: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for env_file in env_files:
        values.update(load_env_file(Path(env_file)))
    values.update(os.environ)
    return values


def is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_falsey(value: str | None) -> bool:
    return (value or "").strip().lower() in {"0", "false", "no", "off"}


def is_missing(env: dict[str, str], name: str) -> bool:
    value = env.get(name)
    return value is None or value.strip() == ""


def contains_wildcard(cors_origins: str) -> bool:
    cleaned = cors_origins.strip()
    if cleaned == "*":
        return True
    tokens = (
        cleaned.replace("[", "")
        .replace("]", "")
        .replace('"', "")
        .replace("'", "")
        .split(",")
    )
    return any(token.strip() == "*" for token in tokens)


def validate(env: dict[str, str], include_frontend: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    required = set(BACKEND_REQUIRED)
    if include_frontend:
        required.update(FRONTEND_REQUIRED)

    for name in sorted(required):
        if is_missing(env, name):
            errors.append(f"missing required variable: {name}")

    app_env = env.get("APP_ENV", "").strip().lower()
    is_production = app_env in {"prod", "production"}
    executor = env.get("GENERATION_EXECUTOR", "in-process").strip().lower()

    if executor and executor not in VALID_EXECUTORS:
        errors.append(
            "GENERATION_EXECUTOR must be one of: in-process, worker"
        )

    if is_production:
        if not is_falsey(env.get("DEBUG")):
            errors.append("APP_ENV=production requires DEBUG=false")
        if is_truthy(env.get("ALLOW_ALL_AUTHENTICATED_USERS")):
            errors.append(
                "APP_ENV=production requires ALLOW_ALL_AUTHENTICATED_USERS=false"
            )
        cors_origins = env.get("CORS_ORIGINS", "")
        if contains_wildcard(cors_origins):
            errors.append("APP_ENV=production forbids wildcard CORS_ORIGINS")
        if "localhost" in cors_origins or "127.0.0.1" in cors_origins:
            warnings.append(
                "CORS_ORIGINS contains localhost entries in production"
            )

    if executor == "worker" and is_missing(env, "REDIS_URL"):
        warnings.append("GENERATION_EXECUTOR=worker should set REDIS_URL")

    if executor == "in-process" and is_truthy(
        env.get("GENERATION_STALE_SWEEPER_ENABLED")
    ):
        warnings.append(
            "sweeper is enabled while GENERATION_EXECUTOR is in-process"
        )

    vite_api_base = env.get("VITE_API_BASE", "")
    if include_frontend and vite_api_base and not vite_api_base.rstrip("/").endswith(
        "/api/v1"
    ):
        warnings.append("VITE_API_BASE should include /api/v1")

    for name in sorted(SECRET_NAMES):
        if env.get(name, "").strip():
            warnings.append(f"{name} is set; value hidden")

    return errors, warnings


def main() -> int:
    args = parse_args()
    try:
        env = merged_env(args.env_file)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    errors, warnings = validate(env, include_frontend=args.include_frontend)

    print("Production environment check")
    print("============================")
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"- {warning}")
    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"- {error}")
        print("\nResult: failed")
        return 1

    print("\nResult: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
