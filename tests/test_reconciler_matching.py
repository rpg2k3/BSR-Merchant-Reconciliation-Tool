"""Tests for the 7-pass matching engine.

These run on tiny hand-built DataFrames so behaviour can be reasoned
about row-by-row. Live parity against the legacy `core.reconciler` is
covered separately in `test_reconciler_mtn_parity.py`.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from reconciler.matching import (
    _greedy_subset_sum,
    run_matching,
)
from reconciler.types import ReconKnobs


def _karibu(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _stmt(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_pass1_same_day_exact_yields_100pct():
    karibu = _karibu([{"Date": datetime(2026, 5, 10), "DR": 1000, "CR": 0}])
    stmt = _stmt([{"Date": datetime(2026, 5, 10),
                   "Amount (UGX)": 1000, "Direction": "IN",
                   "Transaction ID": "TX-1"}])
    k_res, s_res = run_matching(karibu, stmt, ReconKnobs())
    assert k_res.iloc[0]["Status"] == "Matched"
    assert k_res.iloc[0]["Confidence"] == "100%"
    assert k_res.iloc[0]["Match Type"] == "Exact"
    assert s_res.iloc[0]["Matched Ref"] == "K0"


def test_pass2_one_day_drift_yields_90pct():
    karibu = _karibu([{"Date": datetime(2026, 5, 10), "DR": 1000, "CR": 0}])
    stmt = _stmt([{"Date": datetime(2026, 5, 11),
                   "Amount (UGX)": 1000, "Direction": "IN",
                   "Transaction ID": "TX-1"}])
    k_res, _ = run_matching(karibu, stmt, ReconKnobs())
    assert k_res.iloc[0]["Confidence"] == "90%"


def test_pass3_two_day_drift_yields_80pct():
    karibu = _karibu([{"Date": datetime(2026, 5, 10), "DR": 1000, "CR": 0}])
    stmt = _stmt([{"Date": datetime(2026, 5, 12),
                   "Amount (UGX)": 1000, "Direction": "IN",
                   "Transaction ID": "TX-1"}])
    k_res, _ = run_matching(karibu, stmt, ReconKnobs())
    assert k_res.iloc[0]["Confidence"] == "80%"


def test_lumpsum_k_to_s_combines_two_stmt_rows():
    """One Karibu DR of 3000 matches two same-day statement rows of 1000+2000."""
    karibu = _karibu([{"Date": datetime(2026, 5, 10), "DR": 3000, "CR": 0}])
    stmt = _stmt([
        {"Date": datetime(2026, 5, 10), "Amount (UGX)": 1000,
         "Direction": "IN", "Transaction ID": "A"},
        {"Date": datetime(2026, 5, 10), "Amount (UGX)": 2000,
         "Direction": "IN", "Transaction ID": "B"},
    ])
    k_res, s_res = run_matching(karibu, stmt, ReconKnobs())
    assert k_res.iloc[0]["Match Type"] == "Lumpsum"
    assert k_res.iloc[0]["Confidence"] == "60%"
    assert s_res["Status"].tolist() == ["Matched", "Matched"]


def test_lumpsum_s_to_k_respects_lumpsum_window_days():
    """One stmt row of 3000 across two Karibu DRs on different days inside lumpsum_window_days."""
    karibu = _karibu([
        {"Date": datetime(2026, 5, 10), "DR": 1000, "CR": 0},
        {"Date": datetime(2026, 5, 12), "DR": 2000, "CR": 0},
    ])
    stmt = _stmt([{"Date": datetime(2026, 5, 11), "Amount (UGX)": 3000,
                   "Direction": "IN", "Transaction ID": "BIG"}])
    # With lumpsum_window_days=0 (legacy MTN), the two Karibu rows are
    # outside the same-day window → no match. With lumpsum_window_days=2
    # (Petty Cash), the match is found.
    k0, s0 = run_matching(karibu, stmt, ReconKnobs(lumpsum_window_days=0))
    assert (k0["Status"] == "Not in Statement").all()

    k2, s2 = run_matching(karibu, stmt, ReconKnobs(lumpsum_window_days=2))
    assert (k2["Status"] == "Matched").all()
    assert s2.iloc[0]["Status"] == "Matched"


def test_pass7_amount_only_with_far_apart_dates():
    """Same amount, 30 days apart → amount-only match at 40%."""
    karibu = _karibu([{"Date": datetime(2026, 1, 1), "DR": 1000, "CR": 0}])
    stmt = _stmt([{"Date": datetime(2026, 5, 1), "Amount (UGX)": 1000,
                   "Direction": "IN", "Transaction ID": "X"}])
    k_res, _ = run_matching(karibu, stmt, ReconKnobs())
    assert k_res.iloc[0]["Confidence"] == "40%"
    assert k_res.iloc[0]["Match Type"] == "Amount Only"


def test_match_outflows_false_ignores_cr_side():
    """Legacy MTN/Airtel: CR rows never match against OUT statement rows."""
    karibu = _karibu([{"Date": datetime(2026, 5, 10), "DR": 0, "CR": 1000}])
    stmt = _stmt([{"Date": datetime(2026, 5, 10), "Amount (UGX)": 1000,
                   "Direction": "OUT", "Transaction ID": "X"}])
    k_res, s_res = run_matching(karibu, stmt, ReconKnobs(),
                                 match_outflows=False)
    # CR row passes through; matching engine never touched it.
    assert k_res.iloc[0]["Status"] == "Not in Statement"
    assert s_res.iloc[0]["Status"] == "Not in Karibu"


def test_match_outflows_true_matches_cr_with_out():
    """Petty Cash: Karibu CR matches statement OUT row."""
    karibu = _karibu([{"Date": datetime(2026, 5, 10), "DR": 0, "CR": 1000}])
    stmt = _stmt([{"Date": datetime(2026, 5, 10), "Amount (UGX)": 1000,
                   "Direction": "OUT", "Transaction ID": "X"}])
    k_res, s_res = run_matching(karibu, stmt, ReconKnobs(),
                                 match_outflows=True)
    assert k_res.iloc[0]["Status"] == "Matched"
    assert s_res.iloc[0]["Status"] == "Matched"


def test_match_outflows_true_keeps_dr_in_pipeline_too():
    """Bidirectional accounts must STILL match DR↔IN."""
    karibu = _karibu([
        {"Date": datetime(2026, 5, 10), "DR": 1000, "CR": 0},
        {"Date": datetime(2026, 5, 10), "DR": 0, "CR": 500},
    ])
    stmt = _stmt([
        {"Date": datetime(2026, 5, 10), "Amount (UGX)": 1000,
         "Direction": "IN", "Transaction ID": "IN-1"},
        {"Date": datetime(2026, 5, 10), "Amount (UGX)": 500,
         "Direction": "OUT", "Transaction ID": "OUT-1"},
    ])
    k_res, s_res = run_matching(karibu, stmt, ReconKnobs(), match_outflows=True)
    assert (k_res["Status"] == "Matched").all()
    assert (s_res["Status"] == "Matched").all()


def test_amount_tolerance_lets_half_ugx_drift_through():
    """0.5 UGX tolerance — legacy rounding semantics."""
    karibu = _karibu([{"Date": datetime(2026, 5, 10), "DR": 1000.3, "CR": 0}])
    stmt = _stmt([{"Date": datetime(2026, 5, 10),
                   "Amount (UGX)": 1000.0, "Direction": "IN",
                   "Transaction ID": "X"}])
    k_res, _ = run_matching(karibu, stmt, ReconKnobs(amount_tolerance_ugx=0.5))
    assert k_res.iloc[0]["Status"] == "Matched"


def test_locked_row_not_reclaimed_by_later_pass():
    """Once a Karibu row is matched at 100%, pass 7 doesn't steal it."""
    karibu = _karibu([{"Date": datetime(2026, 5, 10), "DR": 1000, "CR": 0}])
    stmt = _stmt([
        {"Date": datetime(2026, 5, 10), "Amount (UGX)": 1000,
         "Direction": "IN", "Transaction ID": "GOOD"},
        # A second statement row with the same amount on a far-away date —
        # would match in pass 7 if the locked row weren't honoured.
        {"Date": datetime(2026, 8, 1), "Amount (UGX)": 1000,
         "Direction": "IN", "Transaction ID": "BAD"},
    ])
    k_res, s_res = run_matching(karibu, stmt, ReconKnobs())
    assert k_res.iloc[0]["Confidence"] == "100%"
    assert s_res.iloc[0]["Status"] == "Matched"  # GOOD
    assert s_res.iloc[1]["Status"] == "Not in Karibu"  # BAD


# ---------- subset-sum helper ----------

def test_subset_sum_single_hit():
    res = _greedy_subset_sum([(0, 1000.0), (1, 500.0)], target=1000.0, tolerance=0.5)
    assert res == [(0, 1000.0)]


def test_subset_sum_two_member_combo():
    res = _greedy_subset_sum([(0, 700.0), (1, 300.0), (2, 50.0)], target=1000.0, tolerance=0.5)
    assert res is not None
    assert sum(amt for _, amt in res) == pytest.approx(1000.0)


def test_subset_sum_no_match_returns_none():
    res = _greedy_subset_sum([(0, 333.0), (1, 444.0)], target=1000.0, tolerance=0.5)
    assert res is None


def test_subset_sum_empty_candidates():
    assert _greedy_subset_sum([], target=1.0, tolerance=0.5) is None
