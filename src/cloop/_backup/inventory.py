"""Backup listing and rotation helpers.

Purpose:
    Implement backup inventory inspection and retention cleanup behind the public
    `cloop.backup` facade.

Responsibilities:
    - Enumerate valid and invalid backup archives from the configured backup directory
    - Surface manifest-derived metadata for backup list callers
    - Delete oldest backups beyond the configured retention count

Scope:
    - Backup listing and retention rotation only

Non-scope:
    - Backup creation or restore publication
    - Scheduler-triggered retention automation

Usage:
    - Imported by `cloop.backup` for list_backups() and rotate_backups()

Invariants/Assumptions:
    - Valid backups are sorted newest-first by manifest timestamp
    - Invalid backups are skipped from the valid list and optionally returned separately
    - Rotation deletes only backups beyond `settings.backup_keep_count`
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Literal, overload

from ..settings import Settings
from .manifesting import load_backup_manifest
from .models import BackupInfo, InvalidBackupInfo

logger = logging.getLogger(__name__)


def _invalid_backup_reason(*, backup_file: Path, error: Exception) -> str:
    """Map backup loading failures to stable operator-facing reasons."""
    if isinstance(error, zipfile.BadZipFile):
        logger.warning(
            "Skipping invalid backup %s: corrupted zip file (%s)", backup_file.name, error
        )
        return f"Corrupted zip file: {error}"
    if isinstance(error, json.JSONDecodeError):
        logger.warning(
            "Skipping invalid backup %s: invalid manifest JSON (%s)", backup_file.name, error
        )
        return f"Invalid manifest JSON: {error}"
    if isinstance(error, (KeyError, TypeError)):
        logger.warning(
            "Skipping invalid backup %s: missing or invalid manifest field (%s)",
            backup_file.name,
            error,
        )
        return f"Missing/invalid manifest field: {error}"
    if isinstance(error, OSError):
        logger.warning("Skipping invalid backup %s: I/O error (%s)", backup_file.name, error)
        return f"I/O error: {error}"

    logger.warning(
        "Skipping invalid backup %s: data error (%s: %s)",
        backup_file.name,
        type(error).__name__,
        error,
    )
    return f"Data error ({type(error).__name__}): {error}"


def _read_backup_info(backup_file: Path) -> BackupInfo:
    """Load backup metadata from one archive path."""
    with zipfile.ZipFile(backup_file, "r") as zf:
        manifest = load_backup_manifest(zf)

    return BackupInfo(
        path=backup_file,
        created_at_utc=manifest.created_at_utc,
        name=manifest.name,
        core_schema_version=manifest.core_schema_version,
        rag_schema_version=manifest.rag_schema_version,
        size_bytes=backup_file.stat().st_size,
    )


@overload
def list_backups(
    *,
    settings: Settings,
    limit: int | None = None,
    include_invalid: Literal[False] = False,
) -> list[BackupInfo]: ...


@overload
def list_backups(
    *,
    settings: Settings,
    limit: int | None = None,
    include_invalid: Literal[True] = True,
) -> tuple[list[BackupInfo], list[InvalidBackupInfo]]: ...


def list_backups(
    *,
    settings: Settings,
    limit: int | None = None,
    include_invalid: Literal[False] | Literal[True] = False,
) -> list[BackupInfo] | tuple[list[BackupInfo], list[InvalidBackupInfo]]:
    """List available backups in the configured backup directory."""
    backup_dir = settings.backup_dir
    if not backup_dir.exists():
        if include_invalid:
            return [], []
        return []

    valid_backups: list[BackupInfo] = []
    invalid_backups: list[InvalidBackupInfo] = []

    for backup_file in backup_dir.glob("*.cloop.zip"):
        try:
            valid_backups.append(_read_backup_info(backup_file))
        except (
            zipfile.BadZipFile,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            OSError,
            ValueError,
            AttributeError,
            RuntimeError,
        ) as exc:
            if include_invalid:
                invalid_backups.append(
                    InvalidBackupInfo(
                        path=backup_file,
                        reason=_invalid_backup_reason(backup_file=backup_file, error=exc),
                    )
                )
            else:
                _invalid_backup_reason(backup_file=backup_file, error=exc)

    valid_backups.sort(key=lambda backup_info: backup_info.created_at_utc, reverse=True)
    invalid_backups.sort(key=lambda backup_info: backup_info.path.name, reverse=True)

    if limit is not None:
        valid_backups = valid_backups[:limit]

    if include_invalid:
        return valid_backups, invalid_backups
    return valid_backups


def rotate_backups(*, settings: Settings) -> list[Path]:
    """Delete oldest backups exceeding settings.backup_keep_count."""
    backups = list_backups(settings=settings)

    if len(backups) <= settings.backup_keep_count:
        return []

    to_delete = backups[settings.backup_keep_count :]
    deleted: list[Path] = []

    for backup_info in to_delete:
        try:
            backup_info.path.unlink()
            deleted.append(backup_info.path)
        except (OSError, PermissionError) as exc:
            logger.warning("Failed to delete backup %s: %s", backup_info.path, exc)

    return deleted
