"""Tests for the account registry and folder bootstrap."""

from __future__ import annotations

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
