#!/usr/bin/env python3
"""BSR Merchant Reconciliation Tool — Entry Point.

Bunyonyi Safaris Resort offline desktop application for consolidating
MTN/Airtel merchant transaction statements and reconciling them against
Karibu HMS ledger reports.

Run with: python main.py
Dependencies: pip install pyqt6 pandas openpyxl numpy anthropic
"""

import sys
import os

# Ensure the package directory is in the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QPalette, QColor

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("BSR Reconciliation Tool")
    app.setStyle("Fusion")

    # Dark-mode palette so button text is always readable
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#2b2b2b"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2b2b2b"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2b2b2b"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#3a3a3a"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ff4444"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#5599ff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1F6B2E"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#666666"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#666666"))
    app.setPalette(palette)

    # Set default font
    font = QFont("Arial", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
