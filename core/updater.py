"""Module 1 — Statement Updater.

Consolidates new transactions from raw CSV exports into the master statement Excel files.
"""

from pathlib import Path
from datetime import datetime

import pandas as pd

from core.parsers import (
    parse_mtn_csv,
    parse_airtel_customer_csv,
    parse_airtel_user_csv,
    identify_airtel_csv_type,
    load_mtn_statement,
    load_airtel_statement,
    _normalize_airtel_id,
)
from utils.backup import create_backup
from utils.excel_writer import write_mtn_statement, write_airtel_statement


def update_mtn_statement(base_dir: Path, log_fn=None) -> dict:
    """Update MTN consolidated statement with new transactions from CSV exports.

    Returns dict with: added, total, date_range, skipped, backup_path.
    """
    def log(msg, level="info"):
        if log_fn:
            log_fn(msg, level)

    tx_dir = base_dir / "Transactions" / "MTN"
    stmt_path = base_dir / "Statements" / "BSR_MTN_Merchant_Transactions.xlsx"
    backup_dir = base_dir / "Backups"

    # Backup
    backup_path = create_backup(stmt_path, backup_dir)
    if backup_path:
        log(f"Backup saved: {backup_path}")

    # Load current statement
    if stmt_path.exists():
        existing_df, old_banner = load_mtn_statement(stmt_path)
        log(f"Loaded existing statement: {len(existing_df)} rows")
    else:
        existing_df = pd.DataFrame()
        old_banner = ""
        log("No existing statement found — creating new one", "warning")

    # Scan and parse all CSVs
    csv_files = sorted(tx_dir.glob("*.csv"))
    if not csv_files:
        log("No CSV files found in Transactions/MTN/", "warning")
        return {"added": 0, "total": len(existing_df), "date_range": "", "skipped": 0, "backup_path": backup_path}

    log(f"Scanning {len(csv_files)} CSV file(s)...")
    all_new = []
    skipped = 0
    for f in csv_files:
        try:
            df = parse_mtn_csv(f)
            log(f"  Parsed {f.name}: {len(df)} rows")
            all_new.append(df)
        except Exception as e:
            log(f"  Error reading {f.name}: {e}", "error")
            skipped += 1

    if not all_new:
        log("No valid data parsed from CSV files", "warning")
        return {"added": 0, "total": len(existing_df), "date_range": "", "skipped": skipped, "backup_path": backup_path}

    new_df = pd.concat(all_new, ignore_index=True)
    # Drop duplicates within new data
    new_df.drop_duplicates(subset=["Id"], keep="first", inplace=True)

    # Deduplicate against existing
    if not existing_df.empty:
        existing_ids = set(existing_df["Id"].astype(str))
        before = len(new_df)
        new_df = new_df[~new_df["Id"].isin(existing_ids)].copy()
        log(f"Found {before - len(new_df)} duplicate(s), {len(new_df)} new row(s)")
    else:
        log(f"All {len(new_df)} rows are new")

    added = len(new_df)

    if added > 0:
        # Append
        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined = existing_df.copy()

    # Sort chronologically
    combined.sort_values("Date", ascending=False, inplace=True)
    combined.reset_index(drop=True, inplace=True)

    # Build date range string
    valid_dates = combined["Date"].dropna()
    if not valid_dates.empty:
        min_d = valid_dates.min().strftime("%d %b %Y")
        max_d = valid_dates.max().strftime("%d %b %Y")
        date_range = f"{min_d} – {max_d}"
    else:
        date_range = "N/A"

    # Count successful
    total = len(combined)
    successful = len(combined[combined["Status"] == "Successful"]) if "Status" in combined.columns else total

    # Build positive-amount total
    if "Amount" in combined.columns:
        total_amount = combined["Amount"].clip(lower=0).sum()
        amount_str = f"{total_amount:,.0f}"
    else:
        amount_str = "N/A"

    # Update banner
    banner = (
        f"BSR MTN Merchant Transactions — Consolidated  |  "
        f"Period: {date_range.replace(' – ', ' – ')}  |  "
        f"Total transactions: {total}  |  "
        f"Successful: {successful}  |  "
        f"Total Amount (UGX): {amount_str}  |  "
        f"Updated: {datetime.now().strftime('%d %b %Y')}"
    )

    # Save
    write_mtn_statement(combined, stmt_path, banner)
    log(f"Statement updated: {total} total rows ({added} added)")
    log(f"Date range: {date_range}")

    return {
        "added": added,
        "total": total,
        "date_range": date_range,
        "skipped": skipped,
        "backup_path": backup_path,
    }


def update_airtel_statement(base_dir: Path, log_fn=None) -> dict:
    """Update Airtel consolidated statement with new transactions.

    Merges Customer Transaction Reports (primary) and User Transaction Reports (contras).
    Returns dict with: added, total, date_range, skipped, backup_path.
    """
    def log(msg, level="info"):
        if log_fn:
            log_fn(msg, level)

    tx_dir = base_dir / "Transactions" / "Airtel"
    stmt_path = base_dir / "Statements" / "BSR_Airtel_Merchant_Transactions.xlsx"
    backup_dir = base_dir / "Backups"

    # Backup
    backup_path = create_backup(stmt_path, backup_dir)
    if backup_path:
        log(f"Backup saved: {backup_path}")

    # Load current statement
    if stmt_path.exists():
        existing_df, old_banner = load_airtel_statement(stmt_path)
        log(f"Loaded existing statement: {len(existing_df)} rows")
    else:
        existing_df = pd.DataFrame()
        old_banner = ""
        log("No existing statement found — creating new one", "warning")

    # Scan and parse all CSVs
    csv_files = sorted(tx_dir.glob("*.csv"))
    if not csv_files:
        log("No CSV files found in Transactions/Airtel/", "warning")
        return {"added": 0, "total": len(existing_df), "date_range": "", "skipped": 0, "backup_path": backup_path}

    customer_dfs = []
    user_dfs = []
    skipped = 0

    for f in csv_files:
        csv_type = identify_airtel_csv_type(f)
        try:
            if csv_type == "customer":
                df = parse_airtel_customer_csv(f)
                log(f"  Parsed Customer report {f.name}: {len(df)} rows")
                customer_dfs.append(df)
            elif csv_type == "user":
                df = parse_airtel_user_csv(f)
                log(f"  Parsed User report {f.name}: {len(df)} rows")
                user_dfs.append(df)
            else:
                log(f"  Unknown CSV type: {f.name}", "warning")
                skipped += 1
        except Exception as e:
            log(f"  Error reading {f.name}: {e}", "error")
            skipped += 1

    # Process customer reports (primary source)
    new_rows = []
    if customer_dfs:
        customer_all = pd.concat(customer_dfs, ignore_index=True)
        customer_all.drop_duplicates(subset=["Transaction ID"], keep="first", inplace=True)

        # Map to statement columns
        for _, row in customer_all.iterrows():
            new_rows.append(_customer_row_to_statement(row))

    # Process user reports — extract contras (MP + ChannelWallet To Bank Transfer)
    if user_dfs:
        user_all = pd.concat(user_dfs, ignore_index=True)
        contras = user_all[
            (user_all["Transaction Type"] == "MP") &
            (user_all["Service Name"].str.contains("ChannelWallet To Bank Transfer", case=False, na=False))
        ].copy()
        if not contras.empty:
            log(f"  Found {len(contras)} contra entries from User reports")
            for _, row in contras.iterrows():
                new_rows.append(_user_contra_to_statement(row))

    if not new_rows:
        log("No new data parsed from CSV files", "warning")
        return {"added": 0, "total": len(existing_df), "date_range": "", "skipped": skipped, "backup_path": backup_path}

    new_df = pd.DataFrame(new_rows)
    # Ensure Transaction ID is string
    new_df["Transaction ID"] = new_df["Transaction ID"].astype(str)
    # Drop duplicates within new data
    new_df.drop_duplicates(subset=["Transaction ID"], keep="first", inplace=True)

    # Deduplicate against existing
    if not existing_df.empty:
        existing_ids = set(existing_df["Transaction ID"].astype(str))
        before = len(new_df)
        new_df = new_df[~new_df["Transaction ID"].isin(existing_ids)].copy()
        log(f"Found {before - len(new_df)} duplicate(s), {len(new_df)} new row(s)")
    else:
        log(f"All {len(new_df)} rows are new")

    added = len(new_df)

    if added > 0:
        # Align columns — add any missing columns from existing
        if not existing_df.empty:
            for col in existing_df.columns:
                if col not in new_df.columns:
                    new_df[col] = None
            new_df = new_df[existing_df.columns]
        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined = existing_df.copy()

    # Sort chronologically (newest first)
    combined.sort_values("Transaction Date", ascending=False, inplace=True)
    combined.reset_index(drop=True, inplace=True)

    # Re-number Record No
    combined["Record No"] = range(1, len(combined) + 1)

    # Date range
    valid_dates = combined["Transaction Date"].dropna()
    if not valid_dates.empty:
        min_d = valid_dates.min().strftime("%d %b %Y")
        max_d = valid_dates.max().strftime("%d %b %Y")
        date_range = f"{min_d} – {max_d}"
    else:
        date_range = "N/A"

    total = len(combined)
    successful = len(combined[combined.get("Transaction Status", pd.Series()) == "Transaction Success"]) if "Transaction Status" in combined.columns else total

    if "Transaction Amount" in combined.columns:
        total_amount = pd.to_numeric(combined["Transaction Amount"], errors="coerce").fillna(0).clip(lower=0).sum()
        amount_str = f"{total_amount:,.0f}"
    else:
        amount_str = "N/A"

    banner = (
        f"Airtel Merchant Transactions — Consolidated  |  "
        f"Period: {date_range}  |  "
        f"Total unique transactions: {total}  |  "
        f"Successful: {successful}  |  "
        f"Total Amount (UGX): {amount_str}  |  "
        f"Updated: {datetime.now().strftime('%d %b %Y')}"
    )

    write_airtel_statement(combined, stmt_path, banner)
    log(f"Statement updated: {total} total rows ({added} added)")
    log(f"Date range: {date_range}")

    return {
        "added": added,
        "total": total,
        "date_range": date_range,
        "skipped": skipped,
        "backup_path": backup_path,
    }


def _customer_row_to_statement(row) -> dict:
    """Map an Airtel Customer Transaction Report row to statement columns."""
    return {
        "Record No": None,  # Will be re-numbered
        "Transaction ID": str(row.get("Transaction ID", "")),
        "Reference No.": row.get("Reference No.", ""),
        "Transaction Date": row.get("Transaction Date"),
        "Transaction Time": row.get("Transaction Time", ""),
        "Payer MFS Provider": row.get("Payer MFS Provider", ""),
        "Payer Payment Instrument": row.get("Payer Payment Instrument", ""),
        "Payer Wallet Type/Linked Bank": row.get("Payer Wallet Type/Linked Bank", ""),
        "Payer Bank Account No/Mobile No": row.get("Payer Bank Account No/Mobile No", ""),
        "Payer User Name": row.get("Payer User Name", ""),
        "Sender Grade": row.get("Sender Grade", ""),
        "Payer Nick Name": row.get("Payer Nick Name", ""),
        "Payer Mobile Number": row.get("Payer Mobile Number", ""),
        "Payer Category": row.get("Payer Category", ""),
        "Payee MFS Provider": row.get("Payee MFS Provider", ""),
        "Payee Payment Instrument": row.get("Payee Payment Instrument", ""),
        "Payee Wallet Type/Linked Bank": row.get("Payee Wallet Type/Linked Bank", ""),
        "Receiver Mobile Number": row.get("Receiver Mobile Number", ""),
        "Payee Bank Account No/Mobile No": row.get("Payee Bank Account No/Mobile No", ""),
        "Receiver Category": row.get("Receiver Category", ""),
        "Receiver Grade": row.get("Receiver Grade", ""),
        "Payee User Name": row.get("Payee User Name", ""),
        "Payee Nick Name": row.get("Payee Nick Name", ""),
        "Service Type": row.get("Service Type", ""),
        "Transaction Status": row.get("Transaction Status", ""),
        "Transaction Amount": row.get("Transaction Amount"),
        "Payer Previous Balance": row.get("Payer Previous Balance", ""),
        "Payer Post Balance": row.get("Payer Post Balance", ""),
        "Payee Pre Balance": row.get("Payee Pre Balance", ""),
        "Payee Post Balance": row.get("Payee Post Balance", ""),
        "Total Service Charge": row.get("Total Service Charge", ""),
        "External Transaction id": row.get("External Transaction id", ""),
        "Receiver_name": row.get("Receiver_name", ""),
        " Reason": row.get(" Reason", ""),
    }


def _user_contra_to_statement(row) -> dict:
    """Map an Airtel User Transaction Report contra row to statement columns."""
    return {
        "Record No": None,
        "Transaction ID": str(row.get("Transaction ID", "")),
        "Reference No.": row.get("Reference Number", ""),
        "Transaction Date": row.get("Transaction Date"),
        "Transaction Time": "",
        "Payer MFS Provider": "Airtel",
        "Payer Payment Instrument": "",
        "Payer Wallet Type/Linked Bank": "",
        "Payer Bank Account No/Mobile No": row.get("Sender Msisdn", ""),
        "Payer User Name": "",
        "Sender Grade": "",
        "Payer Nick Name": "",
        "Payer Mobile Number": row.get("Sender Msisdn", ""),
        "Payer Category": "",
        "Payee MFS Provider": "Airtel",
        "Payee Payment Instrument": "",
        "Payee Wallet Type/Linked Bank": "",
        "Receiver Mobile Number": row.get("Receiver Msisdn", ""),
        "Payee Bank Account No/Mobile No": "",
        "Receiver Category": "",
        "Receiver Grade": "",
        "Payee User Name": "",
        "Payee Nick Name": "",
        "Service Type": "Contra",
        "Transaction Status": row.get("Transaction Status", ""),
        "Transaction Amount": row.get("Transaction Amount"),
        "Payer Previous Balance": row.get("Previous Balance", ""),
        "Payer Post Balance": row.get("Post Balance", ""),
        "Payee Pre Balance": "",
        "Payee Post Balance": "",
        "Total Service Charge": "",
        "External Transaction id": row.get("external_transaction_id", ""),
        "Receiver_name": "",
        " Reason": "ChannelWallet To Bank Transfer",
    }
