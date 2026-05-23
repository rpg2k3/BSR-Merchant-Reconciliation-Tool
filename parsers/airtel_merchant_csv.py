"""Airtel Merchant CSV parser.

Combines Customer Transaction Reports (primary IN flows) and User
Transaction Reports (contras — MP + ChannelWallet To Bank Transfer → OUT).
Format-tolerantly parses each row's date; unparseable rows pass through
tagged with `audit_flag = UNPARSEABLE_DATE` (Joash, 2026-05-20).

Reuses `core.parsers._read_airtel_csv_flexible` for the unquoted-comma
quirk in the Reference No. column (BSR-specific historical issue).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from core.parsers import _read_airtel_csv_flexible, identify_airtel_csv_type
from parsers._dates import parse_date
from parsers.types import DIRECTION_IN, DIRECTION_OUT, NormalizedRecord


# Customer report: e.g. "24-MAR-2026  18:35:57" (two spaces between date and time).
_AIRTEL_CUSTOMER_DATE_FORMATS = (
    "%d-%b-%Y  %H:%M:%S",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y",
)

# User report: e.g. "04-APR-26" (two-digit year, date only).
_AIRTEL_USER_DATE_FORMATS = (
    "%d-%b-%y",
    "%d-%b-%Y",
)

# Header offset for both flavours of Airtel CSV (verified against samples).
_AIRTEL_SKIPROWS = 5

# Service-name substring that identifies a contra (MP from User report).
_CONTRA_SERVICE_NAME_FRAGMENT = "channelwallet to bank transfer"


def parse(path: Path) -> list[NormalizedRecord]:
    p = Path(path)
    csv_type = identify_airtel_csv_type(p)
    if csv_type == "customer":
        return _parse_customer(p)
    if csv_type == "user":
        return _parse_user_contras(p)
    return []


def _parse_customer(path: Path) -> list[NormalizedRecord]:
    df = _read_airtel_csv_flexible(path, skiprows=_AIRTEL_SKIPROWS)
    df.columns = df.columns.str.strip()
    source = path.name

    records: list[NormalizedRecord] = []
    if df.empty:
        return records

    for idx, row in df.iterrows():
        amount = _to_decimal(row.get("Transaction Amount"))
        if amount == 0:
            continue

        date_val, flag = parse_date(
            row.get("Transaction Date & Time"),
            _AIRTEL_CUSTOMER_DATE_FORMATS,
            source_file=source, row_index=int(idx), field_name="Transaction Date & Time",
        )

        records.append(NormalizedRecord(
            source_file=source,
            date=date_val,
            txn_id=_normalize_airtel_id(row.get("Transaction ID")),
            amount=abs(amount),
            direction=DIRECTION_IN,
            counterparty=_stripped(row.get("Payer User Name")),
            txn_type=_stripped(row.get("Service Type")),
            raw={k: _stringify(v) for k, v in row.items()},
            audit_flag=flag,
        ))
    return records


def _parse_user_contras(path: Path) -> list[NormalizedRecord]:
    df = _read_airtel_csv_flexible(path, skiprows=_AIRTEL_SKIPROWS)
    df.columns = df.columns.str.strip()
    source = path.name

    records: list[NormalizedRecord] = []
    if df.empty or "Service Name" not in df.columns:
        return records

    for idx, row in df.iterrows():
        txn_type = _stripped(row.get("Transaction Type"))
        service = _stripped(row.get("Service Name")).lower()
        # Only MP + ChannelWallet To Bank Transfer rows are contras; everything
        # else in the User report would be a duplicate of a Customer row.
        if txn_type != "MP" or _CONTRA_SERVICE_NAME_FRAGMENT not in service:
            continue

        amount = _to_decimal(row.get("Transaction Amount"))
        if amount == 0:
            continue

        date_val, flag = parse_date(
            row.get("Transaction Date and Time"),
            _AIRTEL_USER_DATE_FORMATS,
            source_file=source, row_index=int(idx), field_name="Transaction Date and Time",
        )

        records.append(NormalizedRecord(
            source_file=source,
            date=date_val,
            txn_id=_normalize_airtel_id(row.get("Transaction ID")),
            amount=abs(amount),
            direction=DIRECTION_OUT,
            counterparty=_stripped(row.get("Receiver Msisdn")),
            txn_type="Contra",
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


def _normalize_airtel_id(value) -> str:
    """Strip + recover from scientific notation (e.g. 1.43e+11 → '143000000000')."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s:
        return ""
    if "e" in s.lower():
        try:
            return str(int(float(s)))
        except (ValueError, OverflowError):
            return s
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except (ValueError, OverflowError):
        pass
    return s


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
