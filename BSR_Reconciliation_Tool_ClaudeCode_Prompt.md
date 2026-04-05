# Claude Code Prompt — BSR Merchant Reconciliation Tool
## Bunyonyi Safaris Resort | PyQt6 Desktop App | Linux Kubuntu

---

## PROJECT OVERVIEW

Build a **PyQt6 offline desktop application** for Bunyonyi Safaris Resort (BSR) that automates:
1. Consolidating and updating MTN and Airtel merchant transaction statements
2. Reconciling those statements against Karibu HMS ledger reports
3. Producing audit-ready Excel outputs with match status, confidence scoring, and anomaly flagging

The app must be fully offline (no internet required for core functions). An **optional Claude AI API key** can be entered in settings to enable AI-powered anomaly analysis on reconciliation results.

---

## TECH STACK

- **Language**: Python 3.10+
- **GUI**: PyQt6
- **Data processing**: pandas, openpyxl, numpy
- **Optional AI**: Anthropic Python SDK (`anthropic`) — only loaded if API key is set
- **Platform**: Linux Kubuntu (desktop app, `.py` entry point, no packaging required initially)
- **Install**: All dependencies via `pip install pyqt6 pandas openpyxl numpy anthropic`

---

## FOLDER STRUCTURE (fixed, enforced by the app)

The app works against a single **working directory** the user selects on first launch. The structure inside must be:

```
WorkingDir/
├── Transactions/
│   ├── MTN/          ← raw .csv exports from MTN merchant portal
│   └── Airtel/       ← raw .csv exports from Airtel merchant portal (Customer + User reports)
├── Statements/
│   ├── BSR_MTN_Merchant_Transactions.xlsx      ← master consolidated MTN statement
│   └── BSR_Airtel_Merchant_Transactions.xlsx   ← master consolidated Airtel statement
├── Reports/
│   └── Karibu/
│       ├── MTN/      ← Karibu HMS ledger .csv exports for MTN Money account
│       └── Airtel/   ← Karibu HMS ledger .csv exports for Airtel Money account
├── Reconciliation/
│   ├── BSR_MTN_Reconciliation.xlsx
│   └── BSR_Airtel_Reconciliation.xlsx
└── Backups/          ← auto-created timestamped backups before any write operation
```

---

## DATA FORMATS (critical — hardcode these parsers)

### MTN Transactions CSV (from MTN merchant portal)
- Standard CSV, no header rows to skip
- Columns: `Id, External id, Date, Status, Type, Provider category, From, From account, From name, From handler name, To, To account, To name, To handler name, To message, Initiated by, ..., Amount, Currency, Balance, ...` (57 columns)
- `Date` format: `YYYY-MM-DD HH:MM:SS`
- `Amount`: numeric, **negative = contra/withdrawal** (e.g. `-4300000`)
- Dedup key: `Id` column (string, ~11 digits)

### Airtel Transactions CSV (two report types from Airtel portal)

**Customer Transaction Report** (primary — use this for statement updates):
- Skip first 5 rows (title block), row 6 is the header
- Header: `Record No, Transaction ID, Reference No., Transaction Date & Time, Payer MFS Provider, ..., Transaction Amount, ..., Transaction Status, ...` (33 columns)
- `Transaction Date & Time` format: `DD-MMM-YYYY  HH:MM:SS` (e.g. `21-MAR-2026  19:57:32`)
- `Transaction ID`: **may appear in scientific notation** (e.g. `1.42593E+11`) — always normalize to full integer string
- Dedup key: normalized `Transaction ID`
- Warning: IDs in scientific notation lose last ~5 digits of precision — always cross-check by date + amount + payer name before deduplicating

**User Transaction Report** (secondary — use for contra/wallet-to-bank transfers):
- Skip first 6 rows, row 7 is the header
- Header: `S. No., Transaction ID, Sender Msisdn, Transaction Amount, Transaction Date and Time, Transaction Type, Receiver Msisdn, Service Name, Transaction Status, ...`
- `Transaction Date and Time` format: `DD-MMM-YY` (e.g. `23-MAR-26`)
- Transaction Type `MP` with `Service Name = ChannelWallet To Bank Transfer` = **contra entry**
- Transaction Type `MR` = merchant receipt, `SCP` = service charge (ignore SCP rows)

### Consolidated Statement Excel (Statements folder)
- Sheet name: `MTN Transactions` (MTN) or `All Transactions` (Airtel)
- Row 0: banner/title string (merged cells)
- Row 1: column headers
- Data from row 2 onwards
- MTN date format stored as datetime
- Airtel date format stored as datetime (Transaction Date) + separate Transaction Time string column

### Karibu HMS Ledger CSV (Reports/Karibu)
- Skip first 2 rows (title `Ledger statement` + blank line), row 3 is the header
- Header: `Date, Account, Narration, DR, CR, Balance` (quoted CSV)
- First data row may be `Opening Balance` — skip it
- `Date` format: `YYYY-MM-DD`
- `DR`: debit = money received into ledger (positive receipts to match)
- `CR`: credit = money out (contras, refunds, adjustments) — do NOT use for receipt matching
- Narration contains free text: POS close day postings, accommodation payments, contra entries
- Multiple files per channel — combine chronologically, dedup by date+narration+DR amount

---

## MODULE 1 — STATEMENT UPDATER

### Function: `update_statement(channel: str)`
channel = `"MTN"` or `"Airtel"`

**Steps:**
1. **Backup** current statement Excel to `Backups/` with timestamp suffix before any write
2. **Load** current consolidated statement from `Statements/`
3. **Scan** all CSV files in `Transactions/{channel}/`
4. **Parse** each CSV according to the format rules above
5. **Normalize IDs**: for Airtel, convert scientific notation to full integer string using `str(int(float(val)))` — if precision loss is detected (normalized ID doesn't exactly match any existing full ID), cross-check by date ± 1 day + amount before treating as new
6. **Deduplicate**: identify net-new rows not already in the consolidated statement by ID
7. **Append** net-new rows, preserving all original columns
8. **Sort** chronologically by date
9. **Re-number** Record No / row numbers
10. **Update banner** row 0 with new totals, date range, and updated date
11. **Save** updated statement back to `Statements/`
12. **Report** how many rows were added, date range covered, any skipped rows

**MTN-specific**: negative Amount rows (contras) are kept in statement — flag them visually but do not exclude.

**Airtel-specific**: Customer Transaction Report is primary source. User Transaction Report provides contra entries (Type=MP, ChannelWallet To Bank Transfer) — parse and add those as separate rows tagged as `Contra` in a `Transaction Type` column. Merge both report types before deduplication.

---

## MODULE 2 — RECONCILIATION ENGINE

### Function: `reconcile(channel: str)`
channel = `"MTN"` or `"Airtel"`

**Steps:**
1. **Backup** current reconciliation Excel if it exists
2. **Load** consolidated statement from `Statements/`
3. **Load and combine** all Karibu CSV files from `Reports/Karibu/{channel}/` chronologically
4. **Filter** Karibu to DR > 0 rows only (positive receipts) for matching
5. **Run matching passes** in order (stop at first match per row):

```
Pass 1 — Exact: same amount, same date (0 days apart)         → Confidence 100%
Pass 2 — Exact: same amount, date within ±1 day               → Confidence 90%
Pass 3 — Exact: same amount, date within ±2 days              → Confidence 80%
Pass 4 — Lumpsum K→S: one Karibu DR = sum of multiple stmt rows, same date   → Confidence 60%
Pass 5 — Lumpsum K→S: one Karibu DR = sum of multiple stmt rows, ±2 days     → Confidence 45%
Pass 6 — Lumpsum S→K: one stmt amount = sum of multiple Karibu DRs, same date → Confidence 55%
Pass 7 — Amount only: same amount, any date difference                         → Confidence 40%
```

For lumpsum matching, use a greedy subset-sum algorithm within the date window. Mark ALL rows involved in a lumpsum match with the same confidence and cross-reference index.

6. **Label unmatched**:
   - Karibu rows with no match → `Not in Statement`
   - Statement rows with no match → `Not in Karibu`

7. **Output two sheets per workbook**:

**Sheet 1 — Karibu Report** (source = Karibu ledger, one row per Karibu DR entry):
```
Date | Account | Narration | DR (UGX) | CR (UGX) | Balance | Status | Match Type | Confidence | Matched Ref | Audit Flag | Comments
```

**Sheet 2 — Merchant Statement** (source = consolidated statement):

*MTN:*
```
Date | Transaction ID | Payer Name | Amount (UGX) | Tx Status | Status | Match Type | Confidence | Matched Ref | Audit Flag | Comments
```

*Airtel:*
```
Date | Transaction ID | Payer Name | Amount (UGX) | Reference | Tx Status | Status | Match Type | Confidence | Matched Ref | Audit Flag | Comments
```

**Status column values**: `Matched` | `Not in Statement` | `Not in Karibu`
**Match Type values**: `Exact` | `Lumpsum` | `Amount Only` | `—`
**Confidence**: percentage string e.g. `100%`, `60%`, `—`
**Matched Ref**: index or ID of the matched row(s) on the other side
**Audit Flag**: populated by Module 3 anomaly detection
**Comments**: blank — for manual auditor notes (preserved across re-runs if file already exists)

---

## MODULE 3 — ANOMALY DETECTION & AUDIT FLAGS

Run after reconciliation. Scan both sheets and flag the following in the `Audit Flag` column:

| Flag | Trigger Condition |
|------|------------------|
| `UNMATCHED_HIGH_VALUE` | Unmatched row with amount ≥ 500,000 UGX |
| `CONTRA_NOT_IN_KARIBU` | Negative MTN amount or Airtel contra (Type=MP) not reflected in Karibu CR |
| `DUPLICATE_AMOUNT_SAME_DAY` | Same amount appears 2+ times on the same date in statement |
| `DATE_GAP` | No transactions recorded for 3+ consecutive days in either source (excluding weekends) |
| `LARGE_SINGLE_PAYMENT` | Single payment ≥ 1,000,000 UGX (flag for review, not necessarily wrong) |
| `LOW_CONFIDENCE_MATCH` | Matched but confidence ≤ 45% |
| `KARIBU_ONLY_REPEATED_NARRATION` | Unmatched Karibu row with same narration appears on multiple dates (possible double-posting) |
| `STMT_PAYER_HIGH_FREQUENCY` | Same payer name appears 5+ times in a single month |

Flag logic must be purely code-based (no AI required). Flags are comma-separated if multiple apply.

### Optional AI Analysis (if API key is set):
After anomaly flagging, if a Claude API key is configured, send a structured JSON summary of all flagged rows to `claude-sonnet-4-20250514` with a system prompt instructing it to act as a hotel internal auditor and return:
- A plain-English summary of the most significant anomalies
- Any patterns suggesting systematic errors vs one-off discrepancies  
- Prioritized list of items needing immediate investigation

Display this AI narrative in a separate **Audit Narrative** panel in the UI. Save it as a `.txt` file alongside the reconciliation output.

---

## MODULE 4 — DASHBOARD SUMMARY SHEET

Add a third sheet `Dashboard` to each reconciliation workbook:

```
BSR {Channel} Reconciliation Dashboard
Period: {start} – {end}     Generated: {date}

STATEMENT SUMMARY
  Total transactions:        {n}
  Total received (UGX):      {sum of positive amounts}
  Total contras (UGX):       {sum of negative/contra amounts}
  Net balance:               {received - contras}
  Date range:                {min date} – {max date}

KARIBU SUMMARY  
  Total ledger entries (DR): {n}
  Total DR value (UGX):      {sum}
  Total CR/contra (UGX):     {sum}
  Date range:                {min date} – {max date}

RECONCILIATION RESULTS
  Matched:                   {n} rows  ({pct}%)
  Not in Statement:          {n} rows  ({value} UGX)
  Not in Karibu:             {n} rows  ({value} UGX)
  Unreconciled variance:     {UGX value}

MATCH QUALITY
  100% confidence:           {n} rows
  80-99% confidence:         {n} rows
  50-79% confidence:         {n} rows
  <50% confidence:           {n} rows

AUDIT FLAGS SUMMARY
  {flag_name}: {count} occurrences
  ...

CONTRAS
  Last contra date:          {date}
  Last contra amount (UGX):  {amount}
  Days since last contra:    {n}
  Estimated current balance: {opening + all DR - all CR}
```

---

## GUI LAYOUT

### Main Window (1024×768 minimum)
```
┌─────────────────────────────────────────────────────────┐
│  BSR Merchant Reconciliation Tool        [Settings ⚙]   │
│  Working Directory: /path/to/folder      [Change]        │
├──────────────┬──────────────────────────────────────────┤
│  ACTIONS     │  LOG / OUTPUT PANEL                       │
│              │                                           │
│  [Update MTN │  > Scanning Transactions/MTN/...          │
│   Statement] │  > Found 3 new rows (Mar 23-24)           │
│              │  > Backup saved: Backups/MTN_20260326...  │
│  [Update     │  > Statement updated: 653 total rows      │
│   Airtel     │  > ✓ Done                                 │
│   Statement] │                                           │
│              │                                           │
│  [Reconcile  │                                           │
│   MTN]       │                                           │
│              │                                           │
│  [Reconcile  │                                           │
│   Airtel]    │                                           │
│              │                                           │
│  [Run Both]  │                                           │
│              │                                           │
│  ──────────  │                                           │
│              │                                           │
│  STATUS      │                                           │
│  MTN Stmt:   │                                           │
│  653 rows    │                                           │
│  Last: 24Mar │                                           │
│              │                                           │
│  Airtel Stmt:│                                           │
│  122 rows    │                                           │
│  Last: 26Mar │                                           │
│              │                                           │
│  [Open       │                                           │
│   Output     │  ─────── AI AUDIT NARRATIVE ──────────── │
│   Folder]    │  (shown here if API key is set and        │
│              │   reconciliation has been run)            │
└──────────────┴──────────────────────────────────────────┘
```

### Settings Dialog
- Working directory selector
- Claude API key field (password-masked, saved to `~/.bsr_recon_config.json`)
- Date tolerance for matching (default: 2 days, adjustable 0–5)
- High-value threshold for flags (default: 500,000 UGX)
- Large payment threshold (default: 1,000,000 UGX)

### Progress
- Use `QProgressBar` + threaded workers (`QThread`) so UI never freezes during processing
- Log panel uses `QTextEdit` (read-only) with colour-coded lines: green=success, red=error, amber=warning, white=info

---

## EXCEL OUTPUT STYLING

Consistent with existing BSR files:

| Element | MTN | Airtel |
|---------|-----|--------|
| Header bg | `#1F6B2E` (dark green) | `#C0392B` (red) |
| Header text | White, Arial 10, bold | White, Arial 10, bold |
| Data font | Arial 9 | Arial 9 |
| Matched rows | `#D6EFDD` (light green) | `#D6EFDD` |
| Not in Statement | `#FDECEA` (light red) | `#FDECEA` |
| Not in Karibu | `#FFF3CD` (amber) | `#FFF3CD` |
| Flagged rows | `#FCE4EC` (pink) | `#FCE4EC` |
| Zebra (even rows) | `#F0F7F0` | `#FDF2F0` |
| Amount columns | `#,##0` format, right-aligned | same |
| Date columns | `DD/MM/YYYY` | same |
| Freeze panes | Row 3 (banner + header frozen) | same |
| Banner row | Merged across all cols, bold italic | same |

Status text colours (in Status column cells):
- `Matched` → `#1A6B2E`
- `Not in Statement` → `#C0392B`  
- `Not in Karibu` → `#B7791A`

Confidence text colours:
- 90–100% → `#1A6B2E`
- 70–89%  → `#2471A3`
- 50–69%  → `#B7791A`
- <50%    → `#C0392B`

Audit Flag cells → orange background `#FF9800`, bold black text

---

## BACKUP STRATEGY

Before **any** write operation (statement update or reconciliation output):
1. Create `Backups/` if it doesn't exist
2. Copy the file being overwritten to `Backups/{original_name}_{YYYYMMDD_HHMMSS}.xlsx`
3. Log the backup path to the UI
4. Keep only the last 10 backups per file (auto-delete oldest)

---

## COMMENTS COLUMN PRESERVATION

The `Comments` column in reconciliation sheets is for manual auditor notes. When re-running reconciliation:
1. Load the existing reconciliation file if present
2. Extract any non-empty Comments values keyed by Transaction ID / Karibu Date+Narration+Amount
3. After generating new reconciliation output, re-apply preserved comments to matching rows
4. This ensures re-runs don't wipe investigator notes

---

## ERROR HANDLING

- Missing folder → create it, log warning
- Unreadable CSV → skip file, log error with filename, continue
- Airtel scientific notation ID → normalize, log if precision loss detected
- Empty Transactions folder → show warning, do not crash
- Statement file missing → prompt user to create it or select an existing one
- All errors shown in log panel in red, never crash the app

---

## FILE: `main.py` (entry point)

```python
# Run with: python main.py
# Dependencies: pip install pyqt6 pandas openpyxl numpy anthropic
```

Structure the project as:
```
bsr_recon/
├── main.py                  # Entry point, launches MainWindow
├── ui/
│   ├── main_window.py       # MainWindow (QMainWindow)
│   └── settings_dialog.py   # SettingsDialog (QDialog)
├── core/
│   ├── config.py            # Config load/save (~/.bsr_recon_config.json)
│   ├── parsers.py           # All CSV/Excel parsing functions
│   ├── updater.py           # Module 1 — statement updater
│   ├── reconciler.py        # Module 2 — reconciliation engine
│   ├── anomalies.py         # Module 3 — anomaly/audit flag detection
│   └── ai_analyst.py        # Module 3b — optional Claude API analysis
├── utils/
│   ├── excel_writer.py      # openpyxl Excel output with BSR styling
│   └── backup.py            # Backup management
└── workers/
    └── qt_workers.py        # QThread workers for non-blocking UI
```

---

## SAMPLE DATA CONTEXT (for Claude Code to understand field semantics)

**MTN negative amount row** (contra):
```
Id: 39417651366, Date: 2026-03-23 11:00:03, Amount: -4300000,
Status: Successful, From name: BUNYONYI SAFARIS LIMITED BUNYONYI SAFARIS LIMITED
```
→ This is a wallet-to-bank withdrawal. Keep in statement, tag as Contra. Match against Karibu CR entry.

**Airtel contra** (from User Transaction Report):
```
Transaction ID: 143452191244, Amount: 3700000, Date: 23-MAR-26,
Transaction Type: MP, Service Name: ChannelWallet To Bank Transfer
```
→ Same as MTN contra but sourced from User report, not Customer report.

**Karibu lumpsum example** (MTN, 2026-01-01):
```
Karibu DR row 1: 2026-01-01 | Main Restaurant POS close day posting | 1,544,000
Karibu DR row 2: 2026-01-01 | Garden Bar POS close day posting       |   530,000
Karibu DR row 3: 2026-01-01 | Deposit payment on BBQ                 |   500,000
Total Karibu DR: 2,574,000

Statement has 25 individual transactions on 2026-01-01 totalling 2,784,000
→ Partial lumpsum match at 2,574,000 — the 210,000 gap is unexplained
```
This is the core complexity of the reconciliation.

---

## DELIVERABLE

A working, runnable Python project in the structure above. The app must:
- Launch with `python main.py`
- Work offline on Kubuntu with PyQt6
- Process the exact file formats described
- Produce the Excel outputs described
- Be robust to missing/partial files without crashing
- Have clear, readable code with module docstrings

Start with `main.py` and `core/parsers.py` first — the parsers are the most critical foundation.
