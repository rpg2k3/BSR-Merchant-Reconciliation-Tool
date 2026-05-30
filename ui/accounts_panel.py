"""Accounts panel — the left pane listing every configured account.

Each row shows account name, last consolidation date, last reconciliation
date, and a status dot whose colour summarises what (if anything) the user
should do next. Hovering the dot reveals the next action as a tooltip.

Status precedence:
  red    — the last run for this account errored this session
  amber  — input files newer than the last consolidation (or never
           consolidated but inputs exist), OR consolidated-but-never-reconciled
  green  — up to date
  grey   — no data on disk at all yet
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
)

import app_paths
from config import AccountConfig

# Status dot colours.
_GREEN = "#2D6A4F"
_AMBER = "#B8922A"
_RED = "#C0392B"
_GREY = "#777777"


def _fmt_date(mtime: float | None) -> str:
    if mtime is None:
        return "Never"
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def _count_new_inputs(account: str, since: float | None, data_dir: Path) -> int:
    """Number of input files newer than `since` (all of them if since is None)."""
    count = 0
    for d in (app_paths.transactions_dir(account, data_dir),
              app_paths.karibu_dir(account, data_dir)):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if not (p.is_file() and p.suffix.lower() in app_paths._SUPPORTED_SUFFIXES):
                continue
            if p.name.startswith(".") or p.name.startswith("~"):
                continue
            if since is None or p.stat().st_mtime > since:
                count += 1
    return count


class AccountsPanel(QTableWidget):
    """Table of accounts with per-row status + next-action tooltip."""

    account_selected = pyqtSignal(str)

    def __init__(self, data_dir: Path, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self._errors: dict[str, str] = {}
        self._accounts: dict[str, AccountConfig] = {}

        self.setColumnCount(4)
        self.setHorizontalHeaderLabels(["Account", "Consolidated", "Reconciled", ""])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)

        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.itemSelectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Error state (drives the red dot)
    # ------------------------------------------------------------------

    def set_error(self, account: str, message: str):
        self._errors[account] = message
        self.refresh(self._accounts)

    def clear_error(self, account: str):
        self._errors.pop(account, None)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_selection_changed(self):
        name = self.selected_account()
        if name:
            self.account_selected.emit(name)

    def selected_account(self) -> str | None:
        items = self.selectedItems()
        if not items:
            return None
        return self.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def select_account(self, name: str):
        for row in range(self.rowCount()):
            if self.item(row, 0).data(Qt.ItemDataRole.UserRole) == name:
                self.selectRow(row)
                return

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self, accounts: dict[str, AccountConfig]):
        """Rebuild the table from `accounts`, recomputing status from disk."""
        self._accounts = accounts
        prev = self.selected_account()

        self.blockSignals(True)
        self.setRowCount(0)
        for name in accounts:
            row = self.rowCount()
            self.insertRow(row)

            color, tooltip, consol_txt, recon_txt = self._compute_status(name)

            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, name)
            self.setItem(row, 0, name_item)

            self.setItem(row, 1, QTableWidgetItem(consol_txt))
            self.setItem(row, 2, QTableWidgetItem(recon_txt))

            dot = QTableWidgetItem("●")  # ●
            dot.setForeground(QColor(color))
            dot.setFont(QFont("Arial", 14))
            dot.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setToolTip(tooltip)
            self.setItem(row, 3, dot)
            # Mirror the tooltip onto the whole row so it's easy to discover.
            for col in range(3):
                self.item(row, col).setToolTip(tooltip)

        self.blockSignals(False)

        if prev:
            self.select_account(prev)
        elif self.rowCount():
            self.selectRow(0)

    def _compute_status(self, name: str) -> tuple[str, str, str, str]:
        """Return (dot_colour, tooltip, consolidated_text, reconciled_text)."""
        consol_mtime = app_paths.newest_workbook_mtime(
            app_paths.statements_dir(name, self.data_dir))
        recon_mtime = app_paths.newest_workbook_mtime(
            app_paths.reconciliation_dir(name, self.data_dir))
        input_mtime = app_paths.newest_input_mtime(name, self.data_dir)

        consol_txt = _fmt_date(consol_mtime)
        recon_txt = _fmt_date(recon_mtime)

        # Red — last run errored.
        if name in self._errors:
            return (_RED,
                    f"Last run errored: {self._errors[name]}. See log.",
                    consol_txt, recon_txt)

        has_inputs = input_mtime is not None

        # Grey — nothing on disk at all.
        if not has_inputs and consol_mtime is None:
            return (_GREY,
                    f"No data yet — drop files into Transactions/{name}/ and "
                    f"Reports/Karibu/{name}/",
                    consol_txt, recon_txt)

        # Amber — inputs newer than last consolidation (or never consolidated).
        if has_inputs and (consol_mtime is None or input_mtime > consol_mtime):
            n = _count_new_inputs(name, consol_mtime, self.data_dir)
            return (_AMBER,
                    f"{n} new file(s) in input folders since last consolidation "
                    f"— click Consolidate",
                    consol_txt, recon_txt)

        # Amber variant — consolidated but never reconciled.
        if consol_mtime is not None and recon_mtime is None:
            return (_AMBER,
                    f"Consolidated {consol_txt} but never reconciled — click Reconcile",
                    consol_txt, recon_txt)

        # Green — up to date.
        return (_GREEN,
                f"Up to date — Consolidated {consol_txt}, Reconciled {recon_txt}",
                consol_txt, recon_txt)
