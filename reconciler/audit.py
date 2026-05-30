"""Audit / anomaly flagging with the Phase-3 suppression matrix.

The flag catalogue is preserved verbatim from `core/anomalies.py` so
downstream tools (AI analyst grep patterns, UI badge mapping) keep
working unchanged. Phase 3 adds two new behaviours on top of the legacy
ruleset:

  1. PETTY_CASH_NO_STATEMENT_EXPECTED — a soft flag attached to every
     unmatched Karibu row on accounts where `karibu_only_is_normal=True`.
     Petty-cash entries that have no MoMo counterpart are expected to
     exist (pure-cash moves), so they need to be visible without being
     escalated as errors.

  2. Suppression of the hard-escalation flags
     (UNMATCHED_HIGH_VALUE, LARGE_SINGLE_PAYMENT, DATE_GAP) on those same
     rows. The other observational flags (DUPLICATE_AMOUNT_SAME_DAY,
     KARIBU_ONLY_REPEATED_NARRATION) stay — they're legitimate signals
     regardless of whether the row was expected to be statement-less.

For accounts with `match_outflows=True`, suppression applies to BOTH the
DR-unmatched and CR-unmatched Karibu rows. This is the Petty-Cash case —
expense-side rows (Karibu CR) without a matching TRANSFER row may also
be pure-cash and should not escalate.
"""

from __future__ import annotations

import pandas as pd

from config import AccountConfig
from reconciler.types import (
    FLAG_CONTRA_NOT_IN_KARIBU,
    FLAG_DATE_GAP,
    FLAG_DUPLICATE_SAME_DAY,
    FLAG_KARIBU_REPEATED,
    FLAG_LARGE_SINGLE_PAYMENT,
    FLAG_LOW_CONFIDENCE,
    FLAG_PETTY_CASH_NO_STMT,
    FLAG_STMT_PAYER_FREQ,
    FLAG_UNMATCHED_HIGH_VALUE,
    STATUS_CONTRA,
    STATUS_NOT_IN_KARIBU,
    STATUS_NOT_IN_STATEMENT,
    SUPPRESSED_ON_KARIBU_ONLY,
)


_DEFAULT_HIGH_VALUE = 500_000
_DEFAULT_LARGE_PAYMENT = 1_000_000


def apply_audit(
    karibu_out: pd.DataFrame,
    stmt_out: pd.DataFrame,
    *,
    account: AccountConfig,
    app_config: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Populate the `Audit Flag` column on both DataFrames.

    `karibu_out` must include: Date, Narration, DR (UGX), CR (UGX), Status, Confidence.
    `stmt_out`   must include: Date, Amount (UGX), Status, Confidence (and
                  optionally Payer Name, Direction).
    """
    app_config = app_config or {}
    high_value = app_config.get("high_value_threshold", _DEFAULT_HIGH_VALUE)
    large_payment = app_config.get("large_payment_threshold", _DEFAULT_LARGE_PAYMENT)

    k_flags = [""] * len(karibu_out)
    s_flags = [""] * len(stmt_out)

    # Reset positional indexes for safe assignment via iloc-equivalent .iat.
    k_iter = karibu_out.reset_index(drop=False)
    s_iter = stmt_out.reset_index(drop=False)

    # --- UNMATCHED_HIGH_VALUE ---
    for pos, row in k_iter.iterrows():
        if row["Status"] != STATUS_NOT_IN_STATEMENT:
            continue
        amount = _amount(row, ("DR (UGX)", "CR (UGX)"))
        if amount >= high_value:
            k_flags[pos] = _add_flag(k_flags[pos], FLAG_UNMATCHED_HIGH_VALUE)
    for pos, row in s_iter.iterrows():
        if row["Status"] != STATUS_NOT_IN_KARIBU:
            continue
        amount = _amount(row, ("Amount (UGX)",), absolute=True)
        if amount >= high_value:
            s_flags[pos] = _add_flag(s_flags[pos], FLAG_UNMATCHED_HIGH_VALUE)

    # --- CONTRA_NOT_IN_KARIBU ---
    # Build a (date, abs(amount)) set of Karibu CR rows for fast lookup.
    cr_keys: set[tuple[pd.Timestamp, int]] = set()
    for _, row in k_iter.iterrows():
        cr = _to_float(row.get("CR (UGX)", 0))
        if cr > 0:
            d = pd.to_datetime(row.get("Date"), errors="coerce")
            if not pd.isna(d):
                cr_keys.add((d.date(), round(cr)))
    for pos, row in s_iter.iterrows():
        if row.get("Status") != STATUS_CONTRA:
            continue
        amount = _amount(row, ("Amount (UGX)",), absolute=True)
        d = pd.to_datetime(row.get("Date"), errors="coerce")
        if pd.isna(d):
            continue
        found = False
        for delta in range(-2, 3):
            if ((d + pd.Timedelta(days=delta)).date(), round(amount)) in cr_keys:
                found = True
                break
        if not found:
            s_flags[pos] = _add_flag(s_flags[pos], FLAG_CONTRA_NOT_IN_KARIBU)

    # --- DUPLICATE_AMOUNT_SAME_DAY ---
    _flag_duplicates_same_day(k_iter, "DR (UGX)", "Date", k_flags)
    _flag_duplicates_same_day(s_iter, "Amount (UGX)", "Date", s_flags)

    # --- DATE_GAP ---
    _flag_date_gaps(k_iter, "Date", k_flags)
    _flag_date_gaps(s_iter, "Date", s_flags)

    # --- LARGE_SINGLE_PAYMENT ---
    for pos, row in k_iter.iterrows():
        amount = _amount(row, ("DR (UGX)", "CR (UGX)"))
        if amount >= large_payment:
            k_flags[pos] = _add_flag(k_flags[pos], FLAG_LARGE_SINGLE_PAYMENT)
    for pos, row in s_iter.iterrows():
        amount = _amount(row, ("Amount (UGX)",), absolute=True)
        if amount >= large_payment:
            s_flags[pos] = _add_flag(s_flags[pos], FLAG_LARGE_SINGLE_PAYMENT)

    # --- LOW_CONFIDENCE_MATCH ---
    for pos, row in k_iter.iterrows():
        if _confidence_below(row.get("Confidence", ""), 45):
            k_flags[pos] = _add_flag(k_flags[pos], FLAG_LOW_CONFIDENCE)
    for pos, row in s_iter.iterrows():
        if _confidence_below(row.get("Confidence", ""), 45):
            s_flags[pos] = _add_flag(s_flags[pos], FLAG_LOW_CONFIDENCE)

    # --- KARIBU_ONLY_REPEATED_NARRATION ---
    unmatched_k = k_iter[k_iter["Status"] == STATUS_NOT_IN_STATEMENT]
    if not unmatched_k.empty and "Narration" in unmatched_k.columns:
        groups: dict[str, list[int]] = {}
        for pos, row in unmatched_k.iterrows():
            narration = str(row.get("Narration", "")).strip()
            if narration:
                groups.setdefault(narration, []).append(pos)
        for indices in groups.values():
            dates = set()
            for pos in indices:
                d = pd.to_datetime(unmatched_k.at[pos, "Date"], errors="coerce")
                if not pd.isna(d):
                    dates.add(d.date())
            if len(dates) >= 2:
                for pos in indices:
                    k_flags[pos] = _add_flag(k_flags[pos], FLAG_KARIBU_REPEATED)

    # --- STMT_PAYER_HIGH_FREQUENCY ---
    if "Payer Name" in s_iter.columns:
        s_copy = s_iter.copy()
        s_copy["_month"] = pd.to_datetime(s_copy["Date"], errors="coerce").dt.to_period("M")
        for (payer, month), group in s_copy.groupby(["Payer Name", "_month"], dropna=False):
            if len(group) >= 5 and str(payer).strip():
                for pos in group.index:
                    s_flags[pos] = _add_flag(s_flags[pos], FLAG_STMT_PAYER_FREQ)

    # --- Phase-3 suppression matrix ---
    if account.karibu_only_is_normal:
        _apply_karibu_only_suppression(
            karibu_out, k_flags,
            match_outflows=account.match_outflows,
        )

    karibu_out["Audit Flag"] = k_flags
    stmt_out["Audit Flag"] = s_flags
    return karibu_out, stmt_out


def _apply_karibu_only_suppression(
    karibu_out: pd.DataFrame,
    k_flags: list[str],
    *,
    match_outflows: bool,
) -> None:
    """Replace hard-escalation flags with the soft PETTY_CASH_NO_STMT flag.

    Applies to every Karibu row whose Status is "Not in Statement". When
    `match_outflows` is True, both DR-side and CR-side unmatched rows are
    covered (they all carry the same status string by then). When False,
    only DR-side rows exist in `karibu_out` to begin with, so the same
    blanket pass over rows tagged "Not in Statement" works for both
    cases.
    """
    statuses = karibu_out["Status"].tolist()
    for pos, status in enumerate(statuses):
        if status != STATUS_NOT_IN_STATEMENT:
            continue
        # Strip the suppressed hard-escalation flags …
        flags = [f for f in _split_flags(k_flags[pos]) if f not in SUPPRESSED_ON_KARIBU_ONLY]
        # … and attach the soft "expected" flag.
        if FLAG_PETTY_CASH_NO_STMT not in flags:
            flags.append(FLAG_PETTY_CASH_NO_STMT)
        k_flags[pos] = ",".join(flags)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_flags(s: str) -> list[str]:
    if not s:
        return []
    return [f.strip() for f in s.split(",") if f.strip()]


def _add_flag(existing: str, new_flag: str) -> str:
    flags = _split_flags(existing)
    if new_flag not in flags:
        flags.append(new_flag)
    return ",".join(flags)


def _to_float(value) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if pd.isna(f):
        return 0.0
    return f


def _amount(row, columns: tuple[str, ...], absolute: bool = False) -> float:
    """Return the first non-zero amount across `columns`. Uses abs() if asked."""
    for col in columns:
        v = _to_float(row.get(col, 0))
        if v != 0:
            return abs(v) if absolute else v
    return 0.0


def _confidence_below(conf, threshold: int) -> bool:
    s = str(conf).strip() if conf is not None else ""
    if not s or s == "—":
        return False
    try:
        return int(s.replace("%", "")) <= threshold
    except (TypeError, ValueError):
        return False


def _flag_duplicates_same_day(
    df: pd.DataFrame, amount_col: str, date_col: str, flags: list[str]
) -> None:
    if amount_col not in df.columns or date_col not in df.columns:
        return
    amounts = pd.to_numeric(df[amount_col], errors="coerce")
    dates = pd.to_datetime(df[date_col], errors="coerce")
    n = len(df)
    for i in range(n):
        a_i, d_i = amounts.iloc[i], dates.iloc[i]
        if pd.isna(a_i) or pd.isna(d_i) or a_i == 0:
            continue
        for j in range(i + 1, n):
            a_j, d_j = amounts.iloc[j], dates.iloc[j]
            if pd.isna(a_j) or pd.isna(d_j) or a_j == 0:
                continue
            if abs(a_i - a_j) < 0.5 and d_i.date() == d_j.date():
                flags[i] = _add_flag(flags[i], FLAG_DUPLICATE_SAME_DAY)
                flags[j] = _add_flag(flags[j], FLAG_DUPLICATE_SAME_DAY)


def _flag_date_gaps(df: pd.DataFrame, date_col: str, flags: list[str]) -> None:
    if date_col not in df.columns:
        return
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna().dt.date
    if dates.empty:
        return
    uniq = sorted(dates.unique())
    if len(uniq) < 2:
        return
    gap_dates: set = set()
    for prev, curr in zip(uniq, uniq[1:]):
        # Count business days between (legacy convention).
        bdays = pd.bdate_range(prev, curr).shape[0] - 1
        if bdays >= 3:
            gap_dates.add(prev)
            gap_dates.add(curr)
    if not gap_dates:
        return
    parsed = pd.to_datetime(df[date_col], errors="coerce")
    for pos in range(len(df)):
        d = parsed.iloc[pos]
        if not pd.isna(d) and d.date() in gap_dates:
            flags[pos] = _add_flag(flags[pos], FLAG_DATE_GAP)
