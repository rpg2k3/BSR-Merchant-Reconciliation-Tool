"""QThread worker for file copy/upload operations."""

import shutil
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


class UploadWorker(QThread):
    """Worker thread that copies files to their destination folders."""

    # file_path, dest_path, success, message
    file_done_signal = pyqtSignal(str, str, bool, str)
    all_done_signal = pyqtSignal()

    def __init__(self, jobs: list[tuple[Path, Path]]):
        """jobs: list of (source_path, destination_path) tuples."""
        super().__init__()
        self.jobs = jobs

    def run(self):
        for src, dest in self.jobs:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                self.file_done_signal.emit(
                    src.name, str(dest), True, f"Copied to {dest.parent.name}/"
                )
            except Exception as e:
                self.file_done_signal.emit(
                    src.name, str(dest), False, str(e)
                )
        self.all_done_signal.emit()
