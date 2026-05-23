#!/usr/bin/env python3
"""One-shot migration to the per-account folder layout.

Run after Phase 2 ships, once per machine:

    python3 migrate_layout.py

It does, in order:

1. Renames legacy short-name input folders to display-name folders:
     Transactions/MTN/         → Transactions/MTN Merchant/
     Transactions/Airtel/      → Transactions/Airtel Merchant/
     Reports/Karibu/MTN/       → Reports/Karibu/MTN Merchant/
     Reports/Karibu/Airtel/    → Reports/Karibu/Airtel Merchant/

2. Preserves the flat consolidated workbooks as `_pre_migration` files for
   reference / diff (the legacy Airtel one is NaT-poisoned — see BUGFIX.md
   — and the new per-year workbooks supersede it):
     Statements/BSR_MTN_Merchant_Transactions.xlsx → ..._pre_migration.xlsx
     Statements/BSR_Airtel_Merchant_Transactions.xlsx → ..._pre_migration.xlsx

3. Calls `bootstrap_folders` for the renamed accounts so the four runtime
   folders exist with the display-name convention.

4. Runs the Phase 2 consolidator on every account in accounts.yaml. The
   output lands in Statements/{Account}/{Account} Transactions - {YYYY}.xlsx
   and Statements/{Account}/{Account} Karibu Ledger - {YYYY}.xlsx. (For
   Airtel this is where the 32 broken rows in the legacy flat xlsx are
   recovered with their correct dates from the source CSVs.)

5. Removes the now-empty `~/.local/share/BSR_Recon/Backups/` directory if
   nothing else is in it.

The script is idempotent: re-running after a successful migration is a
no-op for every step. If a step has already happened (folder already
renamed, flat file already preserved, etc.) it is reported and skipped.

The script never deletes user data. The only delete is the empty
`Backups/` dir, and only if it's empty.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the repo importable when running as `python migrate_layout.py` from
# any cwd.
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import bootstrap_folders, load_accounts
from consolidator import consolidate_account


# Canonical runtime data directory per BUILD_PLAN §5. We resolve it here
# explicitly — NOT via core.config.WORKING_DIR — because WORKING_DIR has a
# frozen-vs-source fork that returns the repo root when running from
# source. The migration is a one-shot on the user's live data, so it must
# always target the XDG dir regardless of how it's invoked.
def _resolve_default_base() -> Path:
    return Path(os.environ.get(
        "XDG_DATA_HOME", Path.home() / ".local" / "share"
    )) / "BSR_Recon"


DEFAULT_DATA_DIR = _resolve_default_base()


# (legacy_folder, display_name) under each top-level folder.
_FOLDER_RENAMES_TOP = [
    "Transactions",
    "Reports/Karibu",
]

_FLAT_STATEMENT_FILES = {
    "MTN Merchant": "BSR_MTN_Merchant_Transactions.xlsx",
    "Airtel Merchant": "BSR_Airtel_Merchant_Transactions.xlsx",
}


def migrate(base_dir: Path | None = None, *, run_consolidator: bool = True,
            log=print) -> dict:
    """Run the migration. Returns a small dict of stats / actions taken.

    `base_dir` is required to be the canonical XDG data directory in
    production use; pass an explicit path in tests. If omitted, falls
    back to `DEFAULT_DATA_DIR` (resolved at import time, never
    `core.config.WORKING_DIR`).

    `run_consolidator=False` skips step 4; useful for tests that don't
    want a heavy operation in tmp_path.
    """
    base = Path(base_dir) if base_dir else DEFAULT_DATA_DIR
    actions: dict[str, list[str]] = {
        "renamed_folders": [],
        "preserved_flat_files": [],
        "bootstrapped_accounts": [],
        "consolidated_accounts": [],
        "backups_removed": False,
        "skipped": [],
    }

    accounts = load_accounts()

    # ---- 1. Rename legacy short-name folders ----
    for account in accounts.values():
        legacy = account.legacy_folder
        if not legacy:
            continue
        for top in _FOLDER_RENAMES_TOP:
            legacy_path = base / top / legacy
            target_path = base / top / account.name
            if legacy_path.is_dir() and not target_path.exists():
                legacy_path.rename(target_path)
                msg = f"Renamed: {legacy_path.relative_to(base)} → {target_path.relative_to(base)}"
                log(msg)
                actions["renamed_folders"].append(msg)
            elif legacy_path.is_dir() and target_path.exists():
                msg = (
                    f"BOTH {legacy_path.relative_to(base)} AND "
                    f"{target_path.relative_to(base)} exist — please merge manually."
                )
                log(f"  ! {msg}")
                actions["skipped"].append(msg)
            elif target_path.is_dir():
                actions["skipped"].append(f"already renamed: {top}/{legacy} → {top}/{account.name}")

    # ---- 2. Preserve flat consolidated workbooks as *_pre_migration ----
    statements_dir = base / "Statements"
    for account_name, flat_filename in _FLAT_STATEMENT_FILES.items():
        src = statements_dir / flat_filename
        if not src.exists():
            continue
        dst = statements_dir / flat_filename.replace(".xlsx", "_pre_migration.xlsx")
        if dst.exists():
            actions["skipped"].append(f"flat file already preserved: {dst.name}")
            continue
        src.rename(dst)
        msg = f"Preserved: {src.name} → {dst.name}"
        log(msg)
        actions["preserved_flat_files"].append(msg)

    # ---- 3. Bootstrap renamed accounts ----
    for account in accounts.values():
        created = bootstrap_folders(account.name, base)
        if created:
            msg = f"Bootstrapped {account.name}: {len(created)} folder(s) created"
            log(msg)
            actions["bootstrapped_accounts"].append(account.name)

    # ---- 4. Run consolidator for every account ----
    if run_consolidator:
        for account in accounts.values():
            try:
                result = consolidate_account(account, base)
            except Exception as exc:
                log(f"  ! consolidator failed for {account.name}: {exc}")
                continue
            n_stmt = len(result.statement_workbooks_written)
            n_kar = len(result.karibu_workbooks_written)
            msg = (
                f"Consolidated {account.name}: "
                f"{result.statement_records_unique} statement / "
                f"{result.karibu_records_unique} Karibu records → "
                f"{n_stmt} statement xlsx, {n_kar} Karibu xlsx"
            )
            log(msg)
            if result.statement_unparseable and result.latest_statement_workbook:
                rel = result.latest_statement_workbook.relative_to(base)
                log(
                    f"  Unparseable dates: {result.statement_unparseable} rows — "
                    f"see {rel}, Unparseable sheet."
                )
            if result.karibu_unparseable and result.latest_karibu_workbook:
                rel = result.latest_karibu_workbook.relative_to(base)
                log(
                    f"  Unparseable dates: {result.karibu_unparseable} rows — "
                    f"see {rel}, Unparseable sheet."
                )
            actions["consolidated_accounts"].append(account.name)

    # ---- 5. Remove empty Backups/ ----
    backups = base / "Backups"
    if backups.is_dir():
        non_meta = [p for p in backups.iterdir()
                    if p.name not in (".gitkeep",)]
        if not non_meta:
            # Remove the .gitkeep and the dir itself.
            for meta in backups.iterdir():
                meta.unlink()
            backups.rmdir()
            log(f"Removed empty {backups.relative_to(base)}/")
            actions["backups_removed"] = True
        else:
            actions["skipped"].append(
                f"Backups/ not empty — {len(non_meta)} files left, kept dir for user review"
            )

    return actions


def main(argv: list[str] | None = None, *, base_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot BSR_Recon layout migration.")
    parser.add_argument(
        "--base", type=Path, default=None,
        help=f"Data directory to migrate (default: {DEFAULT_DATA_DIR}).",
    )
    args = parser.parse_args(argv)
    resolved = base_dir or args.base or DEFAULT_DATA_DIR

    print(f"BSR_Recon migration — base: {resolved}")
    if not resolved.exists():
        print(f"  ! Base directory does not exist: {resolved}")
        print(f"  ! Create it first, or pass --base <path> to target a different directory.")
        return 2
    actions = migrate(resolved)
    print()
    print("Summary:")
    print(f"  Folders renamed:       {len(actions['renamed_folders'])}")
    print(f"  Flat files preserved:  {len(actions['preserved_flat_files'])}")
    print(f"  Accounts bootstrapped: {len(actions['bootstrapped_accounts'])}")
    print(f"  Accounts consolidated: {len(actions['consolidated_accounts'])}")
    print(f"  Backups/ removed:      {actions['backups_removed']}")
    if actions["skipped"]:
        print(f"  Skipped: {len(actions['skipped'])} (already-migrated state)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
