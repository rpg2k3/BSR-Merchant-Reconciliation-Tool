"""Parser tests against the checked-in samples/ fixtures."""

from __future__ import annotations

from decimal import Decimal

import pytest

from parsers import DIRECTION_IN, DIRECTION_OUT, NormalizedRecord
from parsers import karibu_ledger_csv, momo_agent_xlsx


# ---------- Karibu Petty Cash ledger ----------

def test_karibu_petty_cash_filter_row_count(karibu_petty_cash_csv):
    """Filtered to the PC - Petty Cash UGX account should yield 686 records.

    Spec §10 originally said 691 total / 690 filtered, but the actual file
    has 688 rows after the 2-row header is skipped; of those, 686 carry
    `Account == 'PC - Petty Cash UGX'` (the other two are an Opening Balance
    row that the parser drops by design and a trailing Totals row with no
    parseable date). Asserting the real shape — if the spec doc gets refreshed
    later, update both places together.
    """
    records = karibu_ledger_csv.parse(
        karibu_petty_cash_csv, karibu_account="PC - Petty Cash UGX"
    )
    assert len(records) == 686


def test_karibu_records_have_normalized_shape(karibu_petty_cash_csv):
    records = karibu_ledger_csv.parse(
        karibu_petty_cash_csv, karibu_account="PC - Petty Cash UGX"
    )
    sample = records[0]
    assert isinstance(sample, NormalizedRecord)
    assert sample.source_file == "Ledger_statement.csv"
    assert sample.direction in (DIRECTION_IN, DIRECTION_OUT)
    assert isinstance(sample.amount, Decimal)
    assert sample.amount > 0
    assert sample.txn_type in {"DR", "CR"}


def test_karibu_filter_excludes_other_accounts(karibu_petty_cash_csv):
    all_records = karibu_ledger_csv.parse(karibu_petty_cash_csv)
    petty = karibu_ledger_csv.parse(
        karibu_petty_cash_csv, karibu_account="PC - Petty Cash UGX"
    )
    assert len(petty) <= len(all_records)


# ---------- MoMo Agent xlsx ----------

def test_momo_agent_total_record_count(momo_agent_xlsx):
    records = momo_agent_xlsx_parse(momo_agent_xlsx)
    assert len(records) == 354


def test_momo_agent_transaction_type_distribution(momo_agent_xlsx):
    records = momo_agent_xlsx_parse(momo_agent_xlsx)
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r.txn_type] = by_type.get(r.txn_type, 0) + 1
    assert by_type == {"CASH_IN": 320, "TRANSFER": 20, "DEPOSIT": 14}


def test_momo_agent_direction_mapping(momo_agent_xlsx):
    records = momo_agent_xlsx_parse(momo_agent_xlsx)
    cash_in_directions = {r.direction for r in records if r.txn_type == "CASH_IN"}
    transfer_directions = {r.direction for r in records if r.txn_type == "TRANSFER"}
    deposit_directions = {r.direction for r in records if r.txn_type == "DEPOSIT"}
    assert cash_in_directions == {DIRECTION_IN}
    assert deposit_directions == {DIRECTION_IN}
    assert transfer_directions == {DIRECTION_OUT}


def test_momo_agent_amounts_positive(momo_agent_xlsx):
    records = momo_agent_xlsx_parse(momo_agent_xlsx)
    assert all(isinstance(r.amount, Decimal) for r in records)
    assert all(r.amount > 0 for r in records), \
        "Amount must be normalised to positive; sign is carried by direction."


def test_momo_agent_transaction_ids_preserved_as_strings(momo_agent_xlsx):
    records = momo_agent_xlsx_parse(momo_agent_xlsx)
    # The sample's first row has Transaction ID = '40714775047'. Just check
    # that every txn_id is a str and at least one has 11+ digits — the bug we
    # want to catch is float-precision loss in large MoMo IDs.
    assert all(isinstance(r.txn_id, str) for r in records)
    assert any(len(r.txn_id) >= 11 and r.txn_id.isdigit() for r in records)


# Tiny shim so the test names stay readable when the module name itself is
# `momo_agent_xlsx` (would otherwise shadow the fixture).
def momo_agent_xlsx_parse(path):
    return momo_agent_xlsx.parse(path)
