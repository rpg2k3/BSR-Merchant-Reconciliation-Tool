"""QThread workers driving the Phase 2/3 pipeline (consolidator + reconciler).

These replace the legacy `workers/qt_workers.py` (which called the old
`core` updater/reconciler paths). Every worker catches exceptions from the
pipeline rather than letting them crash the thread silently: failures are
surfaced in the log pane AND propagated through `finished_signal` with
`status == "error"` so the accounts panel can flip the status dot red.

`finished_signal` payload contract:
    {"status": "ok",    "result": <ConsolidateResult | list | ...>}
    {"status": "error", "error": "<msg>", "traceback": "<tb>"}
"""

from __future__ import annotations

import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

import consolidator
import reconciler
from app_paths import available_years
from config import AccountConfig


class ConsolidateWorker(QThread):
    """Consolidate a single account's raw inputs into yearly workbooks."""

    log_signal = pyqtSignal(str, str)       # message, level
    finished_signal = pyqtSignal(dict)

    def __init__(self, account: AccountConfig, data_dir: Path):
        super().__init__()
        self.account = account
        self.data_dir = Path(data_dir)

    def run(self):
        try:
            self.log_signal.emit(f"Consolidating {self.account.name}...", "info")
            result = consolidator.consolidate_account(self.account, self.data_dir)
            self.log_signal.emit(
                f"{self.account.name}: {result.statement_records_unique} statement "
                f"+ {result.karibu_records_unique} Karibu records consolidated",
                "success",
            )
            if result.statement_unparseable or result.karibu_unparseable:
                self.log_signal.emit(
                    f"{self.account.name}: {result.statement_unparseable + result.karibu_unparseable} "
                    f"unparseable-date row(s) parked on the Unparseable sheet",
                    "warning",
                )
            self.finished_signal.emit({"status": "ok", "result": result})
        except Exception as e:
            self.log_signal.emit(f"ERROR: {type(e).__name__}: {e}", "error")
            self.finished_signal.emit({
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
            })


class ReconcileWorker(QThread):
    """Reconcile a single account across every consolidated year."""

    log_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal(dict)

    def __init__(self, account: AccountConfig, data_dir: Path, app_config: dict | None = None):
        super().__init__()
        self.account = account
        self.data_dir = Path(data_dir)
        self.app_config = app_config

    def run(self):
        try:
            years = available_years(self.account.name, self.data_dir)
            if not years:
                self.log_signal.emit(
                    f"{self.account.name}: no consolidated workbooks found — "
                    f"click Consolidate first.",
                    "warning",
                )
                self.finished_signal.emit({"status": "ok", "result": [], "no_data": True})
                return

            results = []
            for year in years:
                self.log_signal.emit(f"Reconciling {self.account.name} {year}...", "info")
                res = reconciler.reconcile_account(
                    self.account, self.data_dir, year, app_config=self.app_config,
                )
                total = res.karibu_rows
                pct = (res.matched / total * 100) if total else 0
                self.log_signal.emit(
                    f"{self.account.name} {year}: {res.matched}/{total} Karibu rows "
                    f"matched ({pct:.1f}%) → {res.output_path.name}",
                    "success",
                )
                results.append(res)
            self.finished_signal.emit({"status": "ok", "result": results})
        except Exception as e:
            self.log_signal.emit(f"ERROR: {type(e).__name__}: {e}", "error")
            self.finished_signal.emit({
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
            })


class RunAllWorker(QThread):
    """Consolidate every account, then reconcile every account × year.

    `reconciler` has no `reconcile_all`, so the cross-account/year loop is
    orchestrated here rather than in the (off-limits) reconciler package.
    Per-account failures are logged and recorded in the payload's `errors`
    map but do not abort the run — every account is attempted.
    """

    log_signal = pyqtSignal(str, str)
    finished_signal = pyqtSignal(dict)

    def __init__(self, accounts: list[AccountConfig], data_dir: Path, app_config: dict | None = None):
        super().__init__()
        self.accounts = list(accounts)
        self.data_dir = Path(data_dir)
        self.app_config = app_config

    def run(self):
        errors: dict[str, str] = {}
        try:
            self.log_signal.emit("=== Run All: consolidate + reconcile every account ===", "info")
            for account in self.accounts:
                # --- consolidate ---
                try:
                    self.log_signal.emit(f"Consolidating {account.name}...", "info")
                    consolidator.consolidate_account(account, self.data_dir)
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    self.log_signal.emit(f"ERROR consolidating {account.name}: {msg}", "error")
                    errors[account.name] = msg
                    continue  # can't reconcile what didn't consolidate

                # --- reconcile each year ---
                try:
                    years = available_years(account.name, self.data_dir)
                    if not years:
                        self.log_signal.emit(
                            f"{account.name}: nothing to reconcile (no input data).", "warning",
                        )
                        continue
                    for year in years:
                        res = reconciler.reconcile_account(
                            account, self.data_dir, year, app_config=self.app_config,
                        )
                        total = res.karibu_rows
                        pct = (res.matched / total * 100) if total else 0
                        self.log_signal.emit(
                            f"{account.name} {year}: {res.matched}/{total} matched ({pct:.1f}%)",
                            "success",
                        )
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    self.log_signal.emit(f"ERROR reconciling {account.name}: {msg}", "error")
                    errors[account.name] = msg

            if errors:
                self.log_signal.emit(
                    f"=== Run All finished with {len(errors)} account error(s) ===", "warning",
                )
                self.finished_signal.emit({"status": "error", "errors": errors,
                                           "error": "; ".join(f"{k}: {v}" for k, v in errors.items())})
            else:
                self.log_signal.emit("=== Run All complete ===", "success")
                self.finished_signal.emit({"status": "ok", "errors": {}})
        except Exception as e:
            self.log_signal.emit(f"ERROR: {type(e).__name__}: {e}", "error")
            self.finished_signal.emit({
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
