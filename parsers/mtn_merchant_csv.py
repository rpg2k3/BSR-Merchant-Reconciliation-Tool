"""MTN Merchant portal CSV parser.

Reads the raw export, format-tolerantly parses each row's date, and emits
NormalizedRecord rows. Positive Amount → IN (merchant receipt); negative
Amount → OUT (contra). Rows with unparseable dates pass through tagged
with `audit_flag = UNPARSEABLE_DATE` (Joash, 2026-05-20).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from parsers._dates import parse_date
from parsers.types import DIRECTION_IN, DIRECTION_OUT, NormalizedRecord


# The MTN portal has historically exported `YYYY-MM-DD HH:MM:SS` (verified
# 2026-05-20 across oldest March and newest May files in production data).
# Any other format falls through to permissive parsing.
_MTN_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def parse(path: Path) -> list[NormalizedRecord]:
    p = Path(path)
    df = pd.read_csv(p, dtype={"Id": str})
    source = p.name

    records: list[NormalizedRecord] = []
    for idx, row in df.iterrows():
        amount = _to_decimal(row.get("Amount"))
        if amount == 0:
            continue

        date_val, flag = parse_date(
            row.get("Date"), _MTN_DATE_FORMATS,
            source_file=source, row_index=int(idx), field_name="Date",
        )

        direction = DIRECTION_IN if amount > 0 else DIRECTION_OUT
        records.append(NormalizedRecord(
            source_file=source,
            date=date_val,
            txn_id=_stripped(row.get("Id")),
            amount=abs(amount),
            direction=direction,
            counterparty=_stripped(row.get("From name")),
            txn_type=_stripped(row.get("Status")),
            raw={k: _stringify(v) for k, v in row.items()},
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


def _stringify(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)
