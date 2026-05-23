"""Tests for the migration script."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import migrate_layout
from consolidator import consolidate_account
from migrate_layout import DEFAULT_DATA_DIR, migrate


def _seed_legacy_layout(base: Path) -> None:
    """Mimic the pre-Phase-2 directory shape on disk."""
    (base / "Transactions" / "MTN").mkdir(parents=True)
    (base / "Transactions" / "Airtel").mkdir(parents=True)
    (base / "Reports" / "Karibu" / "MTN").mkdir(parents=True)
    (base / "Reports" / "Karibu" / "Airtel").mkdir(parents=True)
    statements = base / "Statements"
    statements.mkdir(parents=True)
    (statements / "BSR_MTN_Merchant_Transactions.xlsx").write_text("placeholder")
    (statements / "BSR_Airtel_Merchant_Transactions.xlsx").write_text("placeholder")
    (base / "Backups").mkdir()
    (base / "Backups" / ".gitkeep").write_text("")


def test_migration_renames_folders_and_preserves_flat_files(tmp_path: Path):
    _seed_legacy_layout(tmp_path)

    actions = migrate(tmp_path, run_consolidator=False, log=lambda *_: None)

    # Folder renames.
    for top in ["Transactions", "Reports/Karibu"]:
        for legacy, display in [("MTN", "MTN Merchant"), ("Airtel", "Airtel Merchant")]:
            assert not (tmp_path / top / legacy).exists(), f"{top}/{legacy} should have been renamed"
            assert (tmp_path / top / display).is_dir(), f"{top}/{display} missing"

    # Flat files preserved with _pre_migration suffix.
    stmts = tmp_path / "Statements"
    assert not (stmts / "BSR_MTN_Merchant_Transactions.xlsx").exists()
    assert (stmts / "BSR_MTN_Merchant_Transactions_pre_migration.xlsx").exists()
    assert not (stmts / "BSR_Airtel_Merchant_Transactions.xlsx").exists()
    assert (stmts / "BSR_Airtel_Merchant_Transactions_pre_migration.xlsx").exists()

    # Backups/ was empty (only .gitkeep) → removed.
    assert not (tmp_path / "Backups").exists()

    assert len(actions["renamed_folders"]) == 4  # 2 tops × 2 accounts
    assert len(actions["preserved_flat_files"]) == 2
    assert actions["backups_removed"] is True


def test_migration_is_idempotent(tmp_path: Path):
    _seed_legacy_layout(tmp_path)

    actions1 = migrate(tmp_path, run_consolidator=False, log=lambda *_: None)
    # Second run should be a complete no-op.
    actions2 = migrate(tmp_path, run_consolidator=False, log=lambda *_: None)

    assert actions1["renamed_folders"], "First run should have renamed folders"
    assert actions2["renamed_folders"] == [], "Second run must not re-rename"
    assert actions2["preserved_flat_files"] == []
    assert actions2["bootstrapped_accounts"] == [], "Folders already exist from first run"


def test_migration_skips_when_both_legacy_and_target_exist(tmp_path: Path):
    """Safety: if both Transactions/MTN/ AND Transactions/MTN Merchant/
    exist, do NOT silently merge — surface for manual resolution."""
    _seed_legacy_layout(tmp_path)
    (tmp_path / "Transactions" / "MTN Merchant").mkdir()

    actions = migrate(tmp_path, run_consolidator=False, log=lambda *_: None)
    # The legacy MTN folder must still exist (not touched).
    assert (tmp_path / "Transactions" / "MTN").is_dir()
    assert any("merge manually" in s for s in actions["skipped"]), \
        f"Expected a 'merge manually' message in skipped list; got {actions['skipped']}"


def test_migration_keeps_nonempty_backups(tmp_path: Path):
    """If Backups/ has anything other than .gitkeep, leave it alone."""
    _seed_legacy_layout(tmp_path)
    (tmp_path / "Backups" / "BSR_MTN_Reconciliation_old.xlsx").write_text("real")

    actions = migrate(tmp_path, run_consolidator=False, log=lambda *_: None)
    assert (tmp_path / "Backups").is_dir(), "Non-empty Backups/ must be preserved"
    assert actions["backups_removed"] is False
    assert any("not empty" in s for s in actions["skipped"])


# ---- Regression: hotfix for the "migration targeted repo root" incident ----

def test_default_data_dir_is_xdg(monkeypatch, tmp_path: Path):
    """`DEFAULT_DATA_DIR` (and `_resolve_default_base()`) must resolve to
    `$XDG_DATA_HOME/BSR_Recon` — or `~/.local/share/BSR_Recon/` when
    `XDG_DATA_HOME` is unset. Never to the repo root.
    """
    # When XDG_DATA_HOME is unset, default falls back to ~/.local/share.
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    expected = Path.home() / ".local" / "share" / "BSR_Recon"
    assert migrate_layout._resolve_default_base() == expected

    # When XDG_DATA_HOME is set, it must be honoured.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert migrate_layout._resolve_default_base() == tmp_path / "xdg" / "BSR_Recon"


def test_migration_does_not_import_working_dir():
    """The migration module must NOT depend on `core.config.WORKING_DIR`,
    which has a frozen-vs-source fork that returns the repo root when
    running from source. This was the bug that made the first migration
    target the wrong directory."""
    # Comments and docstrings may still reference the name for context;
    # what matters is that the symbol is not actually bound at runtime.
    assert not hasattr(migrate_layout, "WORKING_DIR"), (
        "migrate_layout must not import core.config.WORKING_DIR — "
        "use DEFAULT_DATA_DIR (XDG-resolved) or the explicit base_dir arg."
    )


def test_migrate_uses_explicit_base_dir_not_xdg(tmp_path: Path, monkeypatch):
    """`migrate(tmp_path, ...)` must operate strictly inside tmp_path and
    must never write to or read from XDG."""
    _seed_legacy_layout(tmp_path)

    # Make XDG_DATA_HOME point somewhere we control, and assert nothing
    # under it gets created.
    xdg = tmp_path / "should_not_be_touched_xdg"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))

    migrate(tmp_path, run_consolidator=False, log=lambda *_: None)

    assert not xdg.exists(), "migrate must not touch XDG when given an explicit base_dir"


def test_consolidate_account_requires_base_dir():
    """`consolidate_account` must require `base_dir` to be passed
    explicitly — no fallback to a module-level constant."""
    sig = inspect.signature(consolidate_account)
    assert "base_dir" in sig.parameters, "consolidate_account must accept base_dir"
    param = sig.parameters["base_dir"]
    assert param.default is inspect.Parameter.empty, (
        "base_dir must have no default — every caller must pass the path "
        "explicitly so the migration can't silently target the wrong tree."
    )
