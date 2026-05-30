"""Tests for the Phase-3 audit / suppression matrix."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from config import AccountConfig
from reconciler.audit import apply_audit
from reconciler.types import (
    FLAG_DATE_GAP,
    FLAG_DUPLICATE_SAME_DAY,
    FLAG_KARIBU_REPEATED,
    FLAG_LARGE_SINGLE_PAYMENT,
    FLAG_PETTY_CASH_NO_STMT,
    FLAG_UNMATCHED_HIGH_VALUE,
)


def _legacy_mtn() -> AccountConfig:
    return AccountConfig(
        name="MTN Merchant",
        karibu_account="MTN Money",
        statement_parser="mtn_merchant_csv",
        karibu_parser="karibu_ledger_csv",
        matching={"date_window_days": 2, "lumpsum_window_days": 0,
                  "amount_tolerance_ugx": 0.5},
        legacy_folder="MTN",
        karibu_only_is_normal=False,
        match_outflows=False,
    )


def _petty_cash() -> AccountConfig:
    return AccountConfig(
        name="Petty Cash UGX",
        karibu_account="PC - Petty Cash UGX",
        statement_parser="momo_agent_xlsx",
        karibu_parser="karibu_ledger_csv",
        matching={"date_window_days": 2, "lumpsum_window_days": 2,
                  "amount_tolerance_ugx": 0.5},
        karibu_only_is_normal=True,
        match_outflows=True,
    )


def _karibu_unmatched_row(date, dr=600_000, narration="x"):
    return {
        "Date": date, "Account": "MTN Money", "Narration": narration,
        "DR (UGX)": dr, "CR (UGX)": 0, "Balance": "",
        "Status": "Not in Statement",
        "Match Type": "—", "Confidence": "—", "Matched Ref": "—",
        "Audit Flag": "", "Comments": "",
    }


def _stmt_row(date, amount=1000, status="Not in Karibu", direction="IN"):
    return {
        "Date": date, "Transaction ID": "TX",
        "Payer Name": "Alice", "Amount (UGX)": amount,
        "Tx Status": "Successful", "Direction": direction,
        "Status": status, "Match Type": "—",
        "Confidence": "—", "Matched Ref": "—",
        "Audit Flag": "", "Comments": "",
    }


# ---------- Legacy behaviour (no suppression) ----------

def test_legacy_account_high_value_flag_raised():
    karibu = pd.DataFrame([_karibu_unmatched_row(datetime(2026, 5, 10), dr=600_000)])
    stmt = pd.DataFrame()
    k, _ = apply_audit(karibu, stmt, account=_legacy_mtn())
    assert FLAG_UNMATCHED_HIGH_VALUE in k.iloc[0]["Audit Flag"]


def test_legacy_account_large_payment_flag_raised():
    karibu = pd.DataFrame([_karibu_unmatched_row(datetime(2026, 5, 10), dr=2_000_000)])
    stmt = pd.DataFrame()
    k, _ = apply_audit(karibu, stmt, account=_legacy_mtn())
    flags = k.iloc[0]["Audit Flag"]
    assert FLAG_LARGE_SINGLE_PAYMENT in flags
    assert FLAG_UNMATCHED_HIGH_VALUE in flags
    assert FLAG_PETTY_CASH_NO_STMT not in flags


# ---------- Petty Cash UGX suppression ----------

def test_petty_cash_suppresses_unmatched_high_value():
    """Karibu rows with karibu_only_is_normal must NOT carry UNMATCHED_HIGH_VALUE."""
    karibu = pd.DataFrame([_karibu_unmatched_row(datetime(2026, 5, 10), dr=600_000)])
    stmt = pd.DataFrame()
    k, _ = apply_audit(karibu, stmt, account=_petty_cash())
    flags = k.iloc[0]["Audit Flag"]
    assert FLAG_UNMATCHED_HIGH_VALUE not in flags
    assert FLAG_PETTY_CASH_NO_STMT in flags


def test_petty_cash_suppresses_large_single_payment_and_date_gap():
    """LARGE_SINGLE_PAYMENT and DATE_GAP must vanish; soft flag stays."""
    karibu = pd.DataFrame([
        _karibu_unmatched_row(datetime(2026, 5, 1), dr=2_000_000),
        _karibu_unmatched_row(datetime(2026, 5, 15), dr=2_000_000),  # 14-day gap
    ])
    stmt = pd.DataFrame()
    k, _ = apply_audit(karibu, stmt, account=_petty_cash())
    flags_combined = ",".join(k["Audit Flag"].astype(str))
    assert FLAG_LARGE_SINGLE_PAYMENT not in flags_combined
    assert FLAG_DATE_GAP not in flags_combined
    assert k.iloc[0]["Audit Flag"].count(FLAG_PETTY_CASH_NO_STMT) == 1


def test_petty_cash_keeps_repeated_narration_flag():
    """KARIBU_ONLY_REPEATED_NARRATION is NOT suppressed — it's a legitimate
    observation regardless of karibu_only_is_normal."""
    karibu = pd.DataFrame([
        _karibu_unmatched_row(datetime(2026, 5, 1), dr=100, narration="airtime"),
        _karibu_unmatched_row(datetime(2026, 5, 10), dr=100, narration="airtime"),
    ])
    stmt = pd.DataFrame()
    k, _ = apply_audit(karibu, stmt, account=_petty_cash())
    for _, row in k.iterrows():
        assert FLAG_KARIBU_REPEATED in row["Audit Flag"]
        assert FLAG_PETTY_CASH_NO_STMT in row["Audit Flag"]


def test_petty_cash_keeps_duplicate_same_day_flag():
    """Same amount, same day, both unmatched — must keep DUPLICATE flag."""
    karibu = pd.DataFrame([
        _karibu_unmatched_row(datetime(2026, 5, 1), dr=100, narration="a"),
        _karibu_unmatched_row(datetime(2026, 5, 1), dr=100, narration="b"),
    ])
    stmt = pd.DataFrame()
    k, _ = apply_audit(karibu, stmt, account=_petty_cash())
    for _, row in k.iterrows():
        assert FLAG_DUPLICATE_SAME_DAY in row["Audit Flag"]


def test_petty_cash_suppression_applies_to_cr_unmatched_rows():
    """When match_outflows=True, CR-side unmatched rows also get the soft flag
    and have the hard-escalation flags suppressed."""
    cr_row = {
        "Date": datetime(2026, 5, 10), "Account": "PC - Petty Cash UGX",
        "Narration": "x", "DR (UGX)": 0, "CR (UGX)": 1_200_000,
        "Balance": "",
        "Status": "Not in Statement",
        "Match Type": "—", "Confidence": "—", "Matched Ref": "—",
        "Audit Flag": "", "Comments": "",
    }
    karibu = pd.DataFrame([cr_row])
    stmt = pd.DataFrame()
    k, _ = apply_audit(karibu, stmt, account=_petty_cash())
    flags = k.iloc[0]["Audit Flag"]
    assert FLAG_PETTY_CASH_NO_STMT in flags
    assert FLAG_LARGE_SINGLE_PAYMENT not in flags
    assert FLAG_UNMATCHED_HIGH_VALUE not in flags


def test_petty_cash_matched_rows_get_no_soft_flag():
    """Suppression only applies to unmatched Karibu rows. A matched row
    must not carry PETTY_CASH_NO_STATEMENT_EXPECTED."""
    matched = _karibu_unmatched_row(datetime(2026, 5, 10), dr=200_000)
    matched["Status"] = "Matched"
    matched["Confidence"] = "100%"
    karibu = pd.DataFrame([matched])
    stmt = pd.DataFrame()
    k, _ = apply_audit(karibu, stmt, account=_petty_cash())
    assert FLAG_PETTY_CASH_NO_STMT not in k.iloc[0]["Audit Flag"]
