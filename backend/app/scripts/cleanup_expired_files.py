"""Delete expired generated files from Supabase Storage.

Run from the backend directory:
    python -m app.scripts.cleanup_expired_files
"""

from __future__ import annotations

import logging
import sys

from app.services.storage_service import delete_expired_files


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_cleanup() -> int:
    """Run file cleanup and return the number of deleted files.

    Safe to call from the background periodic task in main.py.
    Logs details about each deletion.
    """
    deleted_count = delete_expired_files()
    logger.info("Cleanup complete: deleted %s expired generated file(s)", deleted_count)
    return deleted_count


def main() -> int:
    deleted_count = run_cleanup()
    logger.info("Manual cleanup run: deleted %s expired generated file(s)", deleted_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
