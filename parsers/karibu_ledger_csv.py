"""Karibu HMS ledger CSV parser.

Reads the raw export, format-tolerantly parses each row's date, and emits
NormalizedRecord rows. Rows with no parseable date are emitted with
`audit_flag = UNPARSEABLE_DATE` rather than dropped (Joash, 2026-05-20).

The legacy `core.parsers.parse_karibu_csv` is intentionally NOT used here —
it silently coerces bad dates to NaT and then drops them, which is the
class of behaviour BUGFIX.md addresses.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from parsers._dates import parse_date
from parsers.types import (
    AUDIT_UNPARSEABLE_DATE,
    DIRECTION_IN,
    DIRECTION_OUT,
    NormalizedRecord,
)


# Karibu export uses a single canonical format, but we still go through
# parse_date so anything weird falls through to permissive parsing instead
# of silently NaT'ing.
_KARIBU_DATE_FORMATS = ("%Y-%m-%d",)


def parse(path: Path, karibu_account: str | None = None) -> list[NormalizedRecord]:
    """Parse a Karibu ledger CSV into NormalizedRecord rows.

    If `karibu_account` is given, only rows whose `Account` matches exactly
    are emitted (e.g. `"PC - Petty Cash UGX"`).

    Rows skipped silently (structural noise, no reconciliation signal):
      - Opening Balance marker (Date column literally reads "Opening Balance")
      - Trailing Totals row (Date == "Total" or similar)
      - Both DR and CR are 0
    """
    p = Path(path)
    df = pd.read_csv(p, skiprows=2, dtype=str, quotechar='"')
    df.columns = df.columns.str.strip()
    source = p.name

    if "Date" not in df.columns:
        return []

    records: list[NormalizedRecord] = []
    for idx, row in df.iterrows():
        date_raw = row.get("Date")
        date_str = str(date_raw).strip() if pd.notna(date_raw) else ""
        # Drop structural markers — they're not real ledger entries.
        if not date_str or date_str.lower() in {"opening balance", "total", "totals"}:
            continue

        account = _stripped(row.get("Account"))
        if karibu_account is not None and account != karibu_account:
            continue

        dr = _to_decimal(row.get("DR"))
        cr = _to_decimal(row.get("CR"))
        if dr == 0 and cr == 0:
            continue

        date_val, flag = parse_date(
            date_str, _KARIBU_DATE_FORMATS,
            source_file=source, row_index=int(idx), field_name="Date",
        )

        if dr > 0:
            direction = DIRECTION_IN
            amount = dr
            txn_type = "DR"
        else:
            direction = DIRECTION_OUT
            amount = cr
            txn_type = "CR"

        narration = _stripped(row.get("Narration"))
        records.append(NormalizedRecord(
            source_file=source,
            date=date_val,
            txn_id="",
            amount=amount,
            direction=direction,
            counterparty=narration,
            txn_type=txn_type,
            raw={
                "Date": date_str,
                "Account": account,
                "Narration": narration,
                "DR": str(dr),
                "CR": str(cr),
                "Balance": _stripped(row.get("Balance")),
            },
            audit_flag=flag,
        ))
    return records


def _to_decimal(value) -> Decimal:
    if value is None:
        return Decimal(0)
    try:
        if pd.isna(value):
            return Decimal(0)
    except (TypeError, ValueError):
        pass
    try:
        return Decimal(str(value).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _stripped(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()
