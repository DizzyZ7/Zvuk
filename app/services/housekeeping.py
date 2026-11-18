"""Cleanup orphaned temporary directories after crashes or forced restarts."""
import logging
import shutil
import time
from pathlib import Path

log = logging.getLogger(__name__)


def prune_orphaned_workdirs(root: Path, *, older_than_seconds: int = 86400) -> int:
    """Delete only old zvuk_* directories; never follow symlinks or touch other files."""
    now = time.time()
    removed = 0
    for directory in root.glob("zvuk_*"):
        try:
            if directory.is_symlink() or not directory.is_dir():
                continue
            if now - directory.stat().st_mtime < older_than_seconds:
                continue
            shutil.rmtree(directory)
            removed += 1
        except OSError:
            log.exception("Failed to remove stale work directory %s", directory)
    return removed
