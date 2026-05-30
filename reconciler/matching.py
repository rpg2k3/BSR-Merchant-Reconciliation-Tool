"""7-pass matching engine — plain-English summary.

The engine consumes a Karibu DataFrame and a statement DataFrame, both
already filtered to the rows we care about for one direction. Every pass
walks each unmatched Karibu row and tries to claim an unmatched statement
row according to the pass's rule. Once a Karibu↔statement pair matches,
both rows are locked and skipped by every later pass — so confidence
falls monotonically with pass number.

Pass-by-pass:

  1. Same-day exact   — amount within tolerance AND same calendar date           → 100% Exact
  2. ±1-day exact     — amount within tolerance AND date diff ≤ 1 day            → 90%  Exact
  3. ±N-day exact     — amount within tolerance AND date diff ≤ date_window_days → 80%  Exact
                        (with extra widening passes if date_window_days > 2,
                        confidence dropping 10% per extra day to a floor of 70%)
  4. Same-day lumpsum K→S — one Karibu row = sum of N unmatched statement rows  → 60%  Lumpsum
                            on the SAME date (subset-sum within tolerance)
  5. Wider lumpsum K→S    — same as 4 but inside ±date_window_days              → 45%  Lumpsum
  6. Lumpsum S→K          — one statement row = sum of N unmatched Karibu rows  → 55%  Lumpsum
                            inside ±lumpsum_window_days (0 = same-day only;
                            asymmetric vs Pass 5 by design — legacy MTN
                            behaviour required this)
  7. Amount only          — amount within tolerance, ANY date difference         → 40%  Amount Only

Outflow handling: by default the engine only matches Karibu DR rows
against statement IN rows (the legacy MTN/Airtel behaviour). When the
account sets `match_outflows: true` (Petty Cash UGX), the same 7 passes
are run a SECOND time over (Karibu CR rows ↔ statement OUT rows), with
the locked-row state kept independent between the two directions.

The subset-sum used by passes 4–6 is greedy with an exhaustive fallback
on small combinations (≤ 5 items from the top 15 candidates) — identical
to the legacy implementation so MTN/Airtel results stay byte-for-byte
comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from reconciler.types import (
    STATUS_MATCHED,
    STATUS_NOT_IN_KARIBU,
    STATUS_NOT_IN_STATEMENT,
    ReconKnobs,
)


_NO_VALUE = "—"


@dataclass
class _MatchAssignment:
    status: str = STATUS_NOT_IN_STATEMENT
    match_type: str = _NO_VALUE
    confidence: str = _NO_VALUE
    matched_ref: str = _NO_VALUE


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def run_matching(
    karibu_df: pd.DataFrame,
    stmt_df: pd.DataFrame,
    knobs: ReconKnobs,
    match_outflows: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the 7-pass engine. Returns two DataFrames keyed by original index.

    `karibu_df` must have columns: `Date`, `DR`, `CR`.
    `stmt_df`   must have columns: `Date`, `Amount (UGX)`, `Direction`,
                                   `Transaction ID` (or "" if absent).

    Returns (karibu_result, stmt_result), each indexed identically to its
    input, with columns: Status, Match Type, Confidence, Matched Ref.

    When `match_outflows=False`, the Karibu CR rows are NOT considered —
    they appear in the result with `Status = "Not in Statement"` only if
    they had DR=0 and CR>0 (legacy behaviour filtered these out entirely;
    we keep them out of the result too).
    """
    karibu_result = pd.DataFrame(
        index=karibu_df.index,
        columns=["Status", "Match Type", "Confidence", "Matched Ref"],
        data=[[STATUS_NOT_IN_STATEMENT, _NO_VALUE, _NO_VALUE, _NO_VALUE]] * len(karibu_df),
    )
    stmt_result = pd.DataFrame(
        index=stmt_df.index,
        columns=["Status", "Match Type", "Confidence", "Matched Ref"],
        data=[[STATUS_NOT_IN_KARIBU, _NO_VALUE, _NO_VALUE, _NO_VALUE]] * len(stmt_df),
    )

    # --- Inflow direction: Karibu DR rows ↔ statement IN rows. ---
    k_in_mask = pd.to_numeric(karibu_df.get("DR"), errors="coerce").fillna(0) > 0
    s_in_mask = _direction_mask(stmt_df, "IN")
    _run_passes(
        karibu_df, stmt_df,
        k_mask=k_in_mask, s_mask=s_in_mask,
        k_amount_col="DR",
        karibu_result=karibu_result, stmt_result=stmt_result,
        knobs=knobs,
    )

    # --- Outflow direction (Petty Cash UGX). ---
    if match_outflows:
        k_out_mask = pd.to_numeric(karibu_df.get("CR"), errors="coerce").fillna(0) > 0
        s_out_mask = _direction_mask(stmt_df, "OUT")
        _run_passes(
            karibu_df, stmt_df,
            k_mask=k_out_mask, s_mask=s_out_mask,
            k_amount_col="CR",
            karibu_result=karibu_result, stmt_result=stmt_result,
            knobs=knobs,
        )

    return karibu_result, stmt_result


def _direction_mask(df: pd.DataFrame, direction: str) -> pd.Series:
    if "Direction" not in df.columns:
        # Legacy MTN/Airtel statements: positive amount = IN; negative = OUT.
        amounts = pd.to_numeric(df.get("Amount (UGX)"), errors="coerce").fillna(0)
        return amounts > 0 if direction == "IN" else amounts < 0
    return df["Direction"].astype(str).str.upper() == direction


# ---------------------------------------------------------------------------
# Internal: the 7-pass driver for one direction.
# ---------------------------------------------------------------------------

def _run_passes(
    karibu_df: pd.DataFrame,
    stmt_df: pd.DataFrame,
    *,
    k_mask: pd.Series,
    s_mask: pd.Series,
    k_amount_col: str,
    karibu_result: pd.DataFrame,
    stmt_result: pd.DataFrame,
    knobs: ReconKnobs,
) -> None:
    """Run all 7 passes over the masked subset; mutate result frames in place."""
    k_indices = list(karibu_df.index[k_mask])
    s_indices = list(stmt_df.index[s_mask])

    k_dates = [_as_ts(karibu_df.at[i, "Date"]) for i in k_indices]
    k_amounts = [float(karibu_df.at[i, k_amount_col]) for i in k_indices]
    s_dates = [_as_ts(stmt_df.at[i, "Date"]) for i in s_indices]
    s_amounts = [abs(float(stmt_df.at[i, "Amount (UGX)"])) for i in s_indices]
    s_ids = [
        str(stmt_df.at[i, "Transaction ID"]) if "Transaction ID" in stmt_df.columns else str(i)
        for i in s_indices
    ]

    # k_matched[local] and s_matched[local] track lock state for THIS direction.
    n_k = len(k_indices)
    n_s = len(s_indices)
    k_matched = [False] * n_k
    s_matched = [False] * n_s

    tol = knobs.amount_tolerance_ugx

    # ---- Passes 1-3 (+ optional 3.x widening): exact pairs ----
    pass_specs = _build_exact_pass_specs(knobs)
    for max_days, conf, mtype in pass_specs:
        for ki in range(n_k):
            if k_matched[ki]:
                continue
            k_date = k_dates[ki]
            k_amt = k_amounts[ki]
            if k_date is pd.NaT or k_date is None or np.isnan(k_amt):
                continue
            for si in range(n_s):
                if s_matched[si]:
                    continue
                s_date = s_dates[si]
                s_amt = s_amounts[si]
                if s_date is pd.NaT or s_date is None or np.isnan(s_amt):
                    continue
                if abs(k_amt - s_amt) < tol:
                    if abs((k_date - s_date).days) <= max_days:
                        _record_match(
                            karibu_result, stmt_result,
                            k_idx=k_indices[ki], s_idx=s_indices[si],
                            s_id=s_ids[si],
                            match_type=mtype, confidence=conf,
                        )
                        k_matched[ki] = True
                        s_matched[si] = True
                        break

    # ---- Passes 4-5: lumpsum K→S ----
    lumpsum_ks_passes = [
        (0, "60%"),
        (knobs.date_window_days, "45%"),
    ]
    for max_days, conf in lumpsum_ks_passes:
        for ki in range(n_k):
            if k_matched[ki]:
                continue
            k_date = k_dates[ki]
            k_amt = k_amounts[ki]
            if k_date is pd.NaT or k_date is None or np.isnan(k_amt) or k_amt <= 0:
                continue

            candidates: list[tuple[int, float]] = []
            for si in range(n_s):
                if s_matched[si]:
                    continue
                s_date = s_dates[si]
                s_amt = s_amounts[si]
                if s_date is pd.NaT or s_date is None or np.isnan(s_amt) or s_amt <= 0:
                    continue
                if abs((k_date - s_date).days) <= max_days:
                    candidates.append((si, s_amt))
            if not candidates:
                continue

            subset = _greedy_subset_sum(candidates, k_amt, tol)
            if not subset:
                continue

            refs: list[str] = []
            for si, _ in subset:
                s_matched[si] = True
                refs.append(s_ids[si])
                stmt_result.at[s_indices[si], "Status"] = STATUS_MATCHED
                stmt_result.at[s_indices[si], "Match Type"] = "Lumpsum"
                stmt_result.at[s_indices[si], "Confidence"] = conf
                stmt_result.at[s_indices[si], "Matched Ref"] = f"K{k_indices[ki]}"
            k_matched[ki] = True
            karibu_result.at[k_indices[ki], "Status"] = STATUS_MATCHED
            karibu_result.at[k_indices[ki], "Match Type"] = "Lumpsum"
            karibu_result.at[k_indices[ki], "Confidence"] = conf
            karibu_result.at[k_indices[ki], "Matched Ref"] = ",".join(refs)

    # ---- Pass 6: lumpsum S→K (date window from the dedicated knob) ----
    sk_window = knobs.lumpsum_window_days
    for si in range(n_s):
        if s_matched[si]:
            continue
        s_date = s_dates[si]
        s_amt = s_amounts[si]
        if s_date is pd.NaT or s_date is None or np.isnan(s_amt) or s_amt <= 0:
            continue
        candidates = []
        for ki in range(n_k):
            if k_matched[ki]:
                continue
            k_date = k_dates[ki]
            k_amt = k_amounts[ki]
            if k_date is pd.NaT or k_date is None or np.isnan(k_amt) or k_amt <= 0:
                continue
            if abs((s_date - k_date).days) <= sk_window:
                candidates.append((ki, k_amt))
        if not candidates:
            continue

        subset = _greedy_subset_sum(candidates, s_amt, tol)
        if not subset:
            continue

        refs = []
        for ki, _ in subset:
            k_matched[ki] = True
            refs.append(f"K{k_indices[ki]}")
            karibu_result.at[k_indices[ki], "Status"] = STATUS_MATCHED
            karibu_result.at[k_indices[ki], "Match Type"] = "Lumpsum"
            karibu_result.at[k_indices[ki], "Confidence"] = "55%"
            karibu_result.at[k_indices[ki], "Matched Ref"] = s_ids[si]
        s_matched[si] = True
        stmt_result.at[s_indices[si], "Status"] = STATUS_MATCHED
        stmt_result.at[s_indices[si], "Match Type"] = "Lumpsum"
        stmt_result.at[s_indices[si], "Confidence"] = "55%"
        stmt_result.at[s_indices[si], "Matched Ref"] = ",".join(refs)

    # ---- Pass 7: amount-only (any date) ----
    for ki in range(n_k):
        if k_matched[ki]:
            continue
        k_amt = k_amounts[ki]
        if np.isnan(k_amt):
            continue
        for si in range(n_s):
            if s_matched[si]:
                continue
            s_amt = s_amounts[si]
            if np.isnan(s_amt):
                continue
            if abs(k_amt - s_amt) < tol:
                _record_match(
                    karibu_result, stmt_result,
                    k_idx=k_indices[ki], s_idx=s_indices[si],
                    s_id=s_ids[si],
                    match_type="Amount Only", confidence="40%",
                )
                k_matched[ki] = True
                s_matched[si] = True
                break


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_exact_pass_specs(knobs: ReconKnobs) -> list[tuple[int, str, str]]:
    """Build the (max_days, confidence, match_type) tuples for passes 1-3+.

    Mirrors the legacy `core/reconciler.py` exactly — always runs widths
    (0, 100%) → (1, 90%) → (2, 80%); when `date_window_days` is greater
    than 2, appends one extra pass per additional day at -10% per day,
    floored at 70%.
    """
    specs: list[tuple[int, str, str]] = [
        (0, "100%", "Exact"),
        (1, "90%", "Exact"),
        (2, "80%", "Exact"),
    ]
    if knobs.date_window_days > 2:
        for d in range(3, knobs.date_window_days + 1):
            conf = max(70, 80 - (d - 2) * 10)
            specs.append((d, f"{conf}%", "Exact"))
    return specs


def _record_match(
    karibu_result: pd.DataFrame,
    stmt_result: pd.DataFrame,
    *,
    k_idx,
    s_idx,
    s_id: str,
    match_type: str,
    confidence: str,
) -> None:
    karibu_result.at[k_idx, "Status"] = STATUS_MATCHED
    karibu_result.at[k_idx, "Match Type"] = match_type
    karibu_result.at[k_idx, "Confidence"] = confidence
    karibu_result.at[k_idx, "Matched Ref"] = s_id
    stmt_result.at[s_idx, "Status"] = STATUS_MATCHED
    stmt_result.at[s_idx, "Match Type"] = match_type
    stmt_result.at[s_idx, "Confidence"] = confidence
    stmt_result.at[s_idx, "Matched Ref"] = f"K{k_idx}"


def _as_ts(value) -> pd.Timestamp | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value)


def _greedy_subset_sum(
    candidates: list[tuple[int, float]],
    target: float,
    tolerance: float,
) -> list[tuple[int, float]] | None:
    """Find a subset of `candidates` that sums to `target` ± `tolerance`.

    Mirrors the legacy engine: single hit → largest-fit greedy → exhaustive
    small combos (up to 5 items chosen from the top 15 by amount). The
    exhaustive cap matters for MTN parity — bumping it would silently
    surface new lumpsum matches that the legacy engine missed.
    """
    if not candidates:
        return None
    sorted_cands = sorted(candidates, key=lambda x: x[1], reverse=True)

    for c in sorted_cands:
        if abs(c[1] - target) < tolerance:
            return [c]

    remaining = target
    selected: list[tuple[int, float]] = []
    for c in sorted_cands:
        if c[1] <= remaining + tolerance:
            selected.append(c)
            remaining -= c[1]
            if abs(remaining) < tolerance:
                return selected

    trimmed = sorted_cands[:15]
    for r in range(2, min(6, len(trimmed) + 1)):
        for combo in combinations(trimmed, r):
            total = sum(c[1] for c in combo)
            if abs(total - target) < tolerance:
                return list(combo)
    return None
