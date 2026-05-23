"""Pluggable parser registry.

Each module under `parsers/` exports a `parse(path, **kwargs)` function
returning `list[NormalizedRecord]`. Account YAML entries name a parser by
its module's short key (e.g. `momo_agent_xlsx`); `get_parser(name)` returns
the callable.
"""

from __future__ import annotations

from typing import Callable

from parsers.types import (
    AUDIT_UNPARSEABLE_DATE,
    DIRECTION_IN,
    DIRECTION_OUT,
    NormalizedRecord,
)

# Lazy imports to keep package import cheap and to avoid pulling pandas/openpyxl
# into every consumer.

def _karibu_ledger_csv():
    from parsers import karibu_ledger_csv
    return karibu_ledger_csv.parse


def _mtn_merchant_csv():
    from parsers import mtn_merchant_csv
    return mtn_merchant_csv.parse


def _airtel_merchant_csv():
    from parsers import airtel_merchant_csv
    return airtel_merchant_csv.parse


def _momo_agent_xlsx():
    from parsers import momo_agent_xlsx
    return momo_agent_xlsx.parse


_REGISTRY: dict[str, Callable[..., Callable]] = {
    "karibu_ledger_csv": _karibu_ledger_csv,
    "mtn_merchant_csv": _mtn_merchant_csv,
    "airtel_merchant_csv": _airtel_merchant_csv,
    "momo_agent_xlsx": _momo_agent_xlsx,
}


def get_parser(name: str) -> Callable:
    """Return the `parse` function for the named parser module."""
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(f"unknown parser {name!r}; known parsers: {known}")
    return _REGISTRY[name]()


def available_parsers() -> list[str]:
    return sorted(_REGISTRY)


__all__ = [
    "NormalizedRecord",
    "DIRECTION_IN",
    "DIRECTION_OUT",
    "AUDIT_UNPARSEABLE_DATE",
    "get_parser",
    "available_parsers",
]
