"""Karibu HMS ledger CSV parser.

Wraps `core.parsers.parse_karibu_csv` so the legacy reconciler keeps working
unchanged while the new pluggable pipeline gets a `NormalizedRecord` view.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from core.parsers import parse_karibu_csv
from parsers.types import DIRECTION_IN, DIRECTION_OUT, NormalizedRecord


def parse(path: Path, karibu_account: str | None = None) -> list[NormalizedRecord]:
    """Parse a Karibu ledger CSV into NormalizedRecord rows.

    If `karibu_account` is given, only rows whose `Account` matches exactly
    are returned. DR rows become direction=IN, CR rows become direction=OUT.
    Rows with both DR=0 and CR=0 are skipped (the parser already strips
    Opening Balance and rows with unparseable dates).
    """
    df = parse_karibu_csv(Path(path))
    if karibu_account is not None and "Account" in df.columns:
        df = df[df["Account"].astype(str).str.strip() == karibu_account].copy()

    source = Path(path).name
    records: list[NormalizedRecord] = []
    for _, row in df.iterrows():
        dr = _to_decimal(row.get("DR", 0))
        cr = _to_decimal(row.get("CR", 0))
        date = row.get("Date")
        if pd.isna(date):
            continue
        date = pd.Timestamp(date).to_pydatetime()
        narration = str(row.get("Narration") or "").strip()
        account = str(row.get("Account") or "").strip()

        if dr > 0:
            direction = DIRECTION_IN
            amount = dr
            txn_type = "DR"
        elif cr > 0:
            direction = DIRECTION_OUT
            amount = cr
            txn_type = "CR"
        else:
            # Zero-value Karibu rows carry no reconciliation signal.
            continue

        records.append(NormalizedRecord(
            source_file=source,
            date=date,
            txn_id="",
            amount=amount,
            direction=direction,
            counterparty=narration,
            txn_type=txn_type,
            raw={
                "Date": date.isoformat(),
                "Account": account,
                "Narration": narration,
                "DR": str(dr),
                "CR": str(cr),
                "Balance": str(row.get("Balance", "")),
            },
        ))
    return records


def _to_decimal(value) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal(0)
    try:
        return Decimal(str(value).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal(0)
