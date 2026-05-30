"""Main window for BSR Reconciliation Tool — accounts-driven (Phase 4).

Two-pane window backed by `config/accounts.yaml`:
  left  — AccountsPanel: every configured account + status dot
  right — AccountDetail: file counts, log, Consolidate / Reconcile / Open

Top bar: Run All, Add Account, Settings.

All long operations run on QThread workers (workers/pipeline_workers.py) that
call the Phase 2/3 pipeline (`consolidator.consolidate_account`,
`reconciler.reconcile_account`). The legacy `core` updater/reconciler paths
are no longer invoked from the UI.
"""

import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QVBoxLayout, QWidget,
)

import app_paths
from config import load_accounts
from core.config import load_config, save_config
from ui.account_detail import AccountDetail
from ui.accounts_panel import AccountsPanel
from ui.add_account_dialog import AddAccountDialog
from ui.settings_dialog import SettingsDialog
from workers.pipeline_workers import ConsolidateWorker, ReconcileWorker, RunAllWorker

_TOP_BTN_STYLE = """
    QPushButton {
        color: #ffffff; background-color: #3a3a3a;
        border: 1px solid #555555; border-radius: 4px;
        padding: 8px 16px; font-size: 12px;
    }
    QPushButton:hover { background-color: #4a4a4a; }
    QPushButton:disabled { color: #666666; background-color: #2a2a2a; }
"""


class MainWindow(QMainWindow):
    """BSR Merchant Reconciliation Tool main window."""

    def __init__(self):
        super().__init__()
        self.data_dir = app_paths.DATA_DIR
        self.config = load_config()
        self.accounts = load_accounts()
        self._worker = None
        self._init_ui()
        self.accounts_panel.refresh(self.accounts)

    def _init_ui(self):
        self.setWindowTitle("BSR Merchant Reconciliation Tool")
        self.setMinimumSize(QSize(1024, 768))

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # ---- Top bar ----
        top_bar = QHBoxLayout()
        title = QLabel("BSR Merchant Reconciliation Tool")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        top_bar.addWidget(title)
        top_bar.addStretch()

        self.btn_run_all = QPushButton("Run All")
        self.btn_add_account = QPushButton("Add Account")
        self.btn_settings = QPushButton("Settings")
        for b in (self.btn_run_all, self.btn_add_account, self.btn_settings):
            b.setStyleSheet(_TOP_BTN_STYLE)
            top_bar.addWidget(b)
        self.btn_run_all.clicked.connect(self._run_all)
        self.btn_add_account.clicked.connect(self._add_account)
        self.btn_settings.clicked.connect(self._open_settings)

        main_layout.addLayout(top_bar)

        dir_label = QLabel(f"Data folder: {self.data_dir}")
        dir_label.setFont(QFont("Arial", 9))
        main_layout.addWidget(dir_label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(line)

        # ---- Body: accounts | detail ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.accounts_panel = AccountsPanel(self.data_dir)
        self.detail = AccountDetail(self.data_dir)
        splitter.addWidget(self.accounts_panel)
        splitter.addWidget(self.detail)
        splitter.setSizes([380, 644])
        main_layout.addWidget(splitter, stretch=1)

        # ---- Wiring ----
        self.accounts_panel.account_selected.connect(self._on_account_selected)
        self.detail.consolidate_requested.connect(self._consolidate)
        self.detail.reconcile_requested.connect(self._reconcile)
        self.detail.open_folder_requested.connect(self._open_output_folder)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_account_selected(self, name: str):
        self.detail.set_account(self.accounts.get(name))

    # ------------------------------------------------------------------
    # Busy state
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool):
        self.btn_run_all.setEnabled(not busy)
        self.btn_add_account.setEnabled(not busy)
        self.detail.set_busy(busy)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _consolidate(self, name: str):
        account = self.accounts.get(name)
        if not account:
            return
        self.accounts_panel.clear_error(name)
        self._set_busy(True)
        self._worker = ConsolidateWorker(account, self.data_dir)
        self._worker.log_signal.connect(self.detail.log)
        self._worker.finished_signal.connect(lambda r: self._on_finished(r, name))
        self._worker.start()

    def _reconcile(self, name: str):
        account = self.accounts.get(name)
        if not account:
            return
        self.accounts_panel.clear_error(name)
        self._set_busy(True)
        self._worker = ReconcileWorker(account, self.data_dir, self.config)
        self._worker.log_signal.connect(self.detail.log)
        self._worker.finished_signal.connect(lambda r: self._on_finished(r, name))
        self._worker.start()

    def _run_all(self):
        self._set_busy(True)
        self._worker = RunAllWorker(list(self.accounts.values()), self.data_dir, self.config)
        self._worker.log_signal.connect(self.detail.log)
        self._worker.finished_signal.connect(lambda r: self._on_run_all_finished(r))
        self._worker.start()

    def _on_finished(self, result: dict, name: str):
        self._set_busy(False)
        if result.get("status") == "error":
            self.accounts_panel.set_error(name, result.get("error", "unknown error"))
        else:
            self.accounts_panel.refresh(self.accounts)
        # Refresh the detail counts for the active account.
        self.detail.set_account(self.accounts.get(self.detail.current_account_name())
                                if self.detail.current_account_name() else None)

    def _on_run_all_finished(self, result: dict):
        self._set_busy(False)
        errors = result.get("errors", {})
        for acct_name, msg in errors.items():
            self.accounts_panel.set_error(acct_name, msg)
        self.accounts_panel.refresh(self.accounts)

    # ------------------------------------------------------------------
    # Add Account / Settings / Open folder
    # ------------------------------------------------------------------

    def _add_account(self):
        dlg = AddAccountDialog(self.accounts, self)
        if dlg.exec():
            self.accounts = load_accounts()
            self.accounts_panel.refresh(self.accounts)
            new_name = dlg.new_account_name()
            if new_name:
                self.accounts_panel.select_account(new_name)
            self.detail.log(f"Added account: {new_name}", "success")

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            self.config = dlg.get_config()
            save_config(self.config)

    def _open_output_folder(self, name: str):
        out_dir = app_paths.reconciliation_dir(name, self.data_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(out_dir)])
