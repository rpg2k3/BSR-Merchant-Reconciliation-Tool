"""Configuration management for BSR Reconciliation Tool.

Loads/saves settings from ~/.bsr_recon_config.json.
WORKING_DIR resolves correctly both from source and as a PyInstaller executable.

The runtime data directory honours the ``BSR_RECON_DATA_DIR`` environment
variable (Phase 4.5). When set — e.g. pointing at a portable VeraCrypt SSD —
it overrides every default. ``resolve_data_dir()`` is the *single* place that
override is read; ``migrate_layout.DEFAULT_DATA_DIR`` routes through it too, so
the canonical path definitions cannot diverge.
"""

import json
import os
import sys
from pathlib import Path

# Environment variable that overrides the runtime data directory everywhere.
# Set this to relocate BSR_Recon's data onto a portable / encrypted drive.
DATA_DIR_ENV_VAR = "BSR_RECON_DATA_DIR"


def resolve_data_dir(default: Path) -> Path:
    """Resolve the runtime data dir, honouring ``BSR_RECON_DATA_DIR``.

    When the env var is set it wins over ``default`` (``~`` is expanded).
    Otherwise ``default`` is returned unchanged. This is the single source of
    truth for the override — both this module's ``WORKING_DIR`` and
    ``migrate_layout.DEFAULT_DATA_DIR`` call it with their own default, so the
    two never disagree about where an override points.
    """
    override = os.environ.get(DATA_DIR_ENV_VAR)
    return Path(override).expanduser() if override else default


def _default_working_dir() -> Path:
    """Fallback data dir when ``BSR_RECON_DATA_DIR`` is unset (frozen vs source)."""
    if getattr(sys, "frozen", False):
        # Running as PyInstaller executable — use a user-writable data directory
        # so the app works without root even when installed to /opt
        data_dir = Path(os.environ.get(
            "XDG_DATA_HOME", Path.home() / ".local" / "share"
        )) / "BSR_Recon"
        return data_dir
    else:
        # Running from source — go up from core/ to repo root
        return Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


WORKING_DIR = resolve_data_dir(_default_working_dir())

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
