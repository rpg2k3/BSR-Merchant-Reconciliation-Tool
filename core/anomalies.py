"""Module 3 — Anomaly Detection & Audit Flags.

Purely code-based flag logic. No AI required for this module.
"""

import pandas as pd
import numpy as np
from datetime import timedelta


def run_anomaly_detection(
    karibu_out: pd.DataFrame,
    stmt_out: pd.DataFrame,
    karibu_full: pd.DataFrame,
    stmt_full: pd.DataFrame,
    channel: str,
    config: dict,
    stmt_amount_col: str,
    stmt_date_col: str,
    stmt_payer_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run all anomaly detection passes on reconciliation output.

    Modifies the Audit Flag column in both DataFrames.
    Returns (karibu_out, stmt_out).
    """
    high_value = config.get("high_value_threshold", 500_000)
    large_payment = config.get("large_payment_threshold", 1_000_000)

    # Initialize Audit Flag columns
    karibu_flags = [""] * len(karibu_out)
    stmt_flags = [""] * len(stmt_out)

    # --- UNMATCHED_HIGH_VALUE ---
    for i, row in karibu_out.iterrows():
        if row["Status"] == "Not in Statement":
            amount = pd.to_numeric(row.get("DR (UGX)", 0), errors="coerce")
            if not pd.isna(amount) and amount >= high_value:
                karibu_flags[i] = _add_flag(karibu_flags[i], "UNMATCHED_HIGH_VALUE")

    for i, row in stmt_out.iterrows():
        if row["Status"] == "Not in Karibu":
            amount = pd.to_numeric(row.get("Amount (UGX)", 0), errors="coerce")
            if not pd.isna(amount) and abs(amount) >= high_value:
                stmt_flags[i] = _add_flag(stmt_flags[i], "UNMATCHED_HIGH_VALUE")

    # --- CONTRA_NOT_IN_KARIBU ---
    # Check contras in statement not reflected in Karibu CR
    karibu_cr_dates_amounts = set()
    for _, row in karibu_full.iterrows():
        cr = pd.to_numeric(row.get("CR", 0), errors="coerce")
        if not pd.isna(cr) and cr > 0:
            d = pd.to_datetime(row.get("Date"), errors="coerce")
            if not pd.isna(d):
                karibu_cr_dates_amounts.add((d.date(), round(cr)))

    for i, row in stmt_out.iterrows():
        amount = pd.to_numeric(row.get("Amount (UGX)", 0), errors="coerce")
        if pd.isna(amount):
            continue
        is_contra = False
        if channel == "MTN" and amount < 0:
            is_contra = True
        elif row.get("Status") == "Contra":
            is_contra = True

        if is_contra:
            d = pd.to_datetime(row.get("Date"), errors="coerce")
            if not pd.isna(d):
                abs_amount = round(abs(amount))
                found = False
                for delta in range(-2, 3):
                    check_date = (d + timedelta(days=delta)).date()
                    if (check_date, abs_amount) in karibu_cr_dates_amounts:
                        found = True
                        break
                if not found:
                    stmt_flags[i] = _add_flag(stmt_flags[i], "CONTRA_NOT_IN_KARIBU")

    # --- DUPLICATE_AMOUNT_SAME_DAY ---
    _check_duplicate_same_day(stmt_out, "Amount (UGX)", "Date", stmt_flags)
    _check_duplicate_same_day(karibu_out, "DR (UGX)", "Date", karibu_flags)

    # --- DATE_GAP ---
    _check_date_gaps(karibu_out, "Date", karibu_flags)
    _check_date_gaps(stmt_out, "Date", stmt_flags)

    # --- LARGE_SINGLE_PAYMENT ---
    for i, row in karibu_out.iterrows():
        amount = pd.to_numeric(row.get("DR (UGX)", 0), errors="coerce")
        if not pd.isna(amount) and amount >= large_payment:
            karibu_flags[i] = _add_flag(karibu_flags[i], "LARGE_SINGLE_PAYMENT")

    for i, row in stmt_out.iterrows():
        amount = pd.to_numeric(row.get("Amount (UGX)", 0), errors="coerce")
        if not pd.isna(amount) and abs(amount) >= large_payment:
            stmt_flags[i] = _add_flag(stmt_flags[i], "LARGE_SINGLE_PAYMENT")

    # --- LOW_CONFIDENCE_MATCH ---
    for i, row in karibu_out.iterrows():
        conf = row.get("Confidence", "")
        if conf and conf != "—":
            try:
                val = int(str(conf).replace("%", ""))
                if val <= 45:
                    karibu_flags[i] = _add_flag(karibu_flags[i], "LOW_CONFIDENCE_MATCH")
            except (ValueError, TypeError):
                pass

    for i, row in stmt_out.iterrows():
        conf = row.get("Confidence", "")
        if conf and conf != "—":
            try:
                val = int(str(conf).replace("%", ""))
                if val <= 45:
                    stmt_flags[i] = _add_flag(stmt_flags[i], "LOW_CONFIDENCE_MATCH")
            except (ValueError, TypeError):
                pass

    # --- KARIBU_ONLY_REPEATED_NARRATION ---
    unmatched_karibu = karibu_out[karibu_out["Status"] == "Not in Statement"]
    if not unmatched_karibu.empty:
        narration_dates = {}
        for i, row in unmatched_karibu.iterrows():
            narr = str(row.get("Narration", "")).strip()
            if narr:
                narration_dates.setdefault(narr, []).append(i)

        for narr, indices in narration_dates.items():
            dates = set()
            for idx in indices:
                d = pd.to_datetime(karibu_out.at[idx, "Date"], errors="coerce")
                if not pd.isna(d):
                    dates.add(d.date())
            if len(dates) >= 2:
                for idx in indices:
                    karibu_flags[idx] = _add_flag(karibu_flags[idx], "KARIBU_ONLY_REPEATED_NARRATION")

    # --- STMT_PAYER_HIGH_FREQUENCY ---
    if "Payer Name" in stmt_out.columns:
        stmt_out_copy = stmt_out.copy()
        stmt_out_copy["_month"] = pd.to_datetime(stmt_out_copy["Date"], errors="coerce").dt.to_period("M")
        for (payer, month), group in stmt_out_copy.groupby(["Payer Name", "_month"]):
            if len(group) >= 5 and str(payer).strip():
                for idx in group.index:
                    stmt_flags[idx] = _add_flag(stmt_flags[idx], "STMT_PAYER_HIGH_FREQUENCY")

    # Apply flags
    karibu_out["Audit Flag"] = karibu_flags
    stmt_out["Audit Flag"] = stmt_flags

    return karibu_out, stmt_out


def _add_flag(existing: str, new_flag: str) -> str:
    """Add a flag to a comma-separated flag string."""
    if not existing:
        return new_flag
    flags = [f.strip() for f in existing.split(",")]
    if new_flag not in flags:
        flags.append(new_flag)
    return ",".join(flags)


def _check_duplicate_same_day(df: pd.DataFrame, amount_col: str, date_col: str, flags: list):
    """Flag rows where same amount appears 2+ times on the same date."""
    amounts = pd.to_numeric(df[amount_col], errors="coerce")
    dates = pd.to_datetime(df[date_col], errors="coerce")

    for i in range(len(df)):
        if pd.isna(amounts.iloc[i]) or pd.isna(dates.iloc[i]):
            continue
        for j in range(i + 1, len(df)):
            if pd.isna(amounts.iloc[j]) or pd.isna(dates.iloc[j]):
                continue
            if (abs(amounts.iloc[i] - amounts.iloc[j]) < 0.5 and
                    dates.iloc[i].date() == dates.iloc[j].date()):
                flags[i] = _add_flag(flags[i], "DUPLICATE_AMOUNT_SAME_DAY")
                flags[j] = _add_flag(flags[j], "DUPLICATE_AMOUNT_SAME_DAY")


def _check_date_gaps(df: pd.DataFrame, date_col: str, flags: list):
    """Flag if there's a 3+ business day gap (excluding weekends) in transactions."""
    dates = pd.to_datetime(df[date_col], errors="coerce").dropna().dt.date
    if dates.empty:
        return

    unique_dates = sorted(dates.unique())
    if len(unique_dates) < 2:
        return

    for i in range(1, len(unique_dates)):
        d1 = unique_dates[i - 1]
        d2 = unique_dates[i]
        # Count business days between
        bdays = pd.bdate_range(d1, d2).shape[0] - 1  # Exclude start date
        if bdays >= 3:
            # Flag rows on dates adjacent to the gap
            for idx in range(len(df)):
                row_date = pd.to_datetime(df.iloc[idx][date_col], errors="coerce")
                if not pd.isna(row_date):
                    if row_date.date() == d1 or row_date.date() == d2:
                        flags[idx] = _add_flag(flags[idx], "DATE_GAP")


def get_flagged_summary(karibu_out: pd.DataFrame, stmt_out: pd.DataFrame) -> list[dict]:
    """Extract all flagged rows as a list of dicts for AI analysis."""
    flagged = []
    for _, row in karibu_out.iterrows():
        if row.get("Audit Flag") and str(row["Audit Flag"]) not in ("", "nan"):
            flagged.append({
                "source": "Karibu",
                "date": str(row.get("Date", "")),
                "narration": str(row.get("Narration", "")),
                "amount": str(row.get("DR (UGX)", "")),
                "status": str(row.get("Status", "")),
                "flags": str(row["Audit Flag"]),
                "confidence": str(row.get("Confidence", "")),
            })

    for _, row in stmt_out.iterrows():
        if row.get("Audit Flag") and str(row["Audit Flag"]) not in ("", "nan"):
            flagged.append({
                "source": "Statement",
                "date": str(row.get("Date", "")),
                "transaction_id": str(row.get("Transaction ID", "")),
                "payer": str(row.get("Payer Name", "")),
                "amount": str(row.get("Amount (UGX)", "")),
                "status": str(row.get("Status", "")),
                "flags": str(row["Audit Flag"]),
                "confidence": str(row.get("Confidence", "")),
            })

    return flagged
