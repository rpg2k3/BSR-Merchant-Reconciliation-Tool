"""Account registry and folder bootstrap.

`load_accounts()` parses `config/accounts.yaml` into a dict of `AccountConfig`.
`bootstrap_folders(account, base_dir)` idempotently creates the four runtime
folders for an account: Transactions/, Reports/Karibu/, Statements/,
Reconciliation/ — each under `base_dir/{folder}/{account}/`.

Callers iterating `load_accounts()` on app startup should skip bootstrap for
accounts whose `legacy_folder` still exists (see `should_bootstrap`). The
Phase 2 migration script renames legacy folders, after which bootstrap can
run cleanly for every account on subsequent startups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


_ACCOUNTS_YAML = Path(__file__).resolve().parent / "accounts.yaml"


@dataclass(frozen=True)
class AccountConfig:
    """One entry from accounts.yaml."""

    name: str
    karibu_account: str
    statement_parser: str
    karibu_parser: str
    matching: dict[str, Any] = field(default_factory=dict)
    legacy_folder: str | None = None
    karibu_only_is_normal: bool = False
    notes: str = ""


def load_accounts(yaml_path: Path | None = None) -> dict[str, AccountConfig]:
    """Load accounts.yaml from disk and return a name → AccountConfig dict.

    Pass an explicit `yaml_path` for tests; default reads the bundled file.
    """
    path = Path(yaml_path) if yaml_path else _ACCOUNTS_YAML
    with path.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    raw_accounts = (doc.get("accounts") or {})
    result: dict[str, AccountConfig] = {}
    for name, entry in raw_accounts.items():
        result[name] = AccountConfig(
            name=name,
            karibu_account=entry.get("karibu_account", ""),
            statement_parser=entry.get("statement_parser", ""),
            karibu_parser=entry.get("karibu_parser", "karibu_ledger_csv"),
            matching=dict(entry.get("matching") or {}),
            legacy_folder=entry.get("legacy_folder"),
            karibu_only_is_normal=bool(entry.get("karibu_only_is_normal", False)),
            notes=str(entry.get("notes") or "").strip(),
        )
    return result


FOLDER_NAMES = ("Transactions", "Reports/Karibu", "Statements", "Reconciliation")


def bootstrap_folders(account_name: str, base_dir: Path) -> list[Path]:
    """Create the four runtime folders for `account_name` under `base_dir`.

    Idempotent — re-running is a no-op. Returns the list of paths that were
    actually created (empty if everything was already in place).
    """
    base = Path(base_dir)
    created: list[Path] = []
    for top in FOLDER_NAMES:
        folder = base / top / account_name
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created.append(folder)
        else:
            # Still call mkdir(exist_ok=True) defensively in case it's a stale
            # symlink or otherwise needs parents materialised.
            folder.mkdir(parents=True, exist_ok=True)
    return created


def should_bootstrap(account: AccountConfig, base_dir: Path) -> bool:
    """Return True if it's safe to bootstrap this account's folders now.

    Skips when the account declares a `legacy_folder` that still exists under
    `Transactions/{legacy_folder}` — that means the Phase 2 rename hasn't run
    yet and bootstrapping would create a doubled tree.
    """
    if not account.legacy_folder:
        return True
    legacy_path = Path(base_dir) / "Transactions" / account.legacy_folder
    return not legacy_path.exists()
