"""Tests for the account registry and folder bootstrap."""

from __future__ import annotations

import importlib
from pathlib import Path

from config import (
    AccountConfig,
    bootstrap_folders,
    load_accounts,
    should_bootstrap,
)


def test_load_accounts_returns_three_entries():
    accounts = load_accounts()
    assert set(accounts) == {"MTN Merchant", "Airtel Merchant", "Petty Cash UGX"}


def test_account_fields_populated():
    accounts = load_accounts()
    mtn = accounts["MTN Merchant"]
    assert isinstance(mtn, AccountConfig)
    assert mtn.karibu_account == "MTN Money"
    assert mtn.statement_parser == "mtn_merchant_csv"
    assert mtn.karibu_parser == "karibu_ledger_csv"
    assert mtn.matching["date_window_days"] == 2
    assert mtn.legacy_folder == "MTN"
    assert mtn.karibu_only_is_normal is False


def test_petty_cash_flagged_karibu_only_normal():
    accounts = load_accounts()
    petty = accounts["Petty Cash UGX"]
    assert petty.karibu_only_is_normal is True
    assert petty.legacy_folder is None
    assert petty.statement_parser == "momo_agent_xlsx"


def test_bootstrap_folders_creates_four_dirs(tmp_path: Path):
    created = bootstrap_folders("Stanbic UGX", tmp_path)
    expected = [
        tmp_path / "Transactions" / "Stanbic UGX",
        tmp_path / "Reports" / "Karibu" / "Stanbic UGX",
        tmp_path / "Statements" / "Stanbic UGX",
        tmp_path / "Reconciliation" / "Stanbic UGX",
    ]
    for path in expected:
        assert path.is_dir(), f"missing: {path}"
    assert set(created) == set(expected)


def test_bootstrap_folders_is_idempotent(tmp_path: Path):
    bootstrap_folders("Petty Cash UGX", tmp_path)
    second = bootstrap_folders("Petty Cash UGX", tmp_path)
    assert second == [], "Second run should create nothing"


def test_should_bootstrap_skips_when_legacy_folder_present(tmp_path: Path):
    accounts = load_accounts()
    mtn = accounts["MTN Merchant"]
    (tmp_path / "Transactions" / "MTN").mkdir(parents=True)
    assert should_bootstrap(mtn, tmp_path) is False


def test_should_bootstrap_runs_when_no_legacy_folder(tmp_path: Path):
    accounts = load_accounts()
    assert should_bootstrap(accounts["Petty Cash UGX"], tmp_path) is True


def test_should_bootstrap_runs_when_legacy_folder_renamed_away(tmp_path: Path):
    accounts = load_accounts()
    mtn = accounts["MTN Merchant"]
    # No Transactions/MTN/ exists in tmp_path — simulates post-Phase-2.
    assert should_bootstrap(mtn, tmp_path) is True


def test_bsr_recon_data_dir_env_override(monkeypatch, tmp_path: Path):
    """`BSR_RECON_DATA_DIR` must override the data dir everywhere (Phase 4.5).

    Set the env var, import the modules fresh, and assert the three canonical
    path definitions all relocate to the override:
      - `core.config.WORKING_DIR`
      - `migrate_layout.DEFAULT_DATA_DIR`  (the new-pipeline source of truth)
      - `app_paths.DATA_DIR`               (re-export the UI drives off)
    Then restore the env var and reload so later tests see the real defaults.
    """
    import app_paths
    import core.config as core_config
    import migrate_layout

    override = tmp_path / "veracrypt_drive" / "BSR_Recon"
    monkeypatch.setenv("BSR_RECON_DATA_DIR", str(override))
    try:
        core_config = importlib.reload(core_config)
        migrate_layout = importlib.reload(migrate_layout)
        app_paths = importlib.reload(app_paths)

        assert core_config.WORKING_DIR == override
        assert migrate_layout.DEFAULT_DATA_DIR == override
        assert app_paths.DATA_DIR == override
        # The override is honoured through the single shared resolver.
        assert core_config.resolve_data_dir(Path("/ignored/default")) == override
        # The pure XDG default is unchanged — override is layered on top of it.
        assert "BSR_Recon" in str(migrate_layout._resolve_default_base())
    finally:
        # Restore: drop the override and reload so module-level paths revert.
        monkeypatch.delenv("BSR_RECON_DATA_DIR", raising=False)
        importlib.reload(core_config)
        importlib.reload(migrate_layout)
        importlib.reload(app_paths)
        assert app_paths.DATA_DIR != override
