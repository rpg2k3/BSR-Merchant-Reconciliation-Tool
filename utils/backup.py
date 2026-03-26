"""Backup management for BSR Reconciliation Tool.

Creates timestamped backups before any write operation.
Keeps only the last 10 backups per file.
"""

import shutil
from datetime import datetime
from pathlib import Path


def create_backup(file_path: Path, backup_dir: Path) -> str | None:
    """Backup file_path into backup_dir with timestamp suffix.

    Returns the backup path string, or None if source doesn't exist.
    """
    if not file_path.exists():
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = file_path.stem
    suffix = file_path.suffix
    backup_name = f"{stem}_{timestamp}{suffix}"
    backup_path = backup_dir / backup_name
    shutil.copy2(file_path, backup_path)

    _prune_old_backups(backup_dir, stem, suffix, keep=10)
    return str(backup_path)


def _prune_old_backups(backup_dir: Path, stem: str, suffix: str, keep: int = 10):
    """Keep only the most recent `keep` backups for a given file."""
    pattern = f"{stem}_*{suffix}"
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    while len(backups) > keep:
        oldest = backups.pop(0)
        oldest.unlink()
