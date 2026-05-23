"""Format-tolerant date parsing helper shared by all parsers.

Tries a list of explicit formats first (fastest, most predictable), then
falls through to `dateutil.parser.parse` for permissive parsing. If even
that fails, returns `(None, AUDIT_UNPARSEABLE_DATE)` and logs a WARNING.

Per Joash 2026-05-20: we do NOT silently drop rows with bad dates — they
flow through with `date=None` so the consolidator can route them to a
review sheet. See BUGFIX.md for the April-6 incident this defends against.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import pandas as pd

from parsers.types import AUDIT_UNPARSEABLE_DATE


logger = logging.getLogger("bsr_recon.parsers.dates")


def parse_date(
    value,
    formats: Iterable[str] = (),
    *,
    source_file: str = "?",
    row_index: int | None = None,
    field_name: str = "date",
) -> tuple[datetime | None, str]:
    """Parse `value` into a datetime, returning (datetime|None, audit_flag).

    Try-list order:
      1. If `value` is already a datetime/Timestamp, return it.
      2. Each explicit format in `formats`.
      3. `pd.to_datetime` with infer/permissive mode.
      4. `dateutil.parser.parse` (handles arbitrary natural-language dates).

    On total failure, returns (None, AUDIT_UNPARSEABLE_DATE) and logs a
    WARNING containing source_file, row_index, field_name, and raw value
    so the user can correct the source data.
    """
    if value is None:
        return None, AUDIT_UNPARSEABLE_DATE
    # Pandas NaN/NaT
    try:
        if pd.isna(value):
            return None, AUDIT_UNPARSEABLE_DATE
    except (TypeError, ValueError):
        pass

    if isinstance(value, datetime):
        return value, ""
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime(), ""

    s = str(value).strip()
    if not s:
        return None, AUDIT_UNPARSEABLE_DATE

    for fmt in formats:
        try:
            return datetime.strptime(s, fmt), ""
        except (ValueError, TypeError):
            continue

    # pandas can handle a wide range of formats, including weird whitespace.
    try:
        ts = pd.to_datetime(s, errors="raise")
        if pd.notna(ts):
            if hasattr(ts, "to_pydatetime"):
                return ts.to_pydatetime(), ""
            return ts, ""
    except (ValueError, TypeError):
        pass

    # Last resort: dateutil. Imported lazily because it's heavy and most
    # parses won't get this far.
    try:
        from dateutil import parser as dateutil_parser
        return dateutil_parser.parse(s), ""
    except (ValueError, TypeError, OverflowError):
        pass

    where = f"row {row_index}" if row_index is not None else "row ?"
    logger.warning(
        "unparseable %s in %s %s: %r — emitting row with audit_flag=%s",
        field_name, source_file, where, value, AUDIT_UNPARSEABLE_DATE,
    )
    return None, AUDIT_UNPARSEABLE_DATE
