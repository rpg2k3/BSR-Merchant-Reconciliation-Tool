# BSR Merchant Reconciliation Tool

Bunyonyi Safaris Resort — MTN & Airtel merchant transaction reconciliation desktop app for Linux.

Offline PyQt6 application that consolidates mobile money merchant statements and reconciles them against Karibu HMS ledger reports, producing audit-ready Excel outputs with match status, confidence scoring, and anomaly flagging.

## Quick Start (run from source)

```bash
git clone https://github.com/rpg2k3/BSR-Merchant-Reconciliation-Tool.git
cd BSR-Merchant-Reconciliation-Tool
pip install pyqt6 pandas openpyxl numpy anthropic
python main.py
```

## Build & Install (standalone app)

### 1. Build executable

```bash
./build.sh
```

### 2. Test the build

```bash
./dist/BSR_Recon/BSR_Recon
```

### 3. Install to system (adds to apps menu)

```bash
./install.sh
```

### 4. Uninstall

```bash
./uninstall.sh
```

## Folder Structure

```
Transactions/MTN/        <- Drop MTN .csv files here
Transactions/Airtel/     <- Drop Airtel .csv files here
Reports/Karibu/MTN/      <- Drop Karibu MTN ledger exports here
Reports/Karibu/Airtel/   <- Drop Karibu Airtel ledger exports here
Statements/              <- Master consolidated statements (auto-managed)
Reconciliation/          <- Reconciliation output (auto-generated)
Backups/                 <- Auto-created backups before every update
```

## Daily Workflow

1. Download new transaction CSVs from MTN and Airtel portals
2. Download new Karibu ledger exports for MTN Money and Airtel Money
3. Open the app -> Upload Files tab -> upload all new files
4. Click Update MTN Statement -> Update Airtel Statement
5. Click Reconcile MTN -> Reconcile Airtel
6. Open Reconciliation/ folder to review Excel outputs

## Optional AI Analysis

Enter a Claude API key in Settings to enable AI-powered audit narrative after reconciliation.
