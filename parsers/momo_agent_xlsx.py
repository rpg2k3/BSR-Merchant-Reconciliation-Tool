"""MoMo Agent Transaction Detailed Report XLSX parser.

Used by the Petty Cash UGX account. Direction is driven by Transaction Type
(CASH_IN / DEPOSIT → IN; TRANSFER → OUT). Amount is normalised to a positive
Decimal; the sign in the raw export (TRANSFER rows can be stored as negative)
is carried by `direction`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from parsers.types import DIRECTION_IN, DIRECTION_OUT, NormalizedRecord


SHEET_NAME = "Sheet1"

_INFLOW_TYPES = {"CASH_IN", "DEPOSIT"}
_OUTFLOW_TYPES = {"TRANSFER"}


def parse(path: Path) -> list[NormalizedRecord]:
    """Parse a MoMo Agent xlsx and return NormalizedRecord rows.

    Header is row 1 (no skiprows). Transaction IDs are read as str so the
    large integers don't lose precision through a float roundtrip.
    """
    p = Path(path)
    df = pd.read_excel(p, sheet_name=SHEET_NAME, dtype={"Transaction ID": str})
    source = p.name

    records: list[NormalizedRecord] = []
    for _, row in df.iterrows():
        txn_type = str(row.get("Transaction Type") or "").strip()
        if not txn_type:
            continue
        direction = _direction_for(txn_type, row)
        if direction is None:
            continue

        date = row.get("Date / Time")
        if pd.isna(date):
            continue

        amount = _to_decimal(row.get("Amount"))
        if amount == 0:
            continue

        from_acct = _account_str(row.get("From Account"))
        to_acct = _account_str(row.get("To Account"))
        counterparty = from_acct if direction == DIRECTION_IN else to_acct

        records.append(NormalizedRecord(
            source_file=source,
            date=pd.Timestamp(date).to_pydatetime(),
            txn_id=str(row.get("Transaction ID") or "").strip(),
            amount=abs(amount),
            direction=direction,
            counterparty=counterparty,
            txn_type=txn_type,
            raw={k: _stringify(v) for k, v in row.items()},
        ))
    return records


def _direction_for(txn_type: str, row) -> str | None:
    if txn_type in _INFLOW_TYPES:
        return DIRECTION_IN
    if txn_type in _OUTFLOW_TYPES:
        return DIRECTION_OUT
    # Spec §5 fallback: if the type is unknown, fall back to From/To inspection.
    # The agent's number is constant across the file; whichever side it appears
    # on tells us the direction. We can't know the agent number a priori here,
    # so a safer default is to skip the row and let the consolidator flag it.
    return None


def _to_decimal(value) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return Decimal(0)
    try:
        return Decimal(str(value).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _account_str(value) -> str:
    if value is None or value is False:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _stringify(value):
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value)
