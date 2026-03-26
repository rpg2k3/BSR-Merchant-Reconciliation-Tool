# BSR Merchant Reconciliation Tool

Offline PyQt6 desktop application for Bunyonyi Safaris Resort (BSR) that automates:

1. Consolidating and updating MTN and Airtel merchant transaction statements
2. Reconciling those statements against Karibu HMS ledger reports
3. Producing audit-ready Excel outputs with match status, confidence scoring, and anomaly flagging

## Requirements

- Python 3.10+
- Linux (tested on Kubuntu)

## Installation

```bash
pip install pyqt6 pandas openpyxl numpy anthropic
```

## Usage

```bash
python main.py
```

On first launch, select the working directory containing:

```
WorkingDir/
├── Transactions/
│   ├── MTN/          ← raw CSV exports from MTN merchant portal
│   └── Airtel/       ← raw CSV exports from Airtel merchant portal
├── Statements/       ← master consolidated Excel statements
├── Reports/
│   └── Karibu/
│       ├── MTN/      ← Karibu HMS ledger CSV exports for MTN
│       └── Airtel/   ← Karibu HMS ledger CSV exports for Airtel
├── Reconciliation/   ← output reconciliation workbooks
└── Backups/          ← auto-created timestamped backups
```

## Features

- **Statement Updater** — Scans raw CSVs, deduplicates, and appends new transactions to consolidated statements
- **Reconciliation Engine** — 7-pass matching (exact, lumpsum, amount-only) with confidence scoring
- **Anomaly Detection** — 8 code-based audit flags (high-value unmatched, contras, duplicates, date gaps, etc.)
- **Optional AI Analysis** — Enter a Claude API key in Settings for AI-powered audit narrative
- **Dashboard** — Summary sheet with match quality, variance, and flag counts
- **BSR-styled Excel** — Color-coded outputs consistent with existing BSR files
