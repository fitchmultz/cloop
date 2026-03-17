"""Public backup and restore facade.

Purpose:
    Expose the canonical `cloop.backup` import surface while delegating backup
    runtime details to focused internal modules.

Responsibilities:
    - Re-export backup dataclasses and public operations from one stable module
    - Preserve the public restore monkeypatch seam used by backup tests
    - Keep backup runtime ownership discoverable without a monolithic file

Scope:
    - Public backup facade only

Non-scope:
    - Backup archive creation internals
    - Restore staging, verification, or inventory implementation details

Usage:
    - Import create_backup(), restore_backup(), list_backups(), verify_backup(),
      and rotate_backups() from here
    - Import backup manifest/result dataclasses from here when callers need typed payloads

Invariants/Assumptions:
    - `cloop.backup` remains the canonical public import surface for backup flows
    - Internal implementations may move under `cloop._backup` without changing callers
    - Monkeypatching `cloop.backup._replace_path` continues to affect restore publication
"""

from __future__ import annotations

from pathlib import Path

from ._backup.creation import create_backup
from ._backup.inventory import list_backups, rotate_backups
from ._backup.models import (
    BackupInfo,
    BackupManifest,
    BackupResult,
    InvalidBackupInfo,
    RestoreResult,
    VerifyResult,
)
from ._backup.restore import _replace_path
from ._backup.restore import restore_backup as _restore_backup
from ._backup.verification import verify_backup
from .settings import Settings


def restore_backup(
    *,
    settings: Settings,
    backup_path: Path,
    dry_run: bool = False,
    force: bool = False,
) -> RestoreResult:
    """Restore databases from a backup archive via the public facade seam."""
    return _restore_backup(
        settings=settings,
        backup_path=backup_path,
        dry_run=dry_run,
        force=force,
        replace_path_fn=_replace_path,
    )


__all__ = [
    "BackupInfo",
    "BackupManifest",
    "BackupResult",
    "InvalidBackupInfo",
    "RestoreResult",
    "VerifyResult",
    "_replace_path",
    "create_backup",
    "list_backups",
    "restore_backup",
    "rotate_backups",
    "verify_backup",
]
