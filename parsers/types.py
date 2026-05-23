"""Shared types for the parsers package."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


DIRECTION_IN = "IN"
DIRECTION_OUT = "OUT"

# Audit flag values that parsers may attach to a NormalizedRecord. The
# consolidator surfaces flagged rows in a separate `Unparseable` sheet so
# the user can correct the source and re-upload.
AUDIT_UNPARSEABLE_DATE = "UNPARSEABLE_DATE"


@dataclass(frozen=True)
class NormalizedRecord:
    """One transaction in the canonical shape produced by every parser.

    `date` is `datetime | None` — None means the source row had a date the
    parser couldn't interpret. Those rows still flow through the pipeline
    but are marked with `audit_flag="UNPARSEABLE_DATE"` and routed to a
    review sheet by the consolidator (Joash's call 2026-05-20: don't drop
    silently, surface for human attention).
    """

    source_file: str
    date: datetime | None
    txn_id: str
    amount: Decimal
    direction: str  # DIRECTION_IN or DIRECTION_OUT
    counterparty: str
    txn_type: str
    raw: dict = field(default_factory=dict)
    audit_flag: str = ""
