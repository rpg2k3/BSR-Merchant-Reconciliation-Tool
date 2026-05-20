"""MTN Merchant portal CSV parser.

Wraps `core.parsers.parse_mtn_csv` and emits NormalizedRecord rows.
Positive Amount → IN (merchant receipt); negative Amount → OUT (contra).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from core.parsers import parse_mtn_csv
from parsers.types import DIRECTION_IN, DIRECTION_OUT, NormalizedRecord


def parse(path: Path) -> list[NormalizedRecord]:
    df = parse_mtn_csv(Path(path))
    source = Path(path).name
    records: list[NormalizedRecord] = []
    for _, row in df.iterrows():
        date = row.get("Date")
        amount_raw = row.get("Amount")
        if pd.isna(date) or pd.isna(amount_raw):
            continue
        amount = _to_decimal(amount_raw)
        if amount == 0:
            continue
        direction = DIRECTION_IN if amount > 0 else DIRECTION_OUT
        records.append(NormalizedRecord(
            source_file=source,
            date=pd.Timestamp(date).to_pydatetime(),
            txn_id=str(row.get("Id") or "").strip(),
            amount=abs(amount),
            direction=direction,
            counterparty=str(row.get("From name") or "").strip(),
            txn_type=str(row.get("Status") or "").strip(),
            raw={k: _stringify(v) for k, v in row.items()},
        ))
    return records


def _to_decimal(value) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal(0)
    try:
        return Decimal(str(value).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _stringify(value):
    if pd.isna(value):
        return ""
    return str(value)
