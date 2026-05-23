# BSR_Recon — Architecture Upgrade & Petty Cash UGX Build Plan

> **Status:** living build plan. Updated as phases complete. Section 11 tracks phase status (✅ done / ▶ in-progress / pending).

You are working on the **BSR Merchant Reconciliation Tool** (`BSR_Recon`), a PyQt6 desktop app for **Bunyonyi Safaris Resort**. Source lives at `~/Apps/BSR-Merchant-Reconciliation-Tool` (this directory). Runtime data lives at `~/.local/share/BSR_Recon/`. The app is built with PyInstaller; rebuild with `./build.sh` (ensure `~/.local/bin` is on PATH first).

**Stack:** Python, PyQt6, openpyxl, pandas, pdfplumber, Pillow. Linux (Kubuntu). Editor `nano` is unavailable on this machine — use `sed` one-liners or direct file ops if you ever need to patch outside your normal `str_replace` flow.

**BSR branding (apply consistently across all generated files and UI):**
- Dark green `#1A4D2E` — primary
- Gold `#B8922A` — accent / amounts
- Mid green `#2D6A4F` — secondary

---

## 1. What This Tool Must Become

Today the tool reconciles MTN Merchant and Airtel Merchant statements against Karibu ledger entries. It produces an Excel workbook with `Karibu Report`, `Merchant Statement`, and `Dashboard` sheets and uses a Status / Match Type / Confidence / Audit Flag pattern that **works well and must be preserved**.

The user (Joash, MD of BSR) now needs the tool to:

1. **Handle many accounts**, not just MTN/Airtel Merchant. Each account has its own statement format. Today's new one is **Petty Cash UGX** (MTN MoMo Agent line). Tomorrow's: Stanbic UGX/USD, DFCU UGX/USD, Standard Chartered, ABSA.
2. **Treat Karibu ledger as the source of truth.** The reconciliation question is always: "does each Karibu entry have a corresponding statement transaction, and are there statement transactions Karibu missed?"
3. **Consolidate dumped raw files into clean monthly-by-year workbooks**, so the user can drop new statements / Karibu exports into folders and the tool keeps the historical record tidy.
4. **Output transaction-based reconciliation reports** — no dashboard fluff. The user's boss wants actionable correction lists, not summaries. (Keep the dashboard sheet but only as a thin summary; the value is in the per-transaction rows with Status + Audit Flag.)
5. **Stay maintainable** so adding "Stanbic UGX" later is mostly: write a parser + add a config entry. Not: rewrite the app.

---

## 2. Known Bug to Fix (Phase 2 Blocker)

The tool currently **stops consolidating new data at 2026-04-06** even though newer statement files (up to 2026-05-15+) have been dropped into the source folders. Investigate the existing code paths for:

- A persisted "last processed date" or "last processed file" state file (likely under `~/.local/share/BSR_Recon/`) that wasn't being updated.
- Dedup-key collisions causing newer entries to be silently dropped as duplicates.
- A hardcoded date cutoff or `max_date` literal somewhere in the consolidation logic.
- File modification time logic that ignores files with mtimes older than a cached pointer.

Document the root cause in a `BUGFIX.md` once found. The fix must be reproducible — write a test that ingests the April + May sample files and asserts all dates are captured.

---

## 3. Target Folder Layout (under `~/.local/share/BSR_Recon/`)

```
BSR_Recon/
├── Transactions/                    # raw statement dumps (user drops files here)
│   ├── MTN Merchant/
│   ├── Airtel Merchant/
│   └── Petty Cash UGX/              # NEW
├── Reports/
│   └── Karibu/                      # raw Karibu ledger exports
│       ├── MTN Merchant/
│       ├── Airtel Merchant/
│       └── Petty Cash UGX/
├── Statements/                      # consolidated, deduplicated, sorted output
│   ├── MTN Merchant/
│   │   ├── MTN Merchant Transactions - 2026.xlsx       (sheets: Jan..Dec)
│   │   └── MTN Merchant Karibu Ledger - 2026.xlsx      (sheets: Jan..Dec)
│   └── Petty Cash UGX/
│       ├── Petty Cash UGX Transactions - 2026.xlsx
│       └── Petty Cash UGX Karibu Ledger - 2026.xlsx
└── Reconciliation/                  # the deliverable
    ├── MTN Merchant/
    │   └── MTN Merchant Reconciliation - 2026.xlsx
    └── Petty Cash UGX/
        └── Petty Cash UGX Reconciliation - 2026.xlsx
```

Folder names match account display names exactly (so `MTN Merchant`, not `MTN`). Year is in the filename. Monthly sheets are 3-letter abbreviations: `Jan`, `Feb`, ..., `Dec`. If data spans multiple years, produce one workbook per year. There is **no** `Backups/` directory under the new layout — consolidated output lives under `Statements/{Account}/`, extending the existing `Statements/` convention.

---

## 4. Account Configuration

Externalize all account-specific logic to `config/accounts.yaml` in the repo. Example:

```yaml
accounts:
  "MTN Merchant":
    karibu_account: "MTN Money"
    statement_parser: mtn_merchant_csv
    karibu_parser: karibu_ledger_csv
    legacy_folder: "MTN"            # skip bootstrap until Phase 2 migration runs
    matching:
      date_window_days: 2
      lumpsum_window_days: 1
      amount_tolerance_ugx: 0
    notes: |
      Existing flow — preserve current behaviour exactly.

  "Airtel Merchant":
    karibu_account: "Airtel Money"
    statement_parser: airtel_merchant_csv
    karibu_parser: karibu_ledger_csv
    legacy_folder: "Airtel"
    matching:
      date_window_days: 2
      lumpsum_window_days: 1
      amount_tolerance_ugx: 0

  "Petty Cash UGX":
    karibu_account: "PC - Petty Cash UGX"
    statement_parser: momo_agent_xlsx
    karibu_parser: karibu_ledger_csv
    matching:
      date_window_days: 2
      lumpsum_window_days: 2
      amount_tolerance_ugx: 0
    karibu_only_is_normal: true
    notes: |
      Karibu DR = inflow to petty cash (cash-ins on agent line).
      Karibu CR = outflows / expenses.
      Statement: MoMo Agent transactions — CASH_IN, TRANSFER, DEPOSIT.
      Not every Karibu entry will have a MoMo line (some petty cash moves are pure cash);
      flag those as "Not in Statement" but DO NOT treat them as errors — they may be legitimate.
```

Adding a new account = appending to this YAML + (if format is new) writing one parser module. The optional `legacy_folder` field records a pre-rename short name that startup bootstrap uses to skip account-folder creation while a Phase-2-pending migration is outstanding.

---

## 5. Parser Interface (one module per format)

Each parser is a module under `parsers/` exporting a function:

```python
def parse(path: Path) -> list[NormalizedRecord]: ...
```

Where `NormalizedRecord` is a dataclass:

```python
@dataclass
class NormalizedRecord:
    source_file: str            # filename of origin
    date: datetime              # full timestamp where available
    txn_id: str                 # statement-side ID; "" if N/A
    amount: Decimal             # always positive
    direction: str              # "IN" or "OUT" relative to the account
    counterparty: str           # payer/payee name, free text
    txn_type: str               # e.g. "CASH_IN", "DEPOSIT", "TRANSFER", "Successful"
    raw: dict                   # original row as dict, for audit
```

**Parsers to ship in this build:**

| Parser module                  | Status              | Reads                                                        |
|--------------------------------|---------------------|--------------------------------------------------------------|
| `parsers/karibu_ledger_csv`    | Refactor existing   | Karibu CSV ledger export (any account)                        |
| `parsers/mtn_merchant_csv`     | Refactor existing   | MTN Merchant portal CSV export                                |
| `parsers/airtel_merchant_csv`  | Refactor existing   | Airtel Customer + User CSV exports                            |
| `parsers/momo_agent_xlsx`      | Shipped Phase 1     | MoMo Agent Transaction Detailed Report XLSX (Petty Cash UGX)  |

Module names use `_csv`/`_xlsx` to match the actual portal/export format. The original spec listed `mtn_merchant_xlsx` and `airtel_merchant_xlsx`, but the portal exports are CSV — the XLSX file is the *consolidated output* produced downstream.

**Karibu CSV reading convention** (per institutional knowledge — do not deviate):
- `skiprows=2`, manual column names `['Date','Account','Narration','DR','CR','Balance']`
- Strip commas before numeric parsing
- Date format `%Y-%m-%d`
- Skip the `Opening Balance` row (Date column will literally read "Opening Balance")
- Filter rows where `Account` matches the configured `karibu_account` exactly

**MoMo Agent XLSX format** (verified against sample):
- Sheet name: `Sheet1`
- Header in row 1 (no skiprows)
- Columns (12): `Date / Time, Transaction ID, Transaction Type, Amount, From Account, To Account, Fee, Commision Amount, TAX, Commision Receiving No., Commision Balance, Float Balance`
- Transaction types observed: `CASH_IN`, `TRANSFER`, `DEPOSIT`
- For Petty Cash reconciliation: `Date / Time` → `date`; `Transaction ID` → `txn_id` (cast to str — Transaction IDs are large ints that can lose precision); `Amount` → `amount`; `From Account` / `To Account` → `counterparty` (pick the "other" side based on direction); `Transaction Type` → `txn_type`
- Direction mapping for Petty Cash UGX agent line:
  - `CASH_IN`: customer giving cash to agent (money received by line) → IN
  - `DEPOSIT`: float deposited into the line → IN
  - `TRANSFER`: money sent out → OUT
  - When in doubt, use `From Account` vs `To Account` to determine direction (the agent line's MSISDN/account number stays constant; if it's in `From`, money is leaving; if in `To`, money is arriving)
- **Amount sign quirk:** the source exports store `TRANSFER` rows with a negative `Amount` (e.g. `-192100`). The parser normalises to `abs(amount)` so `NormalizedRecord.amount` is always positive; the sign is carried by `direction`. `DEPOSIT` rows have `From Account == False` (boolean) — treat as empty counterparty; the raw row is preserved in `NormalizedRecord.raw` for audit.

---

## 6. Consolidator Module

`consolidator.py` does this for each account, every run:

1. List all files in `Transactions/{account}/` and `Reports/Karibu/{account}/`.
2. Run the configured parsers on each new-or-modified file.
3. Concatenate all records per account, deduplicate (key: `(date, txn_id, amount, direction)` for statements; `(date, narration, dr, cr, balance)` for Karibu), sort by date.
4. Split records by year, then by month.
5. Write `{Account} Transactions - {YYYY}.xlsx` and `{Account} Karibu Ledger - {YYYY}.xlsx` to `Statements/{Account}/`, with sheets `Jan`..`Dec` (only months that have data; create empty sheets for months in the data range to keep layout consistent).
6. Apply BSR branding to headers: dark green `#1A4D2E` header row with white text, gold `#B8922A` for the amount column header, alternating white / very-light-green data rows. Freeze the header row. Add autofilter.
7. **Idempotent**: re-running with the same inputs produces the same outputs. Track processed-file fingerprints (sha256 of path+mtime+size) in `~/.local/share/BSR_Recon/state/consolidator_state.json` — but **also re-scan everything every run** so users can't get stuck (don't rely solely on the state file). The state file is for performance, not correctness.

**Critical:** The April 6 bug must not recur. If a file with newer data is dropped in, it MUST be ingested on the next run. Write a test for this.

---

## 7. Reconciler Module

`reconciler.py` for each account:

1. Reads `Statements/{Account}/{Account} Karibu Ledger - {YYYY}.xlsx` (all sheets concatenated).
2. Reads `Statements/{Account}/{Account} Transactions - {YYYY}.xlsx`.
3. Runs the matching engine.
4. Writes `Reconciliation/{account}/{Account} Reconciliation - {YYYY}.xlsx` with sheets:
   - `Karibu Report` — every Karibu entry with status / match type / confidence / matched ref / audit flag (preserve the columns from existing MTN reconciliation; see sample file `BSR_MTN_Reconciliation.xlsx`)
   - `Statement` — every statement transaction with the same status columns
   - `Dashboard` — a *thin* summary: totals, match counts, audit flag counts. Keep it under one screen. The deliverable is the two transaction sheets, not the dashboard.

**Matching engine** — preserve and reuse the existing MTN reconciliation logic:

- **Exact match**: same date, same amount → 100% confidence.
- **Lumpsum match**: one Karibu DR/CR row matches the sum of multiple statement transactions within a small date window (or vice versa) → 45–80% confidence depending on tightness.
- **Amount-only match**: amounts match within tolerance but dates drift → 40% confidence.
- **Status values**: `Matched`, `Not in Statement`, `Not in Karibu`.
- **Audit flags** (carry forward from existing implementation): `LOW_CONFIDENCE_MATCH`, `DUPLICATE_AMOUNT_SAME_DAY`, `KARIBU_ONLY_REPEATED_NARRATION`, `STMT_PAYER_HIGH_FREQUENCY`, `LARGE_SINGLE_PAYMENT`, `UNMATCHED_HIGH_VALUE`, `DATE_GAP`, `CONTRA_NOT_IN_KARIBU`.

**Petty Cash specifics**: a Karibu entry that has no matching statement record is NOT necessarily an error — many petty cash moves are pure cash, not MoMo. Mark those `Not in Statement` with a soft audit flag `PETTY_CASH_NO_STATEMENT_EXPECTED` rather than escalating. Add a config flag `karibu_only_is_normal: true` for accounts like petty cash where this is expected.

---

## 8. UI Updates (PyQt6)

The current UI is around a single MTN/Airtel reconciliation flow. Restructure to:

- **Accounts panel** (left side): list of all configured accounts from `accounts.yaml`. Each row shows account name + last consolidation date + last reconciliation date + status colour (green = up to date, amber = data dropped but not processed, red = error).
- **Detail panel** (right side): for selected account — counts of statement files / Karibu files in input folders, last run logs, three buttons: `Consolidate`, `Reconcile`, `Open Output Folder`.
- **Top bar**: `Run All` (consolidate + reconcile every account), `Add Account` (opens a wizard to create folders, edit YAML, pick a parser), `Settings`.
- Keep `QFileDialog` use minimal (known Linux issue per institutional knowledge: it may show empty folders).
- Progress feedback per phase — don't block the UI thread. Use `QThread` or `QtConcurrent` for consolidation/reconciliation runs.

---

## 9. Security — git-crypt Setup

The repo is being made private. Sensitive data files in this repo (sample statements, real reconciliation outputs if any are checked in) must be encrypted at rest on GitHub.

Steps to add as the final part of the build:

1. Install: `sudo apt install git-crypt gnupg`
2. From repo root: `git-crypt init`
3. Export and back up the symmetric key:
   ```bash
   git-crypt export-key ~/bsr_recon_gitcrypt.key
   chmod 600 ~/bsr_recon_gitcrypt.key
   ```
   Store this key somewhere safe and OFF this machine (USB drive, password manager file vault). Without it, encrypted files on GitHub are unrecoverable.
4. Create `.gitattributes` at repo root:
   ```gitattributes
   # Encrypt sample statements & any real data files
   samples/**            filter=git-crypt diff=git-crypt
   *.statement.xlsx      filter=git-crypt diff=git-crypt
   *.ledger.csv          filter=git-crypt diff=git-crypt
   *.reconciliation.xlsx filter=git-crypt diff=git-crypt
   
   # Code, configs, docs stay readable so Claude Code / collaborators can work
   *.py        !filter !diff
   *.md        !filter !diff
   *.yaml      !filter !diff
   *.yml       !filter !diff
   *.json      !filter !diff
   *.toml      !filter !diff
   *.sh        !filter !diff
   ```
5. Commit `.gitattributes`. Add the sample files (see §10) under `samples/` and commit — they'll be encrypted on push.
6. Verify with `git-crypt status` — should show files marked `encrypted`.
7. Add a section to `README.md` titled "Cloning on a new machine" explaining: clone the repo, copy the saved key file to the machine, run `git-crypt unlock ~/bsr_recon_gitcrypt.key`.

**Important:** Do NOT add the key file itself to the repo. Ensure `~/bsr_recon_gitcrypt.key` is not anywhere inside the repo working directory.

---

## 10. Sample Files for Testing

Before starting, ask the user to drop these three files into `samples/` at the repo root (the user has them locally — they were shared with me):

```
samples/
├── Ledger_statement.csv                          # Karibu Petty Cash UGX ledger (Jan–May 2026, 688 rows after skiprows=2)
├── MoMo_Agent_Transaction_Report_2026-05-15.xlsx # MoMo agent statement (Mar–May 2026, 354 rows)
└── BSR_MTN_Reconciliation.xlsx                   # existing MTN reconciliation output — REFERENCE for the format we want
```

Parser tests assert: `samples/Ledger_statement.csv` extracts **686** records filtered to `PC - Petty Cash UGX` (the other two of the 688 rows are an Opening Balance and a trailing Totals row, both correctly dropped). `samples/MoMo_Agent_Transaction_Report_2026-05-15.xlsx` extracts 354 records in CASH_IN/TRANSFER/DEPOSIT proportions 320/20/14.

These belong in `samples/` and will be git-crypt encrypted before push.

---

## 11. Phased Execution Plan

Work in this order. Stop and ask before moving between phases. After each phase, commit with a clear message.

### Phase 1 — Refactor for pluggability (no functional change) ✅ done — commit `9cff7d3`
- Created `parsers/` package: `NormalizedRecord` + four parsers (`karibu_ledger_csv`, `mtn_merchant_csv`, `airtel_merchant_csv`, `momo_agent_xlsx`). Existing parsers wrap `core.parsers.*` so the legacy flow runs byte-identical.
- Created `config/` package: `AccountConfig`, `load_accounts()`, `bootstrap_folders()`, `should_bootstrap()` (skips accounts whose `legacy_folder` still exists).
- `config/accounts.yaml` registers MTN Merchant, Airtel Merchant, Petty Cash UGX.
- `tests/` — 19 pytest tests covering registry, parser shape/counts on samples, bootstrap idempotency, legacy-folder skip logic. All pass.
- `main.py` calls `bootstrap_folders` only for Petty Cash UGX (MTN/Airtel deferred to Phase 2 post-migration).
- `BSR_Recon.spec` and `build.sh` updated for `config/`, `parsers/*`, `pyyaml`.
- `samples/` data files intentionally untracked until Phase 5 sets up git-crypt.

### Phase 2 — Consolidator + fix April 6 bug ✅ done — commit `670cf85`, hotfix `d0db531`
- Built `consolidator.py` per §6: rebuilds yearly per-month workbooks from raw source files on every run; byte-identical re-run guaranteed (pinned workbook metadata, pinned zip member timestamps, pinned `docProps/core.xml` `dcterms:created/modified`).
- Format-tolerant date parsing in `parsers/_dates.py`: tries explicit formats → pandas → dateutil; on total failure logs WARNING and returns `(None, AUDIT_UNPARSEABLE_DATE)` instead of silent NaT coercion. All four parsers route through it. Unparseable rows flow through with `date=None + audit_flag="UNPARSEABLE_DATE"` and are surfaced on a separate `Unparseable` sheet in the latest year's workbook (omitted entirely when zero rows).
- April-6 NaT bug: root cause documented in `BUGFIX.md`. Structurally eliminated — the consolidator never merges against a previous output, so stale NaT baselines have no way to persist.
- `utils/safe_write.py` pre-write check for LibreOffice `.~lock.<name>#` sibling files.
- `migrate_layout.py` one-shot script: renames `MTN/Airtel` → `MTN Merchant/Airtel Merchant` under `Transactions/` and `Reports/Karibu/`, preserves legacy flat xlsx as `*_pre_migration.xlsx`, bootstraps new folders, runs the consolidator for every configured account, removes empty `Backups/`. Idempotent; refuses to merge when both legacy and target folders exist.
- **Hotfix** (`d0db531`): the initial migrate_layout imported `core.config.WORKING_DIR`, which has a frozen-vs-source fork that resolves to the repo root when running from source. The first migration run targeted the wrong directory as a result. Fixed by defining a self-contained `DEFAULT_DATA_DIR` via `XDG_DATA_HOME`-respecting resolution (falling back to `~/.local/share/BSR_Recon/`), passing the canonical XDG path through every downstream call, and adding regression tests that assert the migration never imports `WORKING_DIR` and that `consolidate_account` has no default for its `base_dir` arg.
- 19 new pytest tests (37 total, all passing): consolidator (byte-identical re-run, monthly sheet layout, Unparseable routing, NaT-baseline recovery, dedupe semantics), migration (rename + preserve + idempotency + double-folder safety + XDG-resolution regressions), safe_write (lock check).

**Migration outcome (live data run 2026-05-23):** 9 workbooks across 3 accounts, 2,527 rows total, **zero unparseable dates**. April-6 Airtel NaT bug confirmed fixed — 32 previously-NaT rows recovered with correct dates; new `Airtel Merchant Transactions - 2026.xlsx` covers 2026-03-21 → 2026-05-15 with zero NULL-date rows.

> **Karibu coverage gap (action needed):** the latest Karibu exports under `Reports/Karibu/MTN Merchant/` and `Reports/Karibu/Airtel Merchant/` only run through **2026-04-06**. Phase 3 reconciliation for MTN Merchant and Airtel Merchant will be limited to that window until fresh Karibu exports covering April 7 → today are dropped into those folders. Petty Cash UGX Karibu coverage is up to date (through 2026-05-18).

### Phase 3 — Petty Cash UGX end-to-end
- Build `parsers/momo_agent_xlsx.py` per §5.
- Populate the `Petty Cash UGX` entry in `accounts.yaml`.
- Build `reconciler.py` per §7 (or refactor existing reconciliation code into it).
- Acceptance: running the full pipeline for Petty Cash UGX produces `Reconciliation/Petty Cash UGX/Petty Cash UGX Reconciliation - 2026.xlsx` with `Karibu Report`, `Statement`, and `Dashboard` sheets, BSR branding applied, audit flags populated, and the same column structure as the existing MTN reconciliation file.

### Phase 4 — UI updates
- Restructure the PyQt6 UI per §8.
- Add the "Add Account" wizard.
- Background-thread the long-running operations.
- Acceptance: user can select Petty Cash UGX in the UI, click `Consolidate`, click `Reconcile`, click `Open Output Folder`, and find the reconciliation file.

### Phase 5 — git-crypt + private repo
- Run the git-crypt setup per §9.
- Update README with cloning instructions.
- Verify `git-crypt status` shows samples and any data files encrypted.
- Acceptance: a fresh clone without the key shows encrypted blobs in `samples/`; unlocking with the key restores them.

### Phase 6 — (Defer; do not build yet, just stub) Claude API for PDF parsing
- Create `parsers/pdf_via_claude_api.py` as a stub that raises `NotImplementedError` with a clear message.
- Add a `claude_api_key` field to a `config/secrets.yaml` (git-crypt encrypted) with a placeholder.
- Document the future plan in `docs/pdf_parser_plan.md`: when a new bank provides only PDF statements, this parser will call Anthropic's API with the PDF as a document attachment, asking the model to extract transactions into the `NormalizedRecord` schema as JSON. Keep deferred — the user does not have an Anthropic API key yet.

---

## Phase 1 outcomes & deviations from original spec

| Item | Original spec | Actual |
|---|---|---|
| Karibu sample row count after filter | 690 records | **686** records — the other 2 rows are an Opening Balance and a trailing Totals row, both correctly dropped. The CSV body is 688 rows (after `skiprows=2`), not 691. |
| Output folder for consolidated workbooks | `Backups/{Account}/` | **`Statements/{Account}/`** — extends the existing `Statements/` convention; `Backups/` is being retired. |
| Parser module naming | `mtn_merchant_xlsx`, `airtel_merchant_xlsx` | **`mtn_merchant_csv`, `airtel_merchant_csv`** — matches the actual portal export format. |
| MoMo `Amount` sign | "always positive" | Source `TRANSFER` rows are stored as **negative** in the export; parser normalises to `abs()` with `direction = OUT` carrying the sign. |
| Auto-bootstrap | Implicit (mkdir on first launch) | **Explicit** `bootstrap_folders(account, base_dir)` in `config/__init__.py`, gated on `should_bootstrap()` so pre-Phase-2 legacy folders aren't doubled. |

---

## 12. Conventions

- **No `nano`.** Use `sed`, `tee`, or your file-editing tools.
- **PATH for builds:** `export PATH="$HOME/.local/bin:$PATH"` before `./build.sh`.
- **Excel formulas:** prefer hardcoded values over formulas; if you must use formulas with openpyxl, run `/mnt/skills/public/xlsx/scripts/recalc.py` after `wb.save()` (or replicate that script's behavior — openpyxl alone doesn't compute formulas).
- **DOCX images** (if you ever generate Word reports): pre-process RGBA PNGs to RGB-on-white via Pillow first — RGBA causes white-line artifacts in LibreOffice PDF conversion.
- **Numeric parsing from Karibu**: strip commas before casting.
- **Transaction IDs**: keep as strings; large MoMo/Airtel IDs lose precision when parsed as float.
- **Dates**: store as `datetime` internally; format to `YYYY-MM-DD` for display.
- **Money**: use `Decimal`, not `float`.
- **Logging**: write per-run logs to `~/.local/share/BSR_Recon/logs/{YYYY-MM-DD}_run.log`.
- **Commit messages**: prefix with phase number, e.g. `[Phase 2] Fix April 6 consolidation stale-state bug`.

---

## 13. Commit / Tag History

| Commit  | Phase | Description |
|---------|-------|-------------|
| `9cff7d3` | 1 ✅  | Extract parsers into pluggable package + accounts.yaml |
| `670cf85` | 2 ✅  | Consolidator + migration + safe_write + UNPARSEABLE_DATE handling |
| `d0db531` | 2 ✅  | Hotfix: migrate_layout uses canonical XDG path regardless of invocation |
