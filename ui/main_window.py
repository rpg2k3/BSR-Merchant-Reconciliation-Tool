"""Main window for BSR Reconciliation Tool."""

import subprocess
import sys
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QProgressBar, QFrame,
    QSplitter, QGroupBox, QTabWidget,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QIcon

from core.config import load_config, save_config, WORKING_DIR, STATEMENTS_DIR, RECONCILIATION_DIR
from ui.settings_dialog import SettingsDialog
from ui.upload_panel import UploadPanel
from workers.qt_workers import UpdateWorker, ReconcileWorker


class MainWindow(QMainWindow):
    """BSR Merchant Reconciliation Tool main window."""

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self._current_worker = None
        self._init_ui()
        self._refresh_status()

    def _init_ui(self):
        self.setWindowTitle("BSR Merchant Reconciliation Tool")
        self.setMinimumSize(QSize(1024, 768))

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Top bar: title + data folder path + settings
        top_bar = QHBoxLayout()
        title = QLabel("BSR Merchant Reconciliation Tool")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        top_bar.addWidget(title)
        top_bar.addStretch()

        dir_label = QLabel(f"Data folder: {WORKING_DIR}")
        dir_label.setFont(QFont("Arial", 9))
        top_bar.addWidget(dir_label)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings)
        top_bar.addWidget(settings_btn)

        main_layout.addLayout(top_bar)

        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        main_layout.addWidget(line)

        # Body: left tabs (actions/upload) | right panel (log+AI)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel with tabs
        left_tabs = QTabWidget()
        left_tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #3a3a3a; }
            QTabBar::tab {
                color: #ffffff; background: #2d2d2d;
                padding: 6px 16px; border: 1px solid #3a3a3a;
            }
            QTabBar::tab:selected { background: #3a3a3a; border-bottom: 2px solid #1F6B2E; }
            QTabBar::tab:hover { background: #4a4a4a; }
        """)

        # --- Actions tab ---
        actions_tab = QWidget()
        actions_tab_layout = QVBoxLayout(actions_tab)
        actions_tab_layout.setContentsMargins(5, 5, 5, 5)

        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout()

        self.btn_update_mtn = QPushButton("Update MTN Statement")
        self.btn_update_mtn.clicked.connect(lambda: self._run_update("MTN"))
        actions_layout.addWidget(self.btn_update_mtn)

        self.btn_update_airtel = QPushButton("Update Airtel Statement")
        self.btn_update_airtel.clicked.connect(lambda: self._run_update("Airtel"))
        actions_layout.addWidget(self.btn_update_airtel)

        actions_layout.addSpacing(10)

        self.btn_recon_mtn = QPushButton("Reconcile MTN")
        self.btn_recon_mtn.clicked.connect(lambda: self._run_reconcile("MTN"))
        actions_layout.addWidget(self.btn_recon_mtn)

        self.btn_recon_airtel = QPushButton("Reconcile Airtel")
        self.btn_recon_airtel.clicked.connect(lambda: self._run_reconcile("Airtel"))
        actions_layout.addWidget(self.btn_recon_airtel)

        actions_layout.addSpacing(10)

        self.btn_run_both = QPushButton("Run Both")
        self.btn_run_both.clicked.connect(self._run_both)
        actions_layout.addWidget(self.btn_run_both)

        actions_group.setLayout(actions_layout)
        actions_tab_layout.addWidget(actions_group)

        # Status group
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()

        self.mtn_status_label = QLabel("MTN Statement:\n  Loading...")
        self.mtn_status_label.setFont(QFont("Arial", 9))
        status_layout.addWidget(self.mtn_status_label)

        self.airtel_status_label = QLabel("Airtel Statement:\n  Loading...")
        self.airtel_status_label.setFont(QFont("Arial", 9))
        status_layout.addWidget(self.airtel_status_label)

        status_group.setLayout(status_layout)
        actions_tab_layout.addWidget(status_group)

        # Progress bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate
        self.progress.setVisible(False)
        actions_tab_layout.addWidget(self.progress)

        actions_tab_layout.addStretch()

        # Open output folder button
        self.btn_open_folder = QPushButton("Open Output Folder")
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        actions_tab_layout.addWidget(self.btn_open_folder)

        left_tabs.addTab(actions_tab, "Actions")

        # --- Upload Files tab ---
        self.upload_panel = UploadPanel()
        self.upload_panel.log_signal.connect(self._log)
        self.upload_panel.files_uploaded.connect(self._refresh_status)
        self.upload_panel.request_update.connect(self._run_update)
        left_tabs.addTab(self.upload_panel, "Upload Files")

        splitter.addWidget(left_tabs)

        # Right panel
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 5, 5, 5)

        # Log panel
        log_label = QLabel("Log / Output")
        log_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        right_layout.addWidget(log_label)

        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setFont(QFont("Monospace", 9))
        right_layout.addWidget(self.log_panel, stretch=3)

        # AI Narrative panel
        ai_label = QLabel("AI Audit Narrative")
        ai_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        right_layout.addWidget(ai_label)

        self.ai_panel = QTextEdit()
        self.ai_panel.setReadOnly(True)
        self.ai_panel.setFont(QFont("Arial", 9))
        self.ai_panel.setPlaceholderText(
            "AI analysis will appear here if a Claude API key is configured in Settings "
            "and reconciliation has been run."
        )
        right_layout.addWidget(self.ai_panel, stretch=1)

        splitter.addWidget(right_widget)
        splitter.setSizes([250, 750])

        main_layout.addWidget(splitter)

        # Style buttons
        btn_style = """
            QPushButton {
                color: #ffffff;
                background-color: #3a3a3a;
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:pressed {
                background-color: #1F6B2E;
            }
            QPushButton:disabled {
                color: #666666;
                background-color: #2a2a2a;
            }
        """
        run_both_style = btn_style.replace(
            "font-size: 12px;",
            "font-size: 12px;\n                font-weight: bold;",
            1,
        )
        for btn in [self.btn_update_mtn, self.btn_update_airtel,
                     self.btn_recon_mtn, self.btn_recon_airtel,
                     self.btn_open_folder]:
            btn.setStyleSheet(btn_style)
        self.btn_run_both.setStyleSheet(run_both_style)

    # -------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------

    def _log(self, msg: str, level: str = "info"):
        colors = {
            "info": "#FFFFFF",
            "success": "#4CAF50",
            "error": "#F44336",
            "warning": "#FF9800",
        }
        color = colors.get(level, "#FFFFFF")
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": ">", "success": "✓", "error": "✗", "warning": "⚠"}.get(level, ">")
        self.log_panel.append(
            f'<span style="color:{color}">[{timestamp}] {prefix} {msg}</span>'
        )

    # -------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------

    def _set_busy(self, busy: bool):
        self.progress.setVisible(busy)
        for btn in [self.btn_update_mtn, self.btn_update_airtel,
                     self.btn_recon_mtn, self.btn_recon_airtel, self.btn_run_both]:
            btn.setEnabled(not busy)

    def _run_update(self, channel: str):
        self._set_busy(True)
        self._log(f"Starting {channel} statement update...", "info")

        self._current_worker = UpdateWorker(channel, WORKING_DIR)
        self._current_worker.log_signal.connect(self._log)
        self._current_worker.finished_signal.connect(
            lambda result: self._on_update_finished(result, channel)
        )
        self._current_worker.start()

    def _on_update_finished(self, result: dict, channel: str):
        self._set_busy(False)
        if "error" in result:
            self._log(f"{channel} update failed: {result['error']}", "error")
        else:
            self._log(f"{channel} update complete: {result.get('added', 0)} new rows added", "success")
        self._refresh_status()

        # If this is part of "Run Both", continue with next step
        if hasattr(self, "_run_both_state"):
            self._continue_run_both()

    def _run_reconcile(self, channel: str):
        self._set_busy(True)
        self._log(f"Starting {channel} reconciliation...", "info")

        self._current_worker = ReconcileWorker(channel, WORKING_DIR, self.config)
        self._current_worker.log_signal.connect(self._log)
        self._current_worker.ai_narrative_signal.connect(self._show_ai_narrative)
        self._current_worker.finished_signal.connect(
            lambda result: self._on_recon_finished(result, channel)
        )
        self._current_worker.start()

    def _on_recon_finished(self, result: dict, channel: str):
        self._set_busy(False)
        if "error" in result:
            self._log(f"{channel} reconciliation failed: {result['error']}", "error")
        else:
            matched = result.get("matched", 0)
            total = result.get("total_karibu", 0)
            pct = (matched / total * 100) if total > 0 else 0
            self._log(
                f"{channel} reconciliation complete: {matched}/{total} matched ({pct:.1f}%)",
                "success",
            )
        self._refresh_status()

        if hasattr(self, "_run_both_state"):
            self._continue_run_both()

    def _run_both(self):
        """Run update + reconcile for both MTN and Airtel sequentially."""
        self._run_both_state = [
            ("update", "MTN"),
            ("update", "Airtel"),
            ("reconcile", "MTN"),
            ("reconcile", "Airtel"),
        ]
        self._log("=== Running full update + reconciliation for both channels ===", "info")
        self._continue_run_both()

    def _continue_run_both(self):
        if not hasattr(self, "_run_both_state") or not self._run_both_state:
            if hasattr(self, "_run_both_state"):
                del self._run_both_state
            self._log("=== All operations complete ===", "success")
            return

        action, channel = self._run_both_state.pop(0)
        if action == "update":
            self._run_update(channel)
        else:
            self._run_reconcile(channel)

    def _show_ai_narrative(self, text: str):
        self.ai_panel.setPlainText(text)

    # -------------------------------------------------------------------
    # Status refresh
    # -------------------------------------------------------------------

    def _refresh_status(self):
        # MTN
        mtn_path = STATEMENTS_DIR / "BSR_MTN_Merchant_Transactions.xlsx"
        if mtn_path.exists():
            try:
                from core.parsers import load_mtn_statement
                df, _ = load_mtn_statement(mtn_path)
                dates = df["Date"].dropna()
                last_date = dates.max().strftime("%d %b") if not dates.empty else "N/A"
                self.mtn_status_label.setText(f"MTN Statement:\n  {len(df)} rows\n  Last: {last_date}")
            except Exception:
                self.mtn_status_label.setText("MTN Statement:\n  Error reading file")
        else:
            self.mtn_status_label.setText("MTN Statement:\n  No file")

        # Airtel
        airtel_path = STATEMENTS_DIR / "BSR_Airtel_Merchant_Transactions.xlsx"
        if airtel_path.exists():
            try:
                from core.parsers import load_airtel_statement
                df, _ = load_airtel_statement(airtel_path)
                dates = df["Transaction Date"].dropna()
                last_date = dates.max().strftime("%d %b") if not dates.empty else "N/A"
                self.airtel_status_label.setText(f"Airtel Statement:\n  {len(df)} rows\n  Last: {last_date}")
            except Exception:
                self.airtel_status_label.setText("Airtel Statement:\n  Error reading file")
        else:
            self.airtel_status_label.setText("Airtel Statement:\n  No file")

    # -------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            self.config = dlg.get_config()
            save_config(self.config)

    def _open_output_folder(self):
        recon_dir = RECONCILIATION_DIR
        recon_dir.mkdir(exist_ok=True)
        subprocess.Popen(["xdg-open", str(recon_dir)])
