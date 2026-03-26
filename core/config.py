"""Configuration management for BSR Reconciliation Tool.

Loads/saves settings from ~/.bsr_recon_config.json.
Working directory is always the repo root (parent of this file's directory).
"""

import json
import os
from pathlib import Path

# Static working directory: repo root (one level up from core/)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = Path(os.path.dirname(_THIS_DIR))

CONFIG_PATH = Path.home() / ".bsr_recon_config.json"

DEFAULTS = {
    "claude_api_key": "",
    "date_tolerance_days": 2,
    "high_value_threshold": 500_000,
    "large_payment_threshold": 1_000_000,
}

# All required data folders relative to WORKING_DIR
_FOLDERS = [
    WORKING_DIR / "Transactions" / "MTN",
    WORKING_DIR / "Transactions" / "Airtel",
    WORKING_DIR / "Statements",
    WORKING_DIR / "Reports" / "Karibu" / "MTN",
    WORKING_DIR / "Reports" / "Karibu" / "Airtel",
    WORKING_DIR / "Reconciliation",
    WORKING_DIR / "Backups",
]


def load_config() -> dict:
    """Load config from disk, merging with defaults."""
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                saved = json.load(f)
            config.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    # Strip legacy key if present
    config.pop("working_directory", None)
    return config


def save_config(config: dict):
    """Save config to disk."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def ensure_folders() -> list[str]:
    """Create all required data folders if they don't exist.

    Returns list of newly created folder paths.
    """
    created = []
    for folder in _FOLDERS:
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(str(folder))
    return created
