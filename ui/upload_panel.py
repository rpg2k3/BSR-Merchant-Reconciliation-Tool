"""Upload Files panel for BSR Reconciliation Tool.

Lets users browse/drag-drop CSV and Excel files, auto-detects their type,
and copies them to the correct data folders.
"""

from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView,
    QGroupBox, QComboBox, QMessageBox, QAbstractItemView, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QColor, QDragEnterEvent, QDropEvent

from core.config import WORKING_DIR
from core.file_detector import detect_file_type, FILE_TYPES
from workers.upload_worker import UploadWorker

# Destination map: file_type -> relative folder under WORKING_DIR
_DEST_MAP = {
    "MTN Transaction":      "Transactions/MTN",
    "Airtel Transaction":   "Transactions/Airtel",
    "Karibu MTN Report":    "Reports/Karibu/MTN",
    "Karibu Airtel Report": "Reports/Karibu/Airtel",
    "MTN Statement":        "Statements",
    "Airtel Statement":     "Statements",
}

# Statement files get a fixed name on copy
_STMT_NAMES = {
    "MTN Statement":    "BSR_MTN_Merchant_Transactions.xlsx",
    "Airtel Statement": "BSR_Airtel_Merchant_Transactions.xlsx",
}

# Style constants
_BTN_STYLE = """
    QPushButton {
        color: #ffffff;
        background-color: #3a3a3a;
        border: 1px solid #555555;
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 11px;
    }
    QPushButton:hover { background-color: #4a4a4a; }
    QPushButton:pressed { background-color: #1F6B2E; }
"""

_UPLOAD_BTN_STYLE = """
    QPushButton {
        color: #ffffff;
        background-color: #1F6B2E;
        border: 1px solid #2a8c3e;
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 11px;
    }
    QPushButton:hover { background-color: #28873a; }
    QPushButton:pressed { background-color: #155a22; }
    QPushButton:disabled { color: #666666; background-color: #2a2a2a; }
"""

_UPLOAD_ALL_STYLE = """
    QPushButton {
        color: #ffffff;
        background-color: #1F6B2E;
        border: 1px solid #2a8c3e;
        border-radius: 4px;
        padding: 10px 16px;
        font-size: 13px;
        font-weight: bold;
    }
    QPushButton:hover { background-color: #28873a; }
    QPushButton:pressed { background-color: #155a22; }
    QPushButton:disabled { color: #666666; background-color: #2a2a2a; }
"""

_UPLOAD_UPDATE_STYLE = """
    QPushButton {
        color: #ffffff;
        background-color: #2471A3;
        border: 1px solid #2e86c1;
        border-radius: 4px;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: bold;
    }
    QPushButton:hover { background-color: #2e86c1; }
    QPushButton:pressed { background-color: #1a5276; }
    QPushButton:disabled { color: #666666; background-color: #2a2a2a; }
"""

_TABLE_STYLE = """
    QTableWidget {
        background-color: #1e1e1e;
        alternate-background-color: #2a2a2a;
        color: #ffffff;
        gridline-color: #3a3a3a;
        border: 1px solid #3a3a3a;
        font-size: 10px;
    }
    QTableWidget::item { padding: 4px; }
    QHeaderView::section {
        background-color: #2d2d2d;
        color: #ffffff;
        padding: 5px;
        border: 1px solid #3a3a3a;
        font-weight: bold;
    }
"""

_DROP_HIGHLIGHT = "border: 2px dashed #1F6B2E; border-radius: 6px;"
_DROP_NORMAL = "border: 2px solid transparent;"


class UploadPanel(QWidget):
    """File upload manager panel."""

    # Emitted when files are uploaded so main window can refresh status
    files_uploaded = pyqtSignal()
    # Emitted with log messages for the main log panel
    log_signal = pyqtSignal(str, str)  # message, level
    # Request main window to run an update for a channel
    request_update = pyqtSignal(str)  # channel

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._last_browse_dir = str(Path.home())
        self._pending_files: dict[str, list[Path]] = {}  # type_name -> [paths]
        self._upload_worker = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # --- Upload rows grouped by category ---
        self._file_labels = {}
        self._browse_btns = {}
        self._upload_btns = {}
        self._type_combos = {}

        # Transactions group
        tx_group = QGroupBox("Transactions")
        tx_layout = QVBoxLayout()
        tx_layout.addLayout(self._make_upload_row("MTN Transaction"))
        tx_layout.addLayout(self._make_upload_row("Airtel Transaction"))
        tx_group.setLayout(tx_layout)
        layout.addWidget(tx_group)

        # Karibu Reports group
        kr_group = QGroupBox("Karibu Reports")
        kr_layout = QVBoxLayout()
        kr_layout.addLayout(self._make_upload_row("Karibu MTN Report"))
        kr_layout.addLayout(self._make_upload_row("Karibu Airtel Report"))
        kr_group.setLayout(kr_layout)
        layout.addWidget(kr_group)

        # Statements group
        st_group = QGroupBox("Statements (optional restore)")
        st_layout = QVBoxLayout()
        st_layout.addLayout(self._make_upload_row("MTN Statement"))
        st_layout.addLayout(self._make_upload_row("Airtel Statement"))
        st_group.setLayout(st_layout)
        layout.addWidget(st_group)

        # Upload All Selected button
        self.btn_upload_all = QPushButton("Upload All Selected")
        self.btn_upload_all.setStyleSheet(_UPLOAD_ALL_STYLE)
        self.btn_upload_all.clicked.connect(self._upload_all)
        layout.addWidget(self.btn_upload_all)

        # Upload & Update combined buttons
        combo_layout = QHBoxLayout()
        self.btn_upload_update_mtn = QPushButton("Upload && Update MTN")
        self.btn_upload_update_mtn.setStyleSheet(_UPLOAD_UPDATE_STYLE)
        self.btn_upload_update_mtn.clicked.connect(lambda: self._upload_and_update("MTN"))
        combo_layout.addWidget(self.btn_upload_update_mtn)

        self.btn_upload_update_airtel = QPushButton("Upload && Update Airtel")
        self.btn_upload_update_airtel.setStyleSheet(_UPLOAD_UPDATE_STYLE)
        self.btn_upload_update_airtel.clicked.connect(lambda: self._upload_and_update("Airtel"))
        combo_layout.addWidget(self.btn_upload_update_airtel)
        layout.addLayout(combo_layout)

        # --- Uploaded Files table ---
        table_label = QLabel("Uploaded Files")
        table_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(table_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["File Name", "Detected Type", "Destination", "Status", "Timestamp"]
        )
        self.table.setStyleSheet(_TABLE_STYLE)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        layout.addWidget(self.table, stretch=1)

        # Drop zone style
        self._normal_style = _DROP_NORMAL
        self.setStyleSheet(_DROP_NORMAL)

    def _make_upload_row(self, type_name: str) -> QHBoxLayout:
        """Create a Browse + label + Upload row for a file type."""
        row = QHBoxLayout()

        label = QLabel(type_name)
        label.setFixedWidth(130)
        label.setFont(QFont("Arial", 10))
        row.addWidget(label)

        file_label = QLabel("No file selected")
        file_label.setFont(QFont("Arial", 9))
        file_label.setStyleSheet("color: #888888;")
        file_label.setMinimumWidth(100)
        self._file_labels[type_name] = file_label
        row.addWidget(file_label, stretch=1)

        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(_BTN_STYLE)
        browse_btn.setFixedWidth(70)
        browse_btn.clicked.connect(lambda checked, t=type_name: self._browse(t))
        self._browse_btns[type_name] = browse_btn
        row.addWidget(browse_btn)

        upload_btn = QPushButton("Upload")
        upload_btn.setStyleSheet(_UPLOAD_BTN_STYLE)
        upload_btn.setFixedWidth(70)
        upload_btn.setEnabled(False)
        upload_btn.clicked.connect(lambda checked, t=type_name: self._upload_single(t))
        self._upload_btns[type_name] = upload_btn
        row.addWidget(upload_btn)

        return row

    # -------------------------------------------------------------------
    # Browse
    # -------------------------------------------------------------------

    def _browse(self, type_name: str):
        """Open file dialog for the given type."""
        if "Statement" in type_name:
            filt = "Excel Files (*.xlsx)"
        else:
            filt = "CSV Files (*.csv);;All Files (*)"

        files, _ = QFileDialog.getOpenFileNames(
            self, f"Select {type_name} files", self._last_browse_dir, filt
        )
        if not files:
            return

        self._last_browse_dir = str(Path(files[0]).parent)
        paths = [Path(f) for f in files]
        self._pending_files[type_name] = paths

        names = ", ".join(p.name for p in paths)
        if len(names) > 60:
            names = names[:57] + "..."
        self._file_labels[type_name].setText(f"{len(paths)} file(s): {names}")
        self._file_labels[type_name].setStyleSheet("color: #ffffff;")
        self._upload_btns[type_name].setEnabled(True)

    # -------------------------------------------------------------------
    # Upload
    # -------------------------------------------------------------------

    def _build_jobs(self, type_name: str) -> list[tuple[Path, Path]]:
        """Build (src, dest) copy jobs for a type, checking for overwrites."""
        paths = self._pending_files.get(type_name, [])
        if not paths:
            return []

        dest_folder = WORKING_DIR / _DEST_MAP[type_name]
        jobs = []
        yes_to_all = False

        for src in paths:
            if type_name in _STMT_NAMES:
                dest = dest_folder / _STMT_NAMES[type_name]
            else:
                dest = dest_folder / src.name

            if dest.exists() and not yes_to_all:
                reply = QMessageBox.question(
                    self,
                    "File exists",
                    f"{dest.name} already exists in {dest.parent.name}/.\nReplace it?",
                    QMessageBox.StandardButton.Yes |
                    QMessageBox.StandardButton.No |
                    QMessageBox.StandardButton.YesToAll,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.No:
                    continue
                if reply == QMessageBox.StandardButton.YesToAll:
                    yes_to_all = True

            jobs.append((src, dest))

        return jobs

    def _upload_single(self, type_name: str):
        """Upload files for a single type."""
        jobs = self._build_jobs(type_name)
        if not jobs:
            return
        self._run_upload(jobs, notify_channel=self._channel_for_type(type_name))

    def _upload_all(self):
        """Upload all pending files across all types."""
        all_jobs = []
        channels = set()
        for type_name in list(self._pending_files.keys()):
            jobs = self._build_jobs(type_name)
            all_jobs.extend(jobs)
            ch = self._channel_for_type(type_name)
            if ch:
                channels.add(ch)
        if not all_jobs:
            self.log_signal.emit("No files selected to upload", "warning")
            return
        self._run_upload(all_jobs, notify_channel=None)

    def _upload_and_update(self, channel: str):
        """Browse for transaction CSVs, upload them, then trigger statement update."""
        filt = "CSV Files (*.csv);;All Files (*)"
        files, _ = QFileDialog.getOpenFileNames(
            self, f"Select {channel} transaction files", self._last_browse_dir, filt
        )
        if not files:
            return

        self._last_browse_dir = str(Path(files[0]).parent)
        type_name = f"{channel} Transaction"
        dest_folder = WORKING_DIR / _DEST_MAP[type_name]
        jobs = []
        for f in files:
            src = Path(f)
            detected = detect_file_type(src)
            # Auto-detect and warn if mismatch
            if detected and detected != type_name:
                self.log_signal.emit(
                    f"Warning: {src.name} detected as '{detected}', expected '{type_name}'",
                    "warning",
                )
            jobs.append((src, dest_folder / src.name))

        if jobs:
            self._upload_and_update_channel = channel
            self._run_upload(jobs, notify_channel=channel, trigger_update=True)

    def _run_upload(self, jobs: list[tuple[Path, Path]], notify_channel: str | None = None,
                    trigger_update: bool = False):
        """Execute upload jobs in a worker thread."""
        self._trigger_update_after = trigger_update
        self._notify_channel = notify_channel
        self.btn_upload_all.setEnabled(False)

        self._upload_worker = UploadWorker(jobs)
        self._upload_worker.file_done_signal.connect(self._on_file_done)
        self._upload_worker.all_done_signal.connect(self._on_all_done)
        self._upload_worker.start()

    def _on_file_done(self, filename: str, dest: str, success: bool, message: str):
        """Called for each file after copy attempt."""
        row = self.table.rowCount()
        self.table.insertRow(row)

        self.table.setItem(row, 0, QTableWidgetItem(filename))

        # Detect type for display
        detected = detect_file_type(Path(dest)) if success else None
        type_text = detected or "—"
        self.table.setItem(row, 1, QTableWidgetItem(type_text))

        dest_folder = str(Path(dest).parent.relative_to(WORKING_DIR)) if success else "—"
        self.table.setItem(row, 2, QTableWidgetItem(dest_folder))

        status_item = QTableWidgetItem("✓ Copied" if success else f"✗ {message}")
        status_item.setForeground(QColor("#1A6B2E") if success else QColor("#C0392B"))
        self.table.setItem(row, 3, status_item)

        ts = datetime.now().strftime("%H:%M:%S")
        self.table.setItem(row, 4, QTableWidgetItem(ts))

        level = "success" if success else "error"
        self.log_signal.emit(f"Upload: {filename} → {message}", level)

    def _on_all_done(self):
        """Called when all uploads are complete."""
        self.btn_upload_all.setEnabled(True)

        # Clear pending files and reset labels
        for type_name in list(self._pending_files.keys()):
            self._pending_files.pop(type_name, None)
            self._file_labels[type_name].setText("No file selected")
            self._file_labels[type_name].setStyleSheet("color: #888888;")
            self._upload_btns[type_name].setEnabled(False)

        self.files_uploaded.emit()

        if self._trigger_update_after and hasattr(self, "_upload_and_update_channel"):
            channel = self._upload_and_update_channel
            del self._upload_and_update_channel
            self._trigger_update_after = False
            self.log_signal.emit(
                f"Upload complete. Starting {channel} statement update...", "info"
            )
            self.request_update.emit(channel)

    # -------------------------------------------------------------------
    # Drag and drop
    # -------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet(_DROP_HIGHLIGHT)

    def dragLeaveEvent(self, event):
        self.setStyleSheet(_DROP_NORMAL)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(_DROP_NORMAL)
        urls = event.mimeData().urls()
        if not urls:
            return

        jobs = []
        for url in urls:
            path = Path(url.toLocalFile())
            if not path.is_file():
                continue

            detected = detect_file_type(path)
            if not detected:
                self.log_signal.emit(
                    f"Could not detect type of {path.name} — skipping", "warning"
                )
                continue

            dest_folder = WORKING_DIR / _DEST_MAP[detected]
            if detected in _STMT_NAMES:
                dest = dest_folder / _STMT_NAMES[detected]
            else:
                dest = dest_folder / path.name

            jobs.append((path, dest))
            self.log_signal.emit(f"Dropped: {path.name} → detected as {detected}", "info")

        if jobs:
            self._run_upload(jobs)

    # -------------------------------------------------------------------
    # Context menu
    # -------------------------------------------------------------------

    def _table_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return

        menu = QMenu(self)
        dest_item = self.table.item(row, 2)
        if dest_item and dest_item.text() != "—":
            open_action = menu.addAction("Open destination folder")
            open_action.triggered.connect(
                lambda: self._open_folder(dest_item.text())
            )

        remove_action = menu.addAction("Remove from list")
        remove_action.triggered.connect(lambda: self.table.removeRow(row))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_folder(self, rel_path: str):
        import subprocess
        full_path = WORKING_DIR / rel_path
        if full_path.exists():
            subprocess.Popen(["xdg-open", str(full_path)])

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _channel_for_type(type_name: str) -> str | None:
        if "MTN" in type_name:
            return "MTN"
        if "Airtel" in type_name or "airtel" in type_name:
            return "Airtel"
        return None
