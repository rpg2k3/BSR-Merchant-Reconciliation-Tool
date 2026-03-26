"""Configuration management for BSR Reconciliation Tool.

Loads/saves settings from ~/.bsr_recon_config.json.
WORKING_DIR resolves correctly both from source and as a PyInstaller executable.
"""

import json
import os
import sys
from pathlib import Path


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        # Running as PyInstaller executable — use the folder containing the exe
        return Path(os.path.dirname(sys.executable))
    else:
        # Running from source — go up from core/ to repo root
        return Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


WORKING_DIR = _get_base_dir()

# Named path constants for all data folders
TRANSACTIONS_MTN = WORKING_DIR / "Transactions" / "MTN"
TRANSACTIONS_AIRTEL = WORKING_DIR / "Transactions" / "Airtel"
STATEMENTS_DIR = WORKING_DIR / "Statements"
KARIBU_MTN_DIR = WORKING_DIR / "Reports" / "Karibu" / "MTN"
KARIBU_AIRTEL_DIR = WORKING_DIR / "Reports" / "Karibu" / "Airtel"
RECONCILIATION_DIR = WORKING_DIR / "Reconciliation"
BACKUPS_DIR = WORKING_DIR / "Backups"

CONFIG_PATH = Path.home() / ".bsr_recon_config.json"

DEFAULTS = {
    "claude_api_key": "",
    "date_tolerance_days": 2,
    "high_value_threshold": 500_000,
    "large_payment_threshold": 1_000_000,
}


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
    config.pop("working_directory", None)
    return config


def save_config(config: dict):
    """Save config to disk."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def ensure_folders() -> list[str]:
    """Create all required data folders if they don't exist."""
    created = []
    for folder in [TRANSACTIONS_MTN, TRANSACTIONS_AIRTEL, STATEMENTS_DIR,
                    KARIBU_MTN_DIR, KARIBU_AIRTEL_DIR, RECONCILIATION_DIR, BACKUPS_DIR]:
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(str(folder))
    return created
