"""Configuration management for BSR Reconciliation Tool.

Loads/saves settings from ~/.bsr_recon_config.json.
"""

import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".bsr_recon_config.json"

DEFAULTS = {
    "working_directory": "",
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
    return config


def save_config(config: dict):
    """Save config to disk."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_working_dir(config: dict) -> Path:
    """Return working directory as Path, or None if not set."""
    wd = config.get("working_directory", "")
    if wd and os.path.isdir(wd):
        return Path(wd)
    return None


def ensure_folder_structure(base: Path):
    """Create required subfolders if they don't exist."""
    folders = [
        base / "Transactions" / "MTN",
        base / "Transactions" / "Airtel",
        base / "Statements",
        base / "Reports" / "Karibu" / "MTN",
        base / "Reports" / "Karibu" / "Airtel",
        base / "Reconciliation",
        base / "Backups",
    ]
    created = []
    for folder in folders:
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(str(folder))
    return created
