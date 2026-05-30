"""High-level reconciliation driver.

`reconcile_account(account, base_dir, year)` is the one entry point used
by the UI, the legacy CLI, and the parity-check tests:

  1. Load the consolidated yearly Karibu / statement workbooks for the
     account from `base_dir/Statements/{account}/`.
  2. Run the 7-pass matching engine (`reconciler.matching.run_matching`),
     running outflows too when `account.match_outflows` is True.
  3. Project the per-row match outcome into the legacy MTN-style output
     columns (`Karibu Report` / `Statement`).
  4. Apply the audit-flag suite plus the Phase-3 suppression matrix.
  5. Preserve user-edited `Comments` from any prior reconciliation file.
  6. Write the workbook to
     `base_dir/Reconciliation/{account}/{account} Reconciliation - {year}.xlsx`.

Returns a `ReconResult` summarising counts, flag totals, and output path.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import AccountConfig
from reconciler.audit import apply_audit
from reconciler.loader import (
    count_unparseable,
    load_consolidated_karibu,
    load_consolidated_statement,
)
from reconciler.matching import run_matching
from reconciler.types import (
    ReconKnobs,
    ReconResult,
    STATUS_MATCHED,
    STATUS_NOT_IN_KARIBU,
    STATUS_NOT_IN_STATEMENT,
)
from reconciler.writer import (
    build_dashboard_lines,
    load_existing_comments,
    restore_comments,
    write_reconciliation_workbook,
)


__all__ = [
    "ReconKnobs",
    "ReconResult",
    "reconcile_account",
    "build_output_frames",
]


def reconcile_account(
    account: AccountConfig,
    base_dir: Path,
    year: int,
    *,
    app_config: dict | None = None,
) -> ReconResult:
    base_dir = Path(base_dir)
    stmt_dir = base_dir / "Statements" / account.name
    out_dir = base_dir / "Reconciliation" / account.name
    out_dir.mkdir(parents=True, exist_ok=True)

    stmt_path = stmt_dir / f"{account.name} Transactions - {year}.xlsx"
    karibu_path = stmt_dir / f"{account.name} Karibu Ledger - {year}.xlsx"
    output_path = out_dir / f"{account.name} Reconciliation - {year}.xlsx"

    karibu_df = load_consolidated_karibu(karibu_path)
    stmt_df = load_consolidated_statement(stmt_path)
    unparseable = count_unparseable(karibu_path) + count_unparseable(stmt_path)

    karibu_out, stmt_out = build_output_frames(
        karibu_df=karibu_df, stmt_df=stmt_df,
        account=account, app_config=app_config,
    )

    # Comment preservation.
    existing = load_existing_comments(output_path)
    restore_comments(karibu_out, stmt_out, existing)

    dashboard = build_dashboard_lines(
        karibu_out, stmt_out,
        account_name=account.name, year=year,
        match_outflows=account.match_outflows,
    )

    write_reconciliation_workbook(karibu_out, stmt_out, dashboard, output_path)

    return _summarise(
        karibu_out, stmt_out,
        account=account, year=year, output_path=output_path,
        unparseable=unparseable,
    )


# ---------------------------------------------------------------------------
# Internal: build the two output DataFrames from raw inputs (pure function).
# Exposed for the MTN parity test.
# ---------------------------------------------------------------------------

def build_output_frames(
    *,
    karibu_df: pd.DataFrame,
    stmt_df: pd.DataFrame,
    account: AccountConfig,
    app_config: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the styled output frames (Karibu Report, Statement) ready to write.

    Pure pandas in / pandas out — no I/O. Used directly by the parity
    test against the legacy `core.reconciler` engine.
    """
    knobs = ReconKnobs.from_account(account.matching)

    # Filter to rows we'll surface in the output: DR>0 always; CR>0 only when
    # match_outflows is on (otherwise the legacy behaviour omits them).
    dr_mask = pd.to_numeric(karibu_df.get("DR", 0), errors="coerce").fillna(0) > 0
    cr_mask = pd.to_numeric(karibu_df.get("CR", 0), errors="coerce").fillna(0) > 0
    if account.match_outflows:
        keep_karibu = karibu_df[dr_mask | cr_mask].copy()
    else:
        keep_karibu = karibu_df[dr_mask].copy()
    keep_karibu.reset_index(drop=True, inplace=True)

    # Statement: drop zero-amount rows and (if not matching outflows) negative-
    # amount rows for the matching input. We still surface contras in the
    # output sheet for the legacy MTN flow.
    stmt_amounts = pd.to_numeric(stmt_df.get("Amount (UGX)", 0), errors="coerce").fillna(0)
    if account.match_outflows:
        keep_stmt = stmt_df[stmt_amounts != 0].copy()
    else:
        keep_stmt = stmt_df[stmt_amounts > 0].copy()
    keep_stmt.reset_index(drop=True, inplace=True)

    # Ensure Direction column exists (legacy MTN data does not — derive it).
    if "Direction" not in keep_stmt.columns:
        amt = pd.to_numeric(keep_stmt.get("Amount (UGX)", 0), errors="coerce").fillna(0)
        keep_stmt["Direction"] = np.where(amt >= 0, "IN", "OUT")

    karibu_result, stmt_result = run_matching(
        keep_karibu, keep_stmt, knobs,
        match_outflows=account.match_outflows,
    )

    karibu_out = _karibu_output_frame(keep_karibu, karibu_result, account)
    stmt_out = _stmt_output_frame(keep_stmt, stmt_result)

    # Contras only matter for accounts that DON'T match outflows — for the
    # bidirectional accounts the OUT rows are real reconciliation candidates,
    # not contras. (Legacy MTN/Airtel contras stay as a separate "Contra"
    # status section so the user sees them but doesn't try to match them.)
    if not account.match_outflows:
        contras = _build_contra_rows(stmt_df)
        if not contras.empty:
            stmt_out = pd.concat([stmt_out, contras], ignore_index=True)

    karibu_out, stmt_out = apply_audit(
        karibu_out, stmt_out,
        account=account, app_config=app_config,
    )
    return karibu_out, stmt_out


def _karibu_output_frame(
    karibu_df: pd.DataFrame,
    karibu_result: pd.DataFrame,
    account: AccountConfig,
) -> pd.DataFrame:
    """Project the legacy MTN-style Karibu Report columns."""
    rows = pd.DataFrame({
        "Date": karibu_df.get("Date"),
        "Account": account.karibu_account,
        "Narration": karibu_df.get("Narration", ""),
        "DR (UGX)": pd.to_numeric(karibu_df.get("DR", 0), errors="coerce").fillna(0),
        "CR (UGX)": pd.to_numeric(karibu_df.get("CR", 0), errors="coerce").fillna(0),
        "Balance": karibu_df.get("Balance", ""),
    })
    rows["Status"] = karibu_result["Status"].values
    rows["Match Type"] = karibu_result["Match Type"].values
    rows["Confidence"] = karibu_result["Confidence"].values
    rows["Matched Ref"] = karibu_result["Matched Ref"].values
    rows["Audit Flag"] = ""
    rows["Comments"] = ""
    return rows


def _stmt_output_frame(
    stmt_df: pd.DataFrame,
    stmt_result: pd.DataFrame,
) -> pd.DataFrame:
    rows = pd.DataFrame({
        "Date": stmt_df.get("Date"),
        "Transaction ID": stmt_df.get("Transaction ID", "").astype(str),
        "Payer Name": stmt_df.get("Counterparty", ""),
        "Amount (UGX)": pd.to_numeric(stmt_df.get("Amount (UGX)", 0), errors="coerce").fillna(0),
        "Tx Status": stmt_df.get("Transaction Type", ""),
        "Direction": stmt_df.get("Direction", ""),
    })
    rows["Status"] = stmt_result["Status"].values
    rows["Match Type"] = stmt_result["Match Type"].values
    rows["Confidence"] = stmt_result["Confidence"].values
    rows["Matched Ref"] = stmt_result["Matched Ref"].values
    rows["Audit Flag"] = ""
    rows["Comments"] = ""
    return rows


def _build_contra_rows(stmt_df: pd.DataFrame) -> pd.DataFrame:
    """Surface negative-amount statement rows as contras (legacy MTN flow)."""
    amt = pd.to_numeric(stmt_df.get("Amount (UGX)", 0), errors="coerce").fillna(0)
    contras = stmt_df[amt < 0].copy()
    if contras.empty:
        return pd.DataFrame()
    rows = pd.DataFrame({
        "Date": contras.get("Date"),
        "Transaction ID": contras.get("Transaction ID", "").astype(str),
        "Payer Name": contras.get("Counterparty", ""),
        "Amount (UGX)": pd.to_numeric(contras.get("Amount (UGX)", 0), errors="coerce").fillna(0),
        "Tx Status": contras.get("Transaction Type", ""),
        "Direction": contras.get("Direction", "OUT"),
    })
    rows["Status"] = "Contra"
    rows["Match Type"] = "—"
    rows["Confidence"] = "—"
    rows["Matched Ref"] = "—"
    rows["Audit Flag"] = ""
    rows["Comments"] = ""
    return rows


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------

def _summarise(
    karibu_out: pd.DataFrame,
    stmt_out: pd.DataFrame,
    *,
    account: AccountConfig,
    year: int,
    output_path: Path,
    unparseable: int,
) -> ReconResult:
    matched_k = karibu_out["Status"] == STATUS_MATCHED
    nis_k = karibu_out["Status"] == STATUS_NOT_IN_STATEMENT
    nik_s = stmt_out["Status"] == STATUS_NOT_IN_KARIBU

    result = ReconResult(
        account=account.name,
        year=year,
        output_path=output_path,
        karibu_rows=len(karibu_out),
        stmt_rows=len(stmt_out),
        matched=int(matched_k.sum()),
        not_in_statement=int(nis_k.sum()),
        not_in_karibu=int(nik_s.sum()),
        unparseable_dates=unparseable,
    )

    if account.match_outflows:
        dr_mask = pd.to_numeric(karibu_out.get("DR (UGX)", 0), errors="coerce").fillna(0) > 0
        cr_mask = pd.to_numeric(karibu_out.get("CR (UGX)", 0), errors="coerce").fillna(0) > 0
        s_dir = stmt_out.get("Direction", pd.Series([""] * len(stmt_out))).astype(str).str.upper()
        s_in = s_dir == "IN"
        s_out = s_dir == "OUT"
        result.matched_in = int((matched_k & dr_mask).sum())
        result.matched_out = int((matched_k & cr_mask).sum())
        result.not_in_statement_in = int((nis_k & dr_mask).sum())
        result.not_in_statement_out = int((nis_k & cr_mask).sum())
        result.not_in_karibu_in = int((nik_s & s_in).sum())
        result.not_in_karibu_out = int((nik_s & s_out).sum())

    # Flag counts (used by dashboard and CLI summaries).
    counts: dict[str, int] = {}
    for df in (karibu_out, stmt_out):
        if "Audit Flag" not in df.columns:
            continue
        for v in df["Audit Flag"].dropna():
            for f in str(v).split(","):
                f = f.strip()
                if f:
                    counts[f] = counts.get(f, 0) + 1
    result.flag_counts = counts
    return result
