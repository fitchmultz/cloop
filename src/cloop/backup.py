"""Backup and restore functionality for Cloop data.

Purpose:
    Provide atomic, timestamped backups of all Cloop data (core.db + rag.db)
    with integrity verification, rotation, and point-in-time restore.

Responsibilities:
    - Create timestamped .cloop.zip archives with manifest
    - Restore from backups with schema compatibility checks
    - List and verify existing backups
    - Rotate old backups based on retention settings

Non-scope:
    - Scheduled/automated backup triggering (future enhancement)
    - Cloud storage sync (future enhancement)
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, overload

from . import db
from .settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackupManifest:
    """Metadata for a backup archive."""

    version: int
    created_at_utc: str
    core_schema_version: int
    rag_schema_version: int
    core_db_size_bytes: int
    rag_db_size_bytes: int
    core_db_sha256: str
    rag_db_sha256: str
    name: str
    cloop_version: str


@dataclass(frozen=True)
class BackupResult:
    """Result of a backup operation."""

    success: bool
    backup_path: Path | None
    manifest: BackupManifest | None
    error: str | None = None


@dataclass(frozen=True)
class RestoreResult:
    """Result of a restore operation."""

    success: bool
    dry_run: bool
    backup_path: Path
    manifest: BackupManifest | None
    core_restored: bool
    rag_restored: bool
    error: str | None = None


@dataclass(frozen=True)
class BackupInfo:
    """Information about an existing backup."""

    path: Path
    created_at_utc: str
    name: str
    core_schema_version: int
    rag_schema_version: int
    size_bytes: int


@dataclass(frozen=True)
class InvalidBackupInfo:
    """Information about a backup that failed to load."""

    path: Path
    reason: str


@dataclass(frozen=True)
class VerifyResult:
    """Result of backup verification."""

    valid: bool
    backup_path: Path
    manifest: BackupManifest | None
    core_integrity: bool
    rag_integrity: bool
    errors: list[str] = field(default_factory=list)


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def _get_current_utc_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _get_cloop_version() -> str:
    """Get the current Cloop version string."""
    try:
        from importlib.metadata import version

        return version("cloop")
    except Exception:
        return "0.1.0"


def create_backup(
    *,
    settings: Settings,
    output_dir: Path | None = None,
    name: str = "manual",
) -> BackupResult:
    """Create a timestamped backup of core.db and rag.db.

    Args:
        settings: Application settings containing database paths.
        output_dir: Directory to write backup (default: settings.backup_dir).
        name: Backup name for identification (default: "manual").

    Returns:
        BackupResult with success status and backup path.
    """
    import secrets

    output_dir = output_dir or settings.backup_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _get_current_utc_timestamp()
    # Add 4-character random suffix to prevent collisions when multiple
    # backups are created in the same second
    random_suffix = secrets.token_urlsafe(4)[:4]
    backup_filename = f"{timestamp}_{random_suffix}_{name}.cloop.zip"
    backup_path = output_dir / backup_filename

    core_db_path = settings.core_db_path
    rag_db_path = settings.rag_db_path

    # Check databases exist
    if not core_db_path.exists():
        return BackupResult(
            success=False,
            backup_path=None,
            manifest=None,
            error=f"Core database not found: {core_db_path}",
        )

    # RAG database is optional
    rag_exists = rag_db_path.exists()

    try:
        # Compute checksums before archiving
        core_sha256 = _compute_sha256(core_db_path)
        rag_sha256 = _compute_sha256(rag_db_path) if rag_exists else ""

        # Get schema versions
        core_schema = db.get_core_schema_version(settings)
        rag_schema = db.get_rag_schema_version(settings) if rag_exists else 0

        # Create manifest
        manifest = BackupManifest(
            version=1,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            core_schema_version=core_schema,
            rag_schema_version=rag_schema,
            core_db_size_bytes=core_db_path.stat().st_size,
            rag_db_size_bytes=rag_db_path.stat().st_size if rag_exists else 0,
            core_db_sha256=core_sha256,
            rag_db_sha256=rag_sha256,
            name=name,
            cloop_version=_get_cloop_version(),
        )

        # Create zip archive
        compression = zipfile.ZIP_DEFLATED if settings.backup_compress else zipfile.ZIP_STORED
        with zipfile.ZipFile(backup_path, "w", compression) as zf:
            zf.write(core_db_path, "core.db")
            if rag_exists:
                zf.write(rag_db_path, "rag.db")
            zf.writestr("manifest.json", json.dumps(asdict(manifest), indent=2))

        return BackupResult(
            success=True,
            backup_path=backup_path,
            manifest=manifest,
        )

    except (OSError, IOError, zipfile.BadZipFile) as e:
        logger.exception("Backup creation failed")
        return BackupResult(
            success=False,
            backup_path=None,
            manifest=None,
            error=f"I/O error: {e}",
        )


def restore_backup(
    *,
    settings: Settings,
    backup_path: Path,
    dry_run: bool = False,
    force: bool = False,
) -> RestoreResult:
    """Restore databases from a backup archive.

    Args:
        settings: Application settings containing database paths.
        backup_path: Path to the .cloop.zip backup file.
        dry_run: If True, validate without making changes.
        force: If True, restore even if schema versions differ.

    Returns:
        RestoreResult with success status and details.
    """
    if not backup_path.exists():
        return RestoreResult(
            success=False,
            dry_run=dry_run,
            backup_path=backup_path,
            manifest=None,
            core_restored=False,
            rag_restored=False,
            error=f"Backup not found: {backup_path}",
        )

    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            # Read and parse manifest
            try:
                manifest_data = json.loads(zf.read("manifest.json"))
                manifest = BackupManifest(**manifest_data)
            except (json.JSONDecodeError, KeyError) as e:
                return RestoreResult(
                    success=False,
                    dry_run=dry_run,
                    backup_path=backup_path,
                    manifest=None,
                    core_restored=False,
                    rag_restored=False,
                    error=f"Invalid manifest: {e}",
                )

            # Check schema compatibility (only if current db exists and has schema)
            current_core = db.get_core_schema_version(settings)

            if not force and current_core > 0:
                if manifest.core_schema_version > current_core:
                    return RestoreResult(
                        success=False,
                        dry_run=dry_run,
                        backup_path=backup_path,
                        manifest=manifest,
                        core_restored=False,
                        rag_restored=False,
                        error=(
                            f"Backup schema ({manifest.core_schema_version}) newer "
                            f"than current ({current_core})"
                        ),
                    )

            # Extract to temp location and verify checksums
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)

                # Extract core.db
                zf.extract("core.db", tmp_path)
                extracted_core = tmp_path / "core.db"
                core_sha256 = _compute_sha256(extracted_core)

                if core_sha256 != manifest.core_db_sha256:
                    return RestoreResult(
                        success=False,
                        dry_run=dry_run,
                        backup_path=backup_path,
                        manifest=manifest,
                        core_restored=False,
                        rag_restored=False,
                        error="Core database checksum mismatch",
                    )

                # Extract rag.db if present
                rag_restored = False
                if manifest.rag_db_size_bytes > 0 and "rag.db" in zf.namelist():
                    zf.extract("rag.db", tmp_path)
                    extracted_rag = tmp_path / "rag.db"
                    rag_sha256 = _compute_sha256(extracted_rag)

                    if rag_sha256 != manifest.rag_db_sha256:
                        return RestoreResult(
                            success=False,
                            dry_run=dry_run,
                            backup_path=backup_path,
                            manifest=manifest,
                            core_restored=False,
                            rag_restored=False,
                            error="RAG database checksum mismatch",
                        )
                    rag_restored = True

                if dry_run:
                    return RestoreResult(
                        success=True,
                        dry_run=True,
                        backup_path=backup_path,
                        manifest=manifest,
                        core_restored=False,
                        rag_restored=False,
                    )

                # Perform restore
                core_db_path = settings.core_db_path
                rag_db_path = settings.rag_db_path

                # Backup current databases before overwrite
                core_bak_path = core_db_path.with_suffix(".db.bak")
                rag_bak_path = rag_db_path.with_suffix(".db.bak")
                if core_db_path.exists():
                    core_db_path.rename(core_bak_path)
                shutil.copy2(extracted_core, core_db_path)

                if rag_restored and rag_db_path.exists():
                    rag_db_path.rename(rag_bak_path)
                if rag_restored:
                    shutil.copy2(tmp_path / "rag.db", rag_db_path)

                # Clean up backup files after successful restore
                if core_bak_path.exists():
                    core_bak_path.unlink()
                if rag_bak_path.exists():
                    rag_bak_path.unlink()

                return RestoreResult(
                    success=True,
                    dry_run=False,
                    backup_path=backup_path,
                    manifest=manifest,
                    core_restored=True,
                    rag_restored=rag_restored,
                )

    except (OSError, IOError, zipfile.BadZipFile, shutil.Error) as e:
        logger.exception("Backup restore failed")
        return RestoreResult(
            success=False,
            dry_run=dry_run,
            backup_path=backup_path,
            manifest=None,
            core_restored=False,
            rag_restored=False,
            error=f"Restore error: {e}",
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
    """List available backups in the backup directory.

    Args:
        settings: Application settings containing backup_dir.
        limit: Maximum number of backups to return (newest first).
        include_invalid: If True, return tuple of (valid, invalid) backups.

    Returns:
        List of BackupInfo objects, or tuple of (valid, invalid) if include_invalid=True.
    """
    backup_dir = settings.backup_dir
    if not backup_dir.exists():
        if include_invalid:
            return [], []
        return []

    valid_backups: list[BackupInfo] = []
    invalid_backups: list[InvalidBackupInfo] = []

    for backup_file in backup_dir.glob("*.cloop.zip"):
        try:
            with zipfile.ZipFile(backup_file, "r") as zf:
                manifest_data = json.loads(zf.read("manifest.json"))
                manifest = BackupManifest(**manifest_data)

                valid_backups.append(
                    BackupInfo(
                        path=backup_file,
                        created_at_utc=manifest.created_at_utc,
                        name=manifest.name,
                        core_schema_version=manifest.core_schema_version,
                        rag_schema_version=manifest.rag_schema_version,
                        size_bytes=backup_file.stat().st_size,
                    )
                )
        except zipfile.BadZipFile as e:
            logger.warning(
                "Skipping invalid backup %s: corrupted zip file (%s)", backup_file.name, e
            )
            if include_invalid:
                invalid_backups.append(
                    InvalidBackupInfo(path=backup_file, reason=f"Corrupted zip file: {e}")
                )
        except json.JSONDecodeError as e:
            logger.warning(
                "Skipping invalid backup %s: invalid manifest JSON (%s)", backup_file.name, e
            )
            if include_invalid:
                invalid_backups.append(
                    InvalidBackupInfo(path=backup_file, reason=f"Invalid manifest JSON: {e}")
                )
        except (KeyError, TypeError) as e:
            logger.warning(
                "Skipping invalid backup %s: missing or invalid manifest field (%s)",
                backup_file.name,
                e,
            )
            if include_invalid:
                invalid_backups.append(
                    InvalidBackupInfo(
                        path=backup_file, reason=f"Missing/invalid manifest field: {e}"
                    )
                )
        except OSError as e:
            logger.warning("Skipping invalid backup %s: I/O error (%s)", backup_file.name, e)
            if include_invalid:
                invalid_backups.append(
                    InvalidBackupInfo(path=backup_file, reason=f"I/O error: {e}")
                )
        except (ValueError, AttributeError, RuntimeError) as e:
            logger.warning(
                "Skipping invalid backup %s: data error (%s: %s)",
                backup_file.name,
                type(e).__name__,
                e,
            )
            if include_invalid:
                invalid_backups.append(
                    InvalidBackupInfo(
                        path=backup_file, reason=f"Data error ({type(e).__name__}): {e}"
                    )
                )

    valid_backups.sort(key=lambda b: b.created_at_utc, reverse=True)
    invalid_backups.sort(key=lambda b: b.path.name, reverse=True)

    if limit is not None:
        valid_backups = valid_backups[:limit]

    if include_invalid:
        return valid_backups, invalid_backups
    return valid_backups


def verify_backup(
    *,
    backup_path: Path,
) -> VerifyResult:
    """Verify backup integrity without restoring.

    Args:
        backup_path: Path to the .cloop.zip backup file.

    Returns:
        VerifyResult with integrity check results.
    """
    if not backup_path.exists():
        return VerifyResult(
            valid=False,
            backup_path=backup_path,
            manifest=None,
            core_integrity=False,
            rag_integrity=False,
            errors=[f"Backup not found: {backup_path}"],
        )

    errors: list[str] = []

    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            # Check manifest exists
            if "manifest.json" not in zf.namelist():
                return VerifyResult(
                    valid=False,
                    backup_path=backup_path,
                    manifest=None,
                    core_integrity=False,
                    rag_integrity=False,
                    errors=["Missing manifest.json"],
                )

            manifest_data = json.loads(zf.read("manifest.json"))
            manifest = BackupManifest(**manifest_data)

            # Verify core.db
            core_integrity = False
            if "core.db" not in zf.namelist():
                errors.append("Missing core.db")
            else:
                import tempfile

                with tempfile.TemporaryDirectory() as tmpdir:
                    zf.extract("core.db", tmpdir)
                    extracted_core = Path(tmpdir) / "core.db"
                    core_sha256 = _compute_sha256(extracted_core)
                    if core_sha256 != manifest.core_db_sha256:
                        errors.append("Core database checksum mismatch")
                    else:
                        # Verify SQLite integrity
                        conn = sqlite3.connect(str(extracted_core))
                        result = conn.execute("PRAGMA integrity_check").fetchone()
                        conn.close()
                        if result[0] != "ok":
                            errors.append(f"Core database integrity check failed: {result[0]}")
                        else:
                            core_integrity = True

            # Verify rag.db if present
            rag_integrity = False
            if manifest.rag_db_size_bytes > 0:
                if "rag.db" not in zf.namelist():
                    errors.append("Missing rag.db (expected per manifest)")
                else:
                    import tempfile

                    with tempfile.TemporaryDirectory() as tmpdir:
                        zf.extract("rag.db", tmpdir)
                        extracted_rag = Path(tmpdir) / "rag.db"
                        rag_sha256 = _compute_sha256(extracted_rag)
                        if rag_sha256 != manifest.rag_db_sha256:
                            errors.append("RAG database checksum mismatch")
                        else:
                            conn = sqlite3.connect(str(extracted_rag))
                            result = conn.execute("PRAGMA integrity_check").fetchone()
                            conn.close()
                            if result[0] != "ok":
                                errors.append(f"RAG database integrity check failed: {result[0]}")
                            else:
                                rag_integrity = True

            return VerifyResult(
                valid=len(errors) == 0 and core_integrity,
                backup_path=backup_path,
                manifest=manifest,
                core_integrity=core_integrity,
                rag_integrity=rag_integrity,
                errors=errors,
            )

    except (OSError, IOError, zipfile.BadZipFile, sqlite3.Error) as e:
        logger.exception("Backup verification failed")
        return VerifyResult(
            valid=False,
            backup_path=backup_path,
            manifest=None,
            core_integrity=False,
            rag_integrity=False,
            errors=[f"Verification error: {e}"],
        )


def rotate_backups(
    *,
    settings: Settings,
) -> list[Path]:
    """Delete oldest backups exceeding backup_keep_count.

    Args:
        settings: Application settings containing backup_dir and backup_keep_count.

    Returns:
        List of deleted backup paths.
    """
    backups = list_backups(settings=settings)

    if len(backups) <= settings.backup_keep_count:
        return []

    to_delete = backups[settings.backup_keep_count :]
    deleted: list[Path] = []

    for backup in to_delete:
        try:
            backup.path.unlink()
            deleted.append(backup.path)
        except (OSError, PermissionError) as e:
            logger.warning("Failed to delete backup %s: %s", backup.path, e)

    return deleted
