"""Shared types and constants for the reconciler package.

`ReconKnobs` carries the per-account matching parameters resolved from
`accounts.yaml.matching`. `ReconResult` is the run summary returned by
`reconcile_account()`.

The flag-name constants are duplicated verbatim from `core/anomalies.py`
on purpose — downstream tooling (the AI analyst, Phase 4 UI badges)
grep for these exact strings and renaming them would silently break the
contract. The new `PETTY_CASH_NO_STATEMENT_EXPECTED` flag is the only
addition for Phase 3.

`SUPPRESSED_ON_KARIBU_ONLY` lists the hard-escalation flags that get
removed from unmatched Karibu rows on accounts where `karibu_only_is_normal=True`
(currently Petty Cash UGX). Pure-cash petty-cash moves leaving Karibu
without a statement counterpart is expected — escalating each one as
UNMATCHED_HIGH_VALUE / LARGE_SINGLE_PAYMENT / DATE_GAP would drown the
report in noise. The soft `PETTY_CASH_NO_STATEMENT_EXPECTED` flag
replaces them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Status values written into the output workbooks. Match the legacy MTN
# reconciliation sample exactly — downstream code in core/anomalies and the
# AI analyst greps for these literal strings.
# ---------------------------------------------------------------------------
STATUS_MATCHED = "Matched"
STATUS_NOT_IN_STATEMENT = "Not in Statement"
STATUS_NOT_IN_KARIBU = "Not in Karibu"
STATUS_CONTRA = "Contra"

# ---------------------------------------------------------------------------
# Audit flag names. Verbatim from core/anomalies.py — do not rename.
# ---------------------------------------------------------------------------
FLAG_UNMATCHED_HIGH_VALUE = "UNMATCHED_HIGH_VALUE"
FLAG_LARGE_SINGLE_PAYMENT = "LARGE_SINGLE_PAYMENT"
FLAG_DATE_GAP = "DATE_GAP"
FLAG_DUPLICATE_SAME_DAY = "DUPLICATE_AMOUNT_SAME_DAY"
FLAG_KARIBU_REPEATED = "KARIBU_ONLY_REPEATED_NARRATION"
FLAG_LOW_CONFIDENCE = "LOW_CONFIDENCE_MATCH"
FLAG_STMT_PAYER_FREQ = "STMT_PAYER_HIGH_FREQUENCY"
FLAG_CONTRA_NOT_IN_KARIBU = "CONTRA_NOT_IN_KARIBU"
FLAG_PETTY_CASH_NO_STMT = "PETTY_CASH_NO_STATEMENT_EXPECTED"

# Flags removed from unmatched Karibu rows on `karibu_only_is_normal` accounts.
SUPPRESSED_ON_KARIBU_ONLY = frozenset({
    FLAG_UNMATCHED_HIGH_VALUE,
    FLAG_LARGE_SINGLE_PAYMENT,
    FLAG_DATE_GAP,
})


@dataclass(frozen=True)
class ReconKnobs:
    """Matching knobs resolved from accounts.yaml.matching.

    `date_window_days` widens the exact-match passes (Pass 3) AND the K→S
    lumpsum widening pass (Pass 5). `lumpsum_window_days` is intentionally
    separate so the S→K lumpsum pass (Pass 6) can stay at 0 for MTN/Airtel
    (legacy behaviour) while opening up for Petty Cash (window of 2 days).
    `amount_tolerance_ugx` defaults to 0.5 to match legacy rounding — never
    set to exactly 0 unless inputs are pre-rounded to integer UGX.
    """

    date_window_days: int = 2
    lumpsum_window_days: int = 0
    amount_tolerance_ugx: float = 0.5

    @classmethod
    def from_account(cls, matching: dict) -> "ReconKnobs":
        return cls(
            date_window_days=int(matching.get("date_window_days", 2)),
            lumpsum_window_days=int(matching.get("lumpsum_window_days", 0)),
            amount_tolerance_ugx=float(matching.get("amount_tolerance_ugx", 0.5)),
        )


@dataclass
class ReconResult:
    """Summary returned by `reconcile_account()`."""

    account: str
    year: int
    output_path: Path
    karibu_rows: int
    stmt_rows: int
    matched: int
    not_in_statement: int
    not_in_karibu: int
    # Bidirectional splits (populated when match_outflows=True; otherwise the
    # `_out` fields stay at 0 and the totals above describe DR↔IN only).
    matched_in: int = 0
    matched_out: int = 0
    not_in_statement_in: int = 0
    not_in_statement_out: int = 0
    not_in_karibu_in: int = 0
    not_in_karibu_out: int = 0
    flag_counts: dict[str, int] = field(default_factory=dict)
    unparseable_dates: int = 0
