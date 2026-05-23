# BUGFIX — "Stops consolidating new data at 2026-04-06"

**Reported (Joash, 2026-05-20):** *"The tool stops consolidating new data at 2026-04-06 even though newer statement files (up to 2026-05-15+) have been dropped into the source folders."*

**Affected channel:** Airtel (not MTN — see "What was NOT broken" below).
**Affected runtime file:** `~/.local/share/BSR_Recon/Statements/BSR_Airtel_Merchant_Transactions.xlsx`

---

## TL;DR

Past Airtel updater runs absorbed some transactions with a NULL `Transaction Date` (likely from a transient malformed/partial CSV upload). The current `update_airtel_statement` dedups against existing IDs without checking whether the existing row is healthy:

```python
existing_ids = set(existing_df["Transaction ID"].astype(str))
new_df = new_df[~new_df["Transaction ID"].isin(existing_ids)].copy()
```

So when the user later re-downloaded clean CSVs containing the same Transaction IDs, every clean row was rejected as a duplicate. The broken (NULL-date) rows are still there in the consolidated workbook — just invisible because they sort to the bottom by Date.

When the user sees "max date in the consolidated = 2026-04-06", that's because the visible (date-valid) rows top out there. The April 7+ data is in the file with `Transaction Date = NULL`.

**Phase 2's new consolidator structurally eliminates this class of bug** by re-scanning every CSV from source on every run and writing a fresh output, rather than incrementally appending to a stale baseline. Old NaT rows have no way to persist.

---

## What was NOT broken

- **MTN consolidation is up to date.** The MTN consolidated file currently goes from 2025-09-14 through **2026-05-17 10:36:29** — 783 rows, zero NaT, 41 rows in May. No bug here.
- **MTN/Airtel CSV date format did not change.** Oldest and newest portal exports use identical formats (MTN: `%Y-%m-%d %H:%M:%S`; Airtel Customer: `%d-%b-%Y  %H:%M:%S` with two spaces; Airtel User: `%d-%b-%y`). My initial hypothesis (silent NaT from a format change) was wrong.
- **Karibu data is not stuck due to a bug.** The latest Karibu MTN export in `Reports/Karibu/MTN/` is `MTN 1stJan to 7thApril2026.csv`; the latest Airtel export is similar. The Karibu side is just waiting for a fresher user upload, not failing to absorb existing files.

---

## Empirical evidence

### 1. Consolidated Airtel xlsx already contains the post-April-6 IDs — with NULL dates

```
=== Comparing same Transaction ID: CSV date vs Consolidated date ===
  144440142275: CSV=2026-04-06 09:50:34 | consolidated=2026-04-06 00:00:00  ✓
  144469376482: CSV=2026-04-06 17:11:38 | consolidated=2026-04-06 00:00:00  ✓
  144496155467: CSV=2026-04-06 22:23:52 | consolidated=2026-04-06 00:00:00  ✓
  144541682627: CSV=2026-04-07 17:58:53 | consolidated=NaT                  ✗
  144593994332: CSV=2026-04-08 13:05:10 | consolidated=NaT                  ✗
  145039470056: CSV=2026-04-14 18:05:33 | consolidated=NaT                  ✗
  145042658419: CSV=2026-04-14 18:44:01 | consolidated=NaT                  ✗
  145079416198: CSV=2026-04-15 10:20:19 | consolidated=NaT                  ✗
  145108407659: CSV=2026-04-15 17:52:58 | consolidated=NaT                  ✗
  145122651206: CSV=2026-04-15 20:12:12 | consolidated=NaT                  ✗
  145252958668: CSV=2026-04-17 18:30:15 | consolidated=NaT                  ✗
  145328433918: CSV=2026-04-18 18:51:07 | consolidated=NaT                  ✗
  145461422955: CSV=2026-04-20 15:35:56 | consolidated=NaT                  ✗
```

`32 / 194 rows` in the consolidated workbook have `Transaction Date = None`.

### 2. Fresh build from current CSVs would produce zero NaT rows

```
FRESH-BUILD from current CSVs only (no dedup against existing):
  Total rows: 75
  NaT dates: 0
  Date range: 2026-03-21 → 2026-05-15
```

The source CSVs are now clean. The bug is purely in the consolidated artefact; rebuilding from scratch produces correct data.

### 3. Every current CSV parses cleanly today

A sweep across all 9 MTN, 24 Airtel, and 9 Karibu CSVs reports **zero NaT date rows**. Whatever malformed CSV triggered the original NaT insertion has been replaced.

---

## Why the bug stuck

`core/updater.py:update_airtel_statement` (and the MTN equivalent) does this:

1. `parse_*_csv(f)` — strict date format with `errors="coerce"`. A row that doesn't match the expected format silently becomes `Transaction Date = NaT`.
2. `_customer_row_to_statement(row)` — copies the NaT into the new-row dict, but the Transaction ID is still valid.
3. After concat with existing + `drop_duplicates(subset=["Transaction ID"], keep="first")`, the NaT row enters the consolidated workbook.
4. **Next run with a re-downloaded clean CSV:** the line

   ```python
   new_df = new_df[~new_df["Transaction ID"].isin(existing_ids)].copy()
   ```

   drops every clean row whose ID is already present — including the one with the broken date — and the consolidated keeps the NaT version forever.

There is no validation that the existing row is healthy before treating it as "already imported".

---

## The fix

Two complementary changes (both shipping in Phase 2):

### a. Format-tolerant date parsing + WARN-don't-coerce

`parsers/mtn_merchant_csv`, `parsers/airtel_merchant_csv`, `parsers/karibu_ledger_csv`, and `parsers/momo_agent_xlsx` all switch to a small helper that:

- Tries a list of candidate formats in order.
- If none match, falls through to `dateutil.parser.parse` for permissive parsing.
- If even that fails, **logs a WARNING per unparseable row** (file + 0-indexed row + the raw value) and **drops the row** rather than returning a record with a NaT date.

No record returned by a Phase-2 parser ever has an unparseable date. This prevents the upstream condition that lets bad rows into a consolidated workbook.

### b. Phase 2 consolidator rebuilds from source on every run

The new `consolidator.py` doesn't dedup against the previous consolidated workbook — it reads every CSV/XLSX in the input folder, dedups within the parsed set, and writes a fresh output. The state cache at `~/.local/share/BSR_Recon/state/consolidator_state.json` is for performance (skip re-parsing unchanged files when nothing has changed) but the spec explicitly mandates a full re-scan every run anyway, so stale baseline data has no way to persist.

When the user first runs the Phase-2 consolidator on the Airtel inputs, the 32 broken rows will simply not be present in the new output; the rebuild picks up the clean dates from the source CSVs.

---

## Reproduction test (Phase 2 `tests/test_consolidator.py`)

```python
def test_consolidator_recovers_from_stale_nat_baseline(tmp_path):
    """If the previous consolidated workbook had a row with Transaction ID X
    and a NaT date, and a fresh source CSV now has X with a valid date, the
    Phase 2 consolidator must use the valid date — not silently keep the NaT.
    """
    # Set up: a fixture CSV with the canonical April-7 row.
    # Pre-seed Statements/{Account}/{Account} Transactions - 2026.xlsx with
    # the same ID but Transaction Date = None.
    # Run consolidator; assert the output xlsx has the valid 2026-04-07 date.
```

Plus a separate test that asserts `[parsers] WARN: dropped unparseable row` is emitted (and the bad row is NOT in the output) when the parser hits a row whose date can't be parsed by any candidate format.

---

## Notes for Joash

- After Phase 2 ships, run the new consolidator on the Airtel inputs once. The output will be a clean per-year workbook under `Statements/Airtel Merchant/Airtel Merchant Transactions - 2026.xlsx` with all April–May 2026 data correctly dated.
- The legacy flat `Statements/BSR_Airtel_Merchant_Transactions.xlsx` will be preserved as `BSR_Airtel_Merchant_Transactions_pre_migration.xlsx` by the migration script — useful if you want to diff and confirm the recovered dates.
- To get fully up-to-date Karibu data, drop a fresh Karibu export covering April 7 → today into `Reports/Karibu/{Account}/`. The Karibu side has no bug; it's just waiting for newer input.
