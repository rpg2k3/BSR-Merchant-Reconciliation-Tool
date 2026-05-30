"""Add Account wizard.

Collects the fields for a new account, creates its four runtime folders, and
appends a new entry to `config/accounts.yaml`. The append is append-only (it
never rewrites existing entries) so the hand-written comments and multi-line
`notes:` blocks in the YAML survive untouched.

Validation + rollback (per Phase 4 spec):
  1. Reject duplicate name (case-insensitive), unknown parser, empty Karibu
     account — before touching the file.
  2. Record the file's byte size, append the block, re-parse via
     `load_accounts()`.
  3. If parsing fails or the new account is missing, truncate the file back to
     the recorded size, show the error, and keep the dialog open.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QVBoxLayout,
)

import app_paths
import config as config_pkg
from config import bootstrap_folders, load_accounts
from parsers import available_parsers

_ACCOUNTS_YAML = Path(config_pkg.__file__).resolve().parent / "accounts.yaml"


class AddAccountDialog(QDialog):
    """Wizard to register a new account."""

    def __init__(self, existing_accounts: dict, parent=None):
        super().__init__(parent)
        self._existing = existing_accounts
        self._new_name: str | None = None
        self.setWindowTitle("Add Account")
        self.setMinimumWidth(480)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Stanbic UGX")
        form.addRow("Account name:", self.name_edit)

        self.karibu_edit = QLineEdit()
        self.karibu_edit.setPlaceholderText("Karibu ledger account, e.g. PC - Stanbic UGX")
        form.addRow("Karibu account:", self.karibu_edit)

        parsers = available_parsers()
        self.stmt_combo = QComboBox()
        self.stmt_combo.addItems(parsers)
        form.addRow("Statement parser:", self.stmt_combo)

        self.karibu_combo = QComboBox()
        self.karibu_combo.addItems(parsers)
        if "karibu_ledger_csv" in parsers:
            self.karibu_combo.setCurrentText("karibu_ledger_csv")
        form.addRow("Karibu parser:", self.karibu_combo)

        self.date_window_spin = QSpinBox()
        self.date_window_spin.setRange(0, 10)
        self.date_window_spin.setValue(2)
        form.addRow("Date window (days):", self.date_window_spin)

        self.lumpsum_spin = QSpinBox()
        self.lumpsum_spin.setRange(0, 10)
        self.lumpsum_spin.setValue(0)
        form.addRow("Lumpsum window (days):", self.lumpsum_spin)

        self.match_outflows_chk = QCheckBox("Reconcile outflows (Karibu CR ↔ statement OUT)")
        form.addRow("", self.match_outflows_chk)

        self.karibu_only_chk = QCheckBox("Karibu-only rows are normal (soft-flag unmatched)")
        form.addRow("", self.karibu_only_chk)

        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #F44336;")
        layout.addWidget(self.error_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.save_btn = QPushButton("Create")
        self.save_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------

    def new_account_name(self) -> str | None:
        return self._new_name

    def _error(self, msg: str):
        self.error_label.setText(msg)

    def _on_accept(self):
        name = self.name_edit.text().strip()
        karibu = self.karibu_edit.text().strip()
        stmt_parser = self.stmt_combo.currentText()
        karibu_parser = self.karibu_combo.currentText()
        known_parsers = set(available_parsers())

        # ---- pre-write validation ----
        if not name:
            return self._error("Account name is required.")
        if '"' in name or ":" in name:
            return self._error('Account name cannot contain " or : characters.')
        if any(name.lower() == existing.lower() for existing in self._existing):
            return self._error(f"An account named {name!r} already exists (case-insensitive).")
        if not karibu:
            return self._error("Karibu account is required.")
        if stmt_parser not in known_parsers:
            return self._error(f"Unknown statement parser {stmt_parser!r}.")
        if karibu_parser not in known_parsers:
            return self._error(f"Unknown Karibu parser {karibu_parser!r}.")

        # ---- create folders ----
        try:
            bootstrap_folders(name, app_paths.DATA_DIR)
        except Exception as e:
            return self._error(f"Could not create folders: {e}")

        # ---- append + validate + rollback ----
        block = self._build_yaml_block(
            name, karibu, stmt_parser, karibu_parser,
            self.date_window_spin.value(), self.lumpsum_spin.value(),
            self.match_outflows_chk.isChecked(), self.karibu_only_chk.isChecked(),
        )
        try:
            original_size = _ACCOUNTS_YAML.stat().st_size
        except OSError as e:
            return self._error(f"Cannot read accounts.yaml: {e}")

        with _ACCOUNTS_YAML.open("a", encoding="utf-8") as f:
            f.write(block)

        try:
            accounts = load_accounts()
            if name not in accounts:
                raise ValueError("new account not present after re-parse")
        except Exception as e:
            # Roll back to the pre-append state.
            with _ACCOUNTS_YAML.open("r+", encoding="utf-8") as f:
                f.truncate(original_size)
            return self._error(f"accounts.yaml failed validation, rolled back: {e}")

        self._new_name = name
        self.accept()

    @staticmethod
    def _build_yaml_block(
        name: str, karibu: str, stmt_parser: str, karibu_parser: str,
        date_window: int, lumpsum_window: int,
        match_outflows: bool, karibu_only: bool,
    ) -> str:
        lines = [
            "",
            f'  "{name}":',
            f'    karibu_account: "{karibu}"',
            f"    statement_parser: {stmt_parser}",
            f"    karibu_parser: {karibu_parser}",
            "    matching:",
            f"      date_window_days: {date_window}",
            f"      lumpsum_window_days: {lumpsum_window}",
            "      amount_tolerance_ugx: 0.5",
            f"    match_outflows: {str(match_outflows).lower()}",
        ]
        if karibu_only:
            lines.append("    karibu_only_is_normal: true")
        lines.append("")  # trailing newline
        return "\n".join(lines)
