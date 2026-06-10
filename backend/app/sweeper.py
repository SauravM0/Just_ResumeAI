"""
Stale generation sweeper CLI entrypoint.

Usage:
    python -m app.sweeper --once              # single sweep
    python -m app.sweeper --loop               # continuous loop
    python -m app.sweeper --once --force       # single sweep (skip config check)
    python -m app.sweeper --loop --force       # continuous loop (skip config check)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import get_settings
from app.services.stale_generation_sweeper import sweep_stale_generations_once

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _check_enabled(args: argparse.Namespace) -> bool:
    if args.force:
        return True
    settings = get_settings()
    if not settings.GENERATION_STALE_SWEEPER_ENABLED:
        logger.warning(
            "Stale generation sweeper is disabled (GENERATION_STALE_SWEEPER_ENABLED=false). "
            "Use --force to run anyway."
        )
        return False
    return True


async def _run_loop(args: argparse.Namespace) -> None:
    settings = get_settings()
    interval = settings.GENERATION_STALE_SWEEPER_INTERVAL_SECONDS
    logger.info(
        "Sweeper loop started (interval=%ds). Press Ctrl+C to stop.",
        interval,
    )
    while True:
        try:
            result = sweep_stale_generations_once()
            if any(v > 0 for v in result.values()):
                logger.info("Sweep result: %s", result)
        except Exception as exc:
            logger.error("Sweep cycle failed: %s", exc)
        await asyncio.sleep(interval)


def main() -> None:
    _configure_logging()

    parser = argparse.ArgumentParser(
        description="Stale generation sweeper — detect and recover stuck generations."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single sweep cycle and exit.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run the sweeper continuously (default interval: 60s).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if GENERATION_STALE_SWEEPER_ENABLED is false.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done without modifying any rows.",
    )

    args = parser.parse_args()

    if not _check_enabled(args):
        sys.exit(0)

    if args.once:
        result = sweep_stale_generations_once(dry_run=args.dry_run)
        logger.info("Sweep complete: %s", result)
        return

    if args.loop:
        asyncio.run(_run_loop(args))
        return

    logger.warning("No mode specified (--once or --loop). Use --help for usage.")


if __name__ == "__main__":
    main()
