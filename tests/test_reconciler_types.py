"""Tests for the reconciler dataclasses + flag constants."""

from __future__ import annotations

from pathlib import Path

from reconciler.types import (
    FLAG_DATE_GAP,
    FLAG_LARGE_SINGLE_PAYMENT,
    FLAG_PETTY_CASH_NO_STMT,
    FLAG_UNMATCHED_HIGH_VALUE,
    ReconKnobs,
    ReconResult,
    SUPPRESSED_ON_KARIBU_ONLY,
)


def test_recon_knobs_defaults():
    k = ReconKnobs()
    assert k.date_window_days == 2
    assert k.lumpsum_window_days == 0
    assert k.amount_tolerance_ugx == 0.5


def test_recon_knobs_from_account_strict_types():
    """from_account must coerce string YAML scalars into the right types
    so a hand-edited YAML never bombs the matcher with a TypeError."""
    k = ReconKnobs.from_account(
        {"date_window_days": "3", "lumpsum_window_days": "2",
         "amount_tolerance_ugx": "0.5"}
    )
    assert k.date_window_days == 3
    assert k.lumpsum_window_days == 2
    assert k.amount_tolerance_ugx == 0.5


def test_suppression_matrix_matches_phase3_spec():
    """The three hard-escalation flags from core/anomalies.py must be in
    SUPPRESSED_ON_KARIBU_ONLY; the soft observational flags (DUPLICATE,
    KARIBU_ONLY_REPEATED_NARRATION) must NOT be."""
    assert FLAG_UNMATCHED_HIGH_VALUE in SUPPRESSED_ON_KARIBU_ONLY
    assert FLAG_LARGE_SINGLE_PAYMENT in SUPPRESSED_ON_KARIBU_ONLY
    assert FLAG_DATE_GAP in SUPPRESSED_ON_KARIBU_ONLY
    assert "DUPLICATE_AMOUNT_SAME_DAY" not in SUPPRESSED_ON_KARIBU_ONLY
    assert "KARIBU_ONLY_REPEATED_NARRATION" not in SUPPRESSED_ON_KARIBU_ONLY


def test_petty_cash_flag_name_is_verbatim():
    """Downstream tools grep for the literal string — pin it."""
    assert FLAG_PETTY_CASH_NO_STMT == "PETTY_CASH_NO_STATEMENT_EXPECTED"


def test_recon_result_defaults_zero_for_direction_splits():
    r = ReconResult(
        account="X", year=2026, output_path=Path("/tmp/x.xlsx"),
        karibu_rows=10, stmt_rows=10,
        matched=5, not_in_statement=3, not_in_karibu=2,
    )
    assert r.matched_in == 0
    assert r.matched_out == 0
    assert r.flag_counts == {}
