"""Safe production smoke tests for deployed JustResume API endpoints."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PUBLIC_CHECKS = (
    ("health", "GET", "/health"),
    ("readiness", "GET", "/health/ready"),
)

AUTHENTICATED_CHECKS = (
    ("profile", "GET", "/profile/me"),
    ("settings", "GET", "/settings"),
    ("generations", "GET", "/generations"),
)

ADMIN_CHECKS = (
    ("metrics", "GET", "/metrics"),
)


@dataclass
class CheckResult:
    name: str
    method: str
    path: str
    ok: bool
    status_code: int | None
    detail: str
    duration_ms: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run safe JustResume production smoke tests. Public checks run by "
            "default; authenticated/admin/generation checks require explicit "
            "tokens or flags."
        )
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help=(
            "Backend base URL. May be either the API root "
            "(https://api.example.com/api/v1) or service root "
            "(https://api.example.com)."
        ),
    )
    parser.add_argument(
        "--token",
        help="Optional user bearer token for authenticated read checks.",
    )
    parser.add_argument(
        "--admin-token",
        help="Optional admin bearer token for /metrics.",
    )
    parser.add_argument(
        "--skip-authenticated",
        action="store_true",
        help="Skip authenticated user checks even if --token is provided.",
    )
    parser.add_argument(
        "--skip-generation",
        action="store_true",
        help="Skip generation even if --run-generation is also provided.",
    )
    parser.add_argument(
        "--run-generation",
        action="store_true",
        help=(
            "Explicitly run the mutating generation smoke test. Requires "
            "--token and --generation-payload."
        ),
    )
    parser.add_argument(
        "--generation-payload",
        help=(
            "Path to a JSON payload for POST /pipeline/generate/start. "
            "Required only with --run-generation."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds. Default: 10.",
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


def load_generation_payload(path: str | None) -> dict[str, Any]:
    if not path:
        raise ValueError("--generation-payload is required with --run-generation")
    payload_path = Path(path)
    if not payload_path.exists():
        raise ValueError(f"generation payload file not found: {payload_path}")
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("generation payload must be a JSON object")
    if "raw_jd_text" not in payload or "profile" not in payload:
        raise ValueError(
            "generation payload must include at least 'profile' and 'raw_jd_text'"
        )
    return payload


def make_headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "justresume-production-smoke-test/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def run_http_check(
    *,
    base_url: str,
    name: str,
    method: str,
    path: str,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float,
    expected_statuses: set[int] | None = None,
) -> CheckResult:
    expected = expected_statuses or {200}
    body = None
    headers = make_headers(token)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.status
            # Drain the body so connection errors surface, but never print it.
            response.read()
    except HTTPError as exc:
        status_code = exc.code
        detail = f"HTTP {status_code}"
        ok = status_code in expected
        duration_ms = elapsed_ms(started)
        return CheckResult(name, method, path, ok, status_code, detail, duration_ms)
    except URLError as exc:
        detail = f"connection error: {exc.reason}"
        return CheckResult(name, method, path, False, None, detail, elapsed_ms(started))
    except TimeoutError:
        return CheckResult(name, method, path, False, None, "timeout", elapsed_ms(started))

    ok = status_code in expected
    detail = f"HTTP {status_code}"
    return CheckResult(name, method, path, ok, status_code, detail, elapsed_ms(started))


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def print_result(result: CheckResult) -> None:
    label = "PASS" if result.ok else "FAIL"
    print(
        f"[{label}] {result.name}: {result.method} {result.path} "
        f"{result.detail} ({result.duration_ms} ms)"
    )


def run_checks(args: argparse.Namespace) -> int:
    base_url = normalize_base_url(args.base_url)
    results: list[CheckResult] = []

    for name, method, path in PUBLIC_CHECKS:
        results.append(
            run_http_check(
                base_url=base_url,
                name=name,
                method=method,
                path=path,
                timeout=args.timeout,
            )
        )

    if args.token and not args.skip_authenticated:
        for name, method, path in AUTHENTICATED_CHECKS:
            results.append(
                run_http_check(
                    base_url=base_url,
                    name=name,
                    method=method,
                    path=path,
                    token=args.token,
                    timeout=args.timeout,
                )
            )
    elif args.skip_authenticated:
        print("[SKIP] authenticated checks skipped by --skip-authenticated")
    else:
        print("[SKIP] authenticated checks skipped; no --token provided")

    if args.admin_token:
        for name, method, path in ADMIN_CHECKS:
            results.append(
                run_http_check(
                    base_url=base_url,
                    name=name,
                    method=method,
                    path=path,
                    token=args.admin_token,
                    timeout=args.timeout,
                )
            )
    else:
        print("[SKIP] admin checks skipped; no --admin-token provided")

    if args.run_generation and not args.skip_generation:
        if not args.token:
            raise ValueError("--run-generation requires --token")
        payload = load_generation_payload(args.generation_payload)
        results.append(
            run_http_check(
                base_url=base_url,
                name="generation_start",
                method="POST",
                path="/pipeline/generate/start",
                token=args.token,
                payload=payload,
                timeout=args.timeout,
                expected_statuses={200, 201, 202},
            )
        )
    elif args.skip_generation:
        print("[SKIP] generation check skipped by --skip-generation")
    else:
        print("[SKIP] generation check skipped; pass --run-generation to enable")

    print()
    for result in results:
        print_result(result)

    failed = [result for result in results if not result.ok]
    print()
    print(f"Summary: {len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


def main() -> int:
    args = parse_args()
    try:
        return run_checks(args)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
