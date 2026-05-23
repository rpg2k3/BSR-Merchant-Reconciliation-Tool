"""Lock-file safety wrapper for XLSX writes.

LibreOffice/Excel hold an exclusive lock on an open workbook via a
sibling file named `.~lock.<filename>#`. Writing over an open workbook
either fails outright or, worse, silently produces a stale read on next
open. This module guards against that.

Use `check_xlsx_lock(path)` before any `wb.save(path)` call. If a lock
file is present, it raises `XlsxLockError` with a message naming the
file so the user knows exactly what to close.
"""

from __future__ import annotations

from pathlib import Path


class XlsxLockError(RuntimeError):
    """Raised when an XLSX target is locked by another application."""


def lock_path_for(xlsx_path: Path) -> Path:
    """Return the LibreOffice/Excel lock-file path for `xlsx_path`."""
    p = Path(xlsx_path)
    return p.parent / f".~lock.{p.name}#"


def check_xlsx_lock(xlsx_path: Path) -> None:
    """Raise XlsxLockError if `xlsx_path` is currently held open elsewhere.

    The check is purely filesystem-based: a sibling `.~lock.<name>#` file
    presence is taken as "open in another application". This matches how
    LibreOffice signals locks and how the spec calls for it.
    """
    lock = lock_path_for(xlsx_path)
    if lock.exists():
        raise XlsxLockError(
            f"File is open in another application — close "
            f"{Path(xlsx_path).name} and re-run."
        )
