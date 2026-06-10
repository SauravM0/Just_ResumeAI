"""Launch readiness checks that avoid paid APIs and secret output."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from check_production_env import merged_env, validate


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


@dataclass
class Finding:
    level: str
    message: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check launch readiness without printing secrets, requiring live "
            "user auth, or calling paid APIs."
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
    parser.add_argument(
        "--base-url",
        help=(
            "Optional deployed backend URL. May be service root or /api/v1 root. "
            "Only /health and /health/ready are called."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds for health checks. Default: 10.",
    )
    return parser.parse_args()


def normalize_base_url(raw_base_url: str) -> str:
    base_url = raw_base_url.strip().rstrip("/")
    if not base_url:
        raise ValueError("--base-url cannot be empty")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("--base-url must start with http:// or https://")
    if not base_url.endswith("/api/v1"):
        base_url = f"{base_url}/api/v1"
    return base_url


def is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_falsey(value: str | None) -> bool:
    return (value or "").strip().lower() in {"0", "false", "no", "off"}


def run_http_get(base_url: str, path: str, timeout: float) -> Finding:
    request = Request(
        f"{base_url}{path}",
        headers={
            "Accept": "application/json",
            "User-Agent": "justresume-launch-readiness-check/1.0",
        },
        method="GET",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.status
            response.read()
    except HTTPError as exc:
        return Finding(FAIL, f"GET {path} returned HTTP {exc.code}")
    except URLError as exc:
        return Finding(FAIL, f"GET {path} connection error: {exc.reason}")
    except TimeoutError:
        return Finding(FAIL, f"GET {path} timed out")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if status_code == 200:
        return Finding(PASS, f"GET {path} returned 200 ({elapsed_ms} ms)")
    return Finding(FAIL, f"GET {path} returned HTTP {status_code}")


def evaluate_launch_posture(env: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []

    executor = env.get("GENERATION_EXECUTOR", "in-process").strip().lower()
    app_env = env.get("APP_ENV", "").strip().lower()
    sweeper_enabled = is_truthy(env.get("GENERATION_STALE_SWEEPER_ENABLED"))

    if app_env in {"prod", "production"}:
        findings.append(Finding(PASS, "APP_ENV is production"))
    else:
        findings.append(Finding(WARN, "APP_ENV is not production"))

    if is_falsey(env.get("ALLOW_ALL_AUTHENTICATED_USERS")):
        findings.append(Finding(PASS, "ALLOW_ALL_AUTHENTICATED_USERS is false"))
    else:
        findings.append(Finding(FAIL, "ALLOW_ALL_AUTHENTICATED_USERS must be false"))

    if executor == "in-process":
        findings.append(Finding(PASS, "Launch executor is in-process"))
        if sweeper_enabled:
            findings.append(Finding(WARN, "Sweeper is enabled in in-process mode"))
    elif executor == "worker":
        findings.append(Finding(WARN, "Launch executor is worker; verify Redis, worker, and rollback readiness"))
        if not env.get("REDIS_URL", "").strip():
            findings.append(Finding(FAIL, "Worker mode requires REDIS_URL"))
    else:
        findings.append(Finding(FAIL, "GENERATION_EXECUTOR must be in-process or worker"))

    cors = env.get("CORS_ORIGINS", "")
    if "localhost" in cors or "127.0.0.1" in cors:
        findings.append(Finding(WARN, "CORS_ORIGINS contains local origins"))

    if env.get("VITE_API_BASE", "").strip().rstrip("/").endswith("/api/v1"):
        findings.append(Finding(PASS, "VITE_API_BASE includes /api/v1"))
    elif env.get("VITE_API_BASE"):
        findings.append(Finding(WARN, "VITE_API_BASE should include /api/v1"))

    return findings


def collect_findings(args: argparse.Namespace) -> list[Finding]:
    env = merged_env(args.env_file)
    errors, warnings = validate(env, include_frontend=args.include_frontend)

    findings = [Finding(FAIL, error) for error in errors]
    findings.extend(Finding(WARN, warning) for warning in warnings)
    findings.extend(evaluate_launch_posture(env))

    if args.base_url:
        base_url = normalize_base_url(args.base_url)
        findings.append(run_http_get(base_url, "/health", args.timeout))
        findings.append(run_http_get(base_url, "/health/ready", args.timeout))
    else:
        findings.append(Finding(WARN, "No --base-url provided; deployed health checks skipped"))

    return findings


def print_summary(findings: list[Finding]) -> None:
    print("Launch readiness check")
    print("======================")

    for level in (FAIL, WARN, PASS):
        selected = [finding for finding in findings if finding.level == level]
        if not selected:
            continue
        print()
        print(f"{level}:")
        for finding in selected:
            print(f"- {finding.message}")

    failed = sum(1 for finding in findings if finding.level == FAIL)
    warned = sum(1 for finding in findings if finding.level == WARN)
    passed = sum(1 for finding in findings if finding.level == PASS)
    print()
    print(f"Summary: {passed} pass, {warned} warn, {failed} fail")


def main() -> int:
    args = parse_args()
    try:
        findings = collect_findings(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print_summary(findings)
    return 1 if any(finding.level == FAIL for finding in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
