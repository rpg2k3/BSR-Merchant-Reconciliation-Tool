"""Tests for the XLSX lock-file safety wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.safe_write import XlsxLockError, check_xlsx_lock, lock_path_for


def test_lock_path_for_basic():
    p = Path("/tmp/example/Report.xlsx")
    assert lock_path_for(p) == Path("/tmp/example/.~lock.Report.xlsx#")


def test_check_passes_when_no_lock_file(tmp_path: Path):
    target = tmp_path / "Report.xlsx"
    # Note: target itself doesn't even need to exist — the check is purely
    # about the sibling lock file.
    check_xlsx_lock(target)


def test_check_raises_when_lock_file_present(tmp_path: Path):
    target = tmp_path / "Report.xlsx"
    lock = lock_path_for(target)
    lock.write_text("")
    with pytest.raises(XlsxLockError) as excinfo:
        check_xlsx_lock(target)
    assert "Report.xlsx" in str(excinfo.value)
    assert "close" in str(excinfo.value).lower()
