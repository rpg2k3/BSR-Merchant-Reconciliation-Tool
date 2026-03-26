"""Settings dialog for BSR Reconciliation Tool."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QSpinBox, QPushButton, QFileDialog, QGroupBox,
)
from PyQt6.QtCore import Qt


class SettingsDialog(QDialog):
    """Configuration dialog for app settings."""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Working directory
        dir_group = QGroupBox("Working Directory")
        dir_layout = QHBoxLayout()
        self.dir_edit = QLineEdit(self.config.get("working_directory", ""))
        self.dir_edit.setReadOnly(True)
        dir_btn = QPushButton("Browse...")
        dir_btn.clicked.connect(self._browse_dir)
        dir_layout.addWidget(self.dir_edit)
        dir_layout.addWidget(dir_btn)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        # AI settings
        ai_group = QGroupBox("Claude AI (Optional)")
        ai_layout = QFormLayout()
        self.api_key_edit = QLineEdit(self.config.get("claude_api_key", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Enter Claude API key for AI audit analysis")
        ai_layout.addRow("API Key:", self.api_key_edit)
        ai_group.setLayout(ai_layout)
        layout.addWidget(ai_group)

        # Reconciliation settings
        recon_group = QGroupBox("Reconciliation Settings")
        recon_layout = QFormLayout()

        self.date_tol_spin = QSpinBox()
        self.date_tol_spin.setRange(0, 5)
        self.date_tol_spin.setValue(self.config.get("date_tolerance_days", 2))
        self.date_tol_spin.setSuffix(" days")
        recon_layout.addRow("Date tolerance:", self.date_tol_spin)

        self.high_value_spin = QSpinBox()
        self.high_value_spin.setRange(0, 10_000_000)
        self.high_value_spin.setSingleStep(100_000)
        self.high_value_spin.setValue(self.config.get("high_value_threshold", 500_000))
        self.high_value_spin.setSuffix(" UGX")
        recon_layout.addRow("High value threshold:", self.high_value_spin)

        self.large_pmt_spin = QSpinBox()
        self.large_pmt_spin.setRange(0, 50_000_000)
        self.large_pmt_spin.setSingleStep(500_000)
        self.large_pmt_spin.setValue(self.config.get("large_payment_threshold", 1_000_000))
        self.large_pmt_spin.setSuffix(" UGX")
        recon_layout.addRow("Large payment threshold:", self.large_pmt_spin)

        recon_group.setLayout(recon_layout)
        layout.addWidget(recon_group)

        # Buttons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Working Directory")
        if path:
            self.dir_edit.setText(path)

    def _save(self):
        self.config["working_directory"] = self.dir_edit.text()
        self.config["claude_api_key"] = self.api_key_edit.text()
        self.config["date_tolerance_days"] = self.date_tol_spin.value()
        self.config["high_value_threshold"] = self.high_value_spin.value()
        self.config["large_payment_threshold"] = self.large_pmt_spin.value()
        self.accept()

    def get_config(self) -> dict:
        return self.config
