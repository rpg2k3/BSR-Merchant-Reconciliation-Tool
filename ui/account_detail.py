"""Account detail panel — the right pane for the selected account.

Shows input file counts, a streaming log/output view (seeded with the tail
of the most recent run log on selection), and the three per-account actions:
Consolidate, Reconcile, Open Output Folder.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

import app_paths
from config import AccountConfig

_LOG_TAIL_LINES = 200

_BTN_STYLE = """
    QPushButton {
        color: #ffffff; background-color: #2D6A4F;
        border: 1px solid #1A4D2E; border-radius: 4px;
        padding: 8px 16px; font-size: 12px;
    }
    QPushButton:hover { background-color: #1A4D2E; }
    QPushButton:disabled { color: #888888; background-color: #2a2a2a; }
"""

_LOG_COLORS = {
    "info": "#FFFFFF", "success": "#4CAF50",
    "error": "#F44336", "warning": "#FF9800",
}


class AccountDetail(QWidget):
    """Detail + actions for one account."""

    consolidate_requested = pyqtSignal(str)
    reconcile_requested = pyqtSignal(str)
    open_folder_requested = pyqtSignal(str)

    def __init__(self, data_dir: Path, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self._account: AccountConfig | None = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.title = QLabel("Select an account")
        self.title.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        layout.addWidget(self.title)

        # File counts
        info_group = QGroupBox("Input folders")
        info_layout = QVBoxLayout()
        self.counts_label = QLabel("—")
        self.counts_label.setFont(QFont("Arial", 10))
        info_layout.addWidget(self.counts_label)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_consolidate = QPushButton("Consolidate")
        self.btn_reconcile = QPushButton("Reconcile")
        self.btn_open = QPushButton("Open Output Folder")
        for b in (self.btn_consolidate, self.btn_reconcile, self.btn_open):
            b.setStyleSheet(_BTN_STYLE)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.btn_consolidate.clicked.connect(self._emit_consolidate)
        self.btn_reconcile.clicked.connect(self._emit_reconcile)
        self.btn_open.clicked.connect(self._emit_open)

        # Log / output
        log_label = QLabel("Log / Output")
        log_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(log_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Monospace", 9))
        layout.addWidget(self.log_view, stretch=1)

        self._set_buttons_enabled(False)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def set_account(self, account: AccountConfig | None):
        self._account = account
        if account is None:
            self.title.setText("Select an account")
            self.counts_label.setText("—")
            self._set_buttons_enabled(False)
            return

        self.title.setText(account.name)
        tx = app_paths.count_source_files(app_paths.transactions_dir(account.name, self.data_dir))
        kr = app_paths.count_source_files(app_paths.karibu_dir(account.name, self.data_dir))
        self.counts_label.setText(
            f"Transactions/{account.name}/:  {tx} file(s)\n"
            f"Reports/Karibu/{account.name}/:  {kr} file(s)"
        )
        self._set_buttons_enabled(True)
        self._show_log_tail()

    def current_account_name(self) -> str | None:
        return self._account.name if self._account else None

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, msg: str, level: str = "info"):
        color = _LOG_COLORS.get(level, "#FFFFFF")
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": ">", "success": "✓", "error": "✗", "warning": "⚠"}.get(level, ">")
        self.log_view.append(f'<span style="color:{color}">[{ts}] {prefix} {msg}</span>')

    def _show_log_tail(self):
        """Seed the log view with the tail of the most recent run log file."""
        ldir = app_paths.logs_dir(self.data_dir)
        if not ldir.is_dir():
            return
        logs = sorted(ldir.glob("*_run.log"))
        if not logs:
            return
        try:
            lines = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        tail = lines[-_LOG_TAIL_LINES:]
        self.log_view.clear()
        self.log_view.append(
            f'<span style="color:#888888">--- tail of {logs[-1].name} ---</span>'
        )
        for line in tail:
            self.log_view.append(f'<span style="color:#BBBBBB">{line}</span>')

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_consolidate.setEnabled(enabled)
        self.btn_reconcile.setEnabled(enabled)
        self.btn_open.setEnabled(enabled)

    def set_busy(self, busy: bool):
        self._set_buttons_enabled(not busy and self._account is not None)

    def _emit_consolidate(self):
        if self._account:
            self.consolidate_requested.emit(self._account.name)

    def _emit_reconcile(self):
        if self._account:
            self.reconcile_requested.emit(self._account.name)

    def _emit_open(self):
        if self._account:
            self.open_folder_requested.emit(self._account.name)
