import os
import time
from pathlib import Path

from app.services.housekeeping import prune_orphaned_workdirs


def test_prune_old_directories_only(tmp_path: Path):
    old = tmp_path / "zvuk_orphan"
    old.mkdir()
    (old / "partial.mp4").write_bytes(b"temporary media")
    new = tmp_path / "zvuk_active"
    new.mkdir()
    other = tmp_path / "unrelated"
    other.mkdir()

    ancient = time.time() - 100_000
    os.utime(old, (ancient, ancient))
    removed = prune_orphaned_workdirs(tmp_path, older_than_seconds=86400)

    assert removed == 1
    assert not old.exists()
    assert new.exists()
    assert other.exists()


def test_prune_ignores_symlinks(tmp_path: Path):
    target = tmp_path / "do_not_delete"
    target.mkdir()
    (target / "important.txt").write_text("kept")
    link = tmp_path / "zvuk_bad_link"
    link.symlink_to(target, target_is_directory=True)
    assert prune_orphaned_workdirs(tmp_path, older_than_seconds=0) == 0
    assert (target / "important.txt").read_text() == "kept"
