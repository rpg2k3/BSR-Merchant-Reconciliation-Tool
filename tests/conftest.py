"""Shared pytest fixtures.

`pytest` is dev-only — it is not bundled by `build.sh`. Run from the repo root:
    pytest tests/
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "samples"

# Ensure the repo root is importable so `import parsers`, `import config` work
# whether pytest is invoked from inside `tests/` or from the repo root.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _sample_or_skip(filename: str) -> Path:
    path = SAMPLES_DIR / filename
    if not path.exists():
        pytest.skip(
            f"sample file not found: {path}\n"
            "Drop the sample files into samples/ to enable parser tests."
        )
    return path


@pytest.fixture
def karibu_petty_cash_csv() -> Path:
    return _sample_or_skip("Ledger_statement.csv")


@pytest.fixture
def momo_agent_xlsx() -> Path:
    return _sample_or_skip("MoMo_Agent_Transaction_Report_2026-05-15.xlsx")


@pytest.fixture
def mtn_reconciliation_xlsx() -> Path:
    return _sample_or_skip("BSR_MTN_Reconciliation.xlsx")
