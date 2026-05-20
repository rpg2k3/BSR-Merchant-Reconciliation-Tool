"""Shared types for the parsers package."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


DIRECTION_IN = "IN"
DIRECTION_OUT = "OUT"


@dataclass(frozen=True)
class NormalizedRecord:
    """One transaction in the canonical shape produced by every parser."""

    source_file: str
    date: datetime
    txn_id: str
    amount: Decimal
    direction: str  # DIRECTION_IN or DIRECTION_OUT
    counterparty: str
    txn_type: str
    raw: dict = field(default_factory=dict)
