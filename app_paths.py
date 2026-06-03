"""Shared path helpers for the Phase 4 UI and its workers.

The single source of truth for the runtime data directory is
`migrate_layout.DEFAULT_DATA_DIR` — it resolves the XDG path
(`~/.local/share/BSR_Recon/`) regardless of frozen-vs-source, which is the
fork that bit the Phase 2 migration. The UI must drive the new pipeline off
this, NOT `core.config.WORKING_DIR` (which returns the repo root from source).

`DEFAULT_DATA_DIR` honours the `BSR_RECON_DATA_DIR` env-var override (Phase
4.5) via `core.config.resolve_data_dir`, so `DATA_DIR` here automatically
relocates with it (e.g. onto a portable VeraCrypt drive) — no extra wiring.
"""

from __future__ import annotations

import re
from pathlib import Path

from migrate_layout import DEFAULT_DATA_DIR

# Re-export under a UI-facing name.
DATA_DIR: Path = DEFAULT_DATA_DIR

# Statement / Karibu source files the consolidator knows how to parse.
_SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}

_YEAR_RE = re.compile(r"- (\d{4})\.xlsx$")


def transactions_dir(account: str, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "Transactions" / account


def karibu_dir(account: str, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "Reports" / "Karibu" / account


def statements_dir(account: str, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "Statements" / account


def reconciliation_dir(account: str, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "Reconciliation" / account


def logs_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "logs"


def count_source_files(directory: Path) -> int:
    """Count parseable source files in a folder (non-recursive)."""
    if not directory.is_dir():
        return 0
    return sum(
        1 for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES
        and not p.name.startswith(".") and not p.name.startswith("~")
    )


def newest_input_mtime(account: str, data_dir: Path | None = None) -> float | None:
    """Most recent mtime across both input folders, or None if empty."""
    mtimes: list[float] = []
    for d in (transactions_dir(account, data_dir), karibu_dir(account, data_dir)):
        if d.is_dir():
            for p in d.iterdir():
                if (p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES
                        and not p.name.startswith(".") and not p.name.startswith("~")):
                    mtimes.append(p.stat().st_mtime)
    return max(mtimes) if mtimes else None


def newest_workbook_mtime(directory: Path) -> float | None:
    """Most recent mtime across .xlsx files in a folder, or None if empty."""
    if not directory.is_dir():
        return None
    mtimes = [p.stat().st_mtime for p in directory.glob("*.xlsx") if p.is_file()]
    return max(mtimes) if mtimes else None


def available_years(account: str, data_dir: Path | None = None) -> list[int]:
    """Reconcilable years for an account, ascending.

    A year is reconcilable only when BOTH consolidated workbooks exist under
    `Statements/{Account}/` — `{Account} Transactions - {YYYY}.xlsx` AND
    `{Account} Karibu Ledger - {YYYY}.xlsx`. `reconcile_account` reads both, so
    a year with only one (e.g. a stray statement workbook and no Karibu ledger)
    is skipped rather than raising ConsolidatedFileNotFound mid-run.
    """
    sdir = statements_dir(account, data_dir)
    if not sdir.is_dir():
        return []

    def _years(prefix: str) -> set[int]:
        out: set[int] = set()
        for p in sdir.glob(f"{prefix} - *.xlsx"):
            m = _YEAR_RE.search(p.name)
            if m:
                out.add(int(m.group(1)))
        return out

    stmt_years = _years(f"{account} Transactions")
    karibu_years = _years(f"{account} Karibu Ledger")
    return sorted(stmt_years & karibu_years)
