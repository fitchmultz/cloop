"""Backup archive creation flow.

Purpose:
    Implement timestamped backup archive creation behind the public
    `cloop.backup.create_backup()` facade.

Responsibilities:
    - Validate current database availability before archive creation
    - Build canonical manifest metadata for each backup snapshot
    - Write core.db, optional rag.db, and manifest.json into a `.cloop.zip` archive

Scope:
    - On-demand backup archive creation only

Non-scope:
    - Restore execution or verification
    - Backup rotation or scheduler-triggered automation

Usage:
    - Imported by `cloop.backup` to provide the public create_backup() entrypoint

Invariants/Assumptions:
    - core.db must exist before a backup can be created
    - rag.db is optional and is omitted from the archive when absent
    - Archive filenames remain timestamped and collision-resistant
"""

from __future__ import annotations

import logging
import secrets
import zipfile
from pathlib import Path

from ..settings import Settings
from .manifesting import backup_manifest_to_json, create_backup_manifest, get_current_utc_timestamp
from .models import BackupResult

logger = logging.getLogger(__name__)


def create_backup(
    *,
    settings: Settings,
    output_dir: Path | None = None,
    name: str = "manual",
) -> BackupResult:
    """Create a timestamped backup of core.db and optional rag.db."""
    output_dir = output_dir or settings.backup_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = get_current_utc_timestamp()
    random_suffix = secrets.token_urlsafe(4)[:4]
    backup_filename = f"{timestamp}_{random_suffix}_{name}.cloop.zip"
    backup_path = output_dir / backup_filename

    core_db_path = settings.core_db_path
    rag_db_path = settings.rag_db_path
    if not core_db_path.exists():
        return BackupResult(
            success=False,
            backup_path=None,
            manifest=None,
            error=f"Core database not found: {core_db_path}",
        )

    rag_exists = rag_db_path.exists()

    try:
        manifest = create_backup_manifest(settings=settings, name=name)
        compression = zipfile.ZIP_DEFLATED if settings.backup_compress else zipfile.ZIP_STORED
        with zipfile.ZipFile(backup_path, "w", compression) as zf:
            zf.write(core_db_path, "core.db")
            if rag_exists:
                zf.write(rag_db_path, "rag.db")
            zf.writestr("manifest.json", backup_manifest_to_json(manifest))

        return BackupResult(success=True, backup_path=backup_path, manifest=manifest)
    except (OSError, IOError, zipfile.BadZipFile) as exc:
        logger.exception("Backup creation failed")
        return BackupResult(
            success=False,
            backup_path=None,
            manifest=None,
            error=f"I/O error: {exc}",
        )
