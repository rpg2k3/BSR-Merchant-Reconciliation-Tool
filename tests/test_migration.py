"""Tests for the migration script."""

from __future__ import annotations

from pathlib import Path

from migrate_layout import migrate


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
