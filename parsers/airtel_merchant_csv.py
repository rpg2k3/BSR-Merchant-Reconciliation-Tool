"""Airtel Merchant CSV parser.

Combines Customer Transaction Reports (primary IN flows) and User Transaction
Reports (contras — MP + ChannelWallet To Bank Transfer → OUT), mirroring the
logic in `core.updater.update_airtel_statement`.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from core.parsers import (
    identify_airtel_csv_type,
    parse_airtel_customer_csv,
    parse_airtel_user_csv,
)
from parsers.types import DIRECTION_IN, DIRECTION_OUT, NormalizedRecord


def parse(path: Path) -> list[NormalizedRecord]:
    p = Path(path)
    csv_type = identify_airtel_csv_type(p)
    if csv_type == "customer":
        return _parse_customer(p)
    if csv_type == "user":
        return _parse_user_contras(p)
    return []


def _parse_customer(path: Path) -> list[NormalizedRecord]:
    df = parse_airtel_customer_csv(path)
    source = path.name
    records: list[NormalizedRecord] = []
    for _, row in df.iterrows():
        date = row.get("_parsed_datetime", row.get("Transaction Date"))
        amount = _to_decimal(row.get("Transaction Amount"))
        if pd.isna(date) or amount == 0:
            continue
        records.append(NormalizedRecord(
            source_file=source,
            date=pd.Timestamp(date).to_pydatetime(),
            txn_id=str(row.get("Transaction ID") or "").strip(),
            amount=abs(amount),
            direction=DIRECTION_IN,
            counterparty=str(row.get("Payer User Name") or "").strip(),
            txn_type=str(row.get("Service Type") or "").strip(),
            raw={k: _stringify(v) for k, v in row.items()},
        ))
    return records


def _parse_user_contras(path: Path) -> list[NormalizedRecord]:
    df = parse_airtel_user_csv(path)
    source = path.name
    if "Service Name" not in df.columns:
        return []
    contras = df[
        (df.get("Transaction Type") == "MP")
        & df["Service Name"].astype(str).str.contains(
            "ChannelWallet To Bank Transfer", case=False, na=False
        )
    ]
    records: list[NormalizedRecord] = []
    for _, row in contras.iterrows():
        date = row.get("Transaction Date")
        amount = _to_decimal(row.get("Transaction Amount"))
        if pd.isna(date) or amount == 0:
            continue
        records.append(NormalizedRecord(
            source_file=source,
            date=pd.Timestamp(date).to_pydatetime(),
            txn_id=str(row.get("Transaction ID") or "").strip(),
            amount=abs(amount),
            direction=DIRECTION_OUT,
            counterparty=str(row.get("Receiver Msisdn") or "").strip(),
            txn_type="Contra",
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
