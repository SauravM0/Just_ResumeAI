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


def main() -> int:
    deleted_count = delete_expired_files()
    logger.info("Deleted %s expired generated file(s)", deleted_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
