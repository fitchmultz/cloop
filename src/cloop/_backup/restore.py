"""Backup restore execution.

Purpose:
    Implement restore preflight, staged publication, and rollback behavior behind
    the public `cloop.backup.restore_backup()` facade.

Responsibilities:
    - Validate manifests and archive contents before mutating live databases
    - Stage verified restore files on the target filesystem
    - Publish restore files atomically and roll back on any mid-restore failure

Scope:
    - Backup restore validation, staging, and publication only

Non-scope:
    - Backup archive creation
    - Backup inventory listing or retention rotation

Usage:
    - Imported by `cloop.backup`, which supplies the public monkeypatchable
      `_replace_path` seam used by restore tests

Invariants/Assumptions:
    - Restore mutates live files only after archive membership, checksums, and schema checks pass
    - Restore either publishes the requested snapshot completely or rolls back the prior state
    - Temporary restore artifacts are cleaned up best-effort on every path
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Iterable

from .. import db
from ..settings import Settings
from .archive_io import extract_archive_member, verify_extracted_database
from .manifesting import compute_sha256, load_backup_manifest
from .models import BackupManifest, RestoreResult

logger = logging.getLogger(__name__)

type ReplacePathFn = Callable[[Path, Path], None]


def validate_restore_manifest(
    *,
    manifest: BackupManifest,
    archive_members: set[str],
    force: bool,
) -> str | None:
    """Validate restore preconditions before touching live database files."""
    has_rag_archive = "rag.db" in archive_members
    has_rag_manifest = manifest.rag_db_size_bytes > 0

    if "core.db" not in archive_members:
        return "Backup archive missing core.db"
    if manifest.core_db_size_bytes <= 0:
        return "Backup manifest has invalid core database size"
    if manifest.core_schema_version <= 0:
        return "Backup manifest has invalid core schema version"
    if not manifest.core_db_sha256:
        return "Backup manifest missing core database checksum"

    if has_rag_archive != has_rag_manifest:
        return "Backup manifest/archive disagree about rag.db presence"

    if has_rag_manifest:
        if manifest.rag_schema_version <= 0:
            return "Backup manifest has invalid RAG schema version"
        if not manifest.rag_db_sha256:
            return "Backup manifest missing RAG database checksum"
    elif manifest.rag_schema_version != 0 or manifest.rag_db_sha256:
        return "Backup manifest marks rag.db absent but still includes RAG metadata"

    if not force and manifest.core_schema_version > db.SCHEMA_VERSION:
        return (
            f"Core backup schema ({manifest.core_schema_version}) newer than supported "
            f"({db.SCHEMA_VERSION})"
        )

    if has_rag_manifest and not force and manifest.rag_schema_version > db.RAG_SCHEMA_VERSION:
        return (
            f"RAG backup schema ({manifest.rag_schema_version}) newer than supported "
            f"({db.RAG_SCHEMA_VERSION})"
        )

    return None


def make_restore_temp_path(*, live_path: Path, label: str) -> Path:
    """Create a unique sibling temp path on the same filesystem as a live database."""
    file_descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{live_path.name}.{label}.",
        suffix=".tmp",
        dir=str(live_path.parent),
    )
    os.close(file_descriptor)
    return Path(raw_path)


def prepare_staged_restore_file(
    *,
    source_path: Path,
    live_path: Path,
    expected_sha256: str,
    label: str,
) -> Path:
    """Copy a verified database file into a same-filesystem staged temp path."""
    staged_path = make_restore_temp_path(live_path=live_path, label="restore-staged")
    shutil.copy2(source_path, staged_path)

    staged_sha256 = compute_sha256(staged_path)
    if staged_sha256 != expected_sha256:
        raise IOError(f"Staged {label} database checksum mismatch")

    return staged_path


def cleanup_restore_temp_paths(paths: Iterable[Path]) -> None:
    """Best-effort cleanup for temporary restore paths."""
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            logger.warning("Failed to clean up restore temp path %s", path, exc_info=True)


def _replace_path(source: Path, destination: Path) -> None:
    """Atomically replace one filesystem path with another."""
    os.replace(source, destination)


def apply_staged_restore(
    *,
    core_db_path: Path,
    rag_db_path: Path,
    staged_core_path: Path,
    staged_rag_path: Path | None,
    replace_path_fn: ReplacePathFn,
) -> None:
    """Publish staged restore files with rollback on any mutation failure."""
    restore_targets: list[tuple[Path, Path | None]] = [
        (core_db_path, staged_core_path),
        (rag_db_path, staged_rag_path),
    ]
    rollback_paths: dict[Path, Path] = {}
    promoted_paths: set[Path] = set()
    staged_paths = [staged_core_path]
    if staged_rag_path is not None:
        staged_paths.append(staged_rag_path)

    try:
        for live_path, _ in restore_targets:
            if not live_path.exists():
                continue
            rollback_path = make_restore_temp_path(live_path=live_path, label="restore-rollback")
            replace_path_fn(live_path, rollback_path)
            rollback_paths[live_path] = rollback_path

        for live_path, staged_path in restore_targets:
            if staged_path is None:
                continue
            replace_path_fn(staged_path, live_path)
            promoted_paths.add(live_path)

        cleanup_restore_temp_paths(rollback_paths.values())
    except Exception as restore_error:
        rollback_errors: list[str] = []

        for live_path in promoted_paths:
            if live_path in rollback_paths:
                continue
            try:
                if live_path.exists():
                    live_path.unlink()
            except OSError as rollback_error:
                rollback_errors.append(f"remove {live_path}: {rollback_error}")

        for live_path, rollback_path in rollback_paths.items():
            try:
                replace_path_fn(rollback_path, live_path)
            except OSError as rollback_error:
                rollback_errors.append(f"restore {live_path}: {rollback_error}")

        cleanup_restore_temp_paths(staged_paths)
        cleanup_restore_temp_paths(rollback_paths.values())

        if rollback_errors:
            rollback_message = "; ".join(rollback_errors)
            raise RuntimeError(
                "Restore failed and rollback was incomplete: "
                f"{restore_error}; rollback errors: {rollback_message}"
            ) from restore_error

        raise RuntimeError(
            f"Restore failed but rollback restored the prior state: {restore_error}"
        ) from restore_error
    finally:
        cleanup_restore_temp_paths(staged_paths)


def restore_backup(
    *,
    settings: Settings,
    backup_path: Path,
    dry_run: bool = False,
    force: bool = False,
    replace_path_fn: ReplacePathFn = _replace_path,
) -> RestoreResult:
    """Restore databases from a backup archive."""
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

    manifest: BackupManifest | None = None
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            try:
                manifest = load_backup_manifest(zf)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                return RestoreResult(
                    success=False,
                    dry_run=dry_run,
                    backup_path=backup_path,
                    manifest=None,
                    core_restored=False,
                    rag_restored=False,
                    error=f"Invalid manifest: {exc}",
                )

            validation_error = validate_restore_manifest(
                manifest=manifest,
                archive_members=set(zf.namelist()),
                force=force,
            )
            if validation_error is not None:
                return RestoreResult(
                    success=False,
                    dry_run=dry_run,
                    backup_path=backup_path,
                    manifest=manifest,
                    core_restored=False,
                    rag_restored=False,
                    error=validation_error,
                )

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                extracted_core = extract_archive_member(
                    zf=zf,
                    member_name="core.db",
                    destination_dir=tmp_path,
                )
                core_validation_error = verify_extracted_database(
                    label="Core",
                    file_path=extracted_core,
                    expected_size_bytes=manifest.core_db_size_bytes,
                    expected_sha256=manifest.core_db_sha256,
                )
                if core_validation_error is not None:
                    return RestoreResult(
                        success=False,
                        dry_run=dry_run,
                        backup_path=backup_path,
                        manifest=manifest,
                        core_restored=False,
                        rag_restored=False,
                        error=core_validation_error,
                    )

                extracted_rag: Path | None = None
                rag_present_in_backup = manifest.rag_db_size_bytes > 0
                if rag_present_in_backup:
                    extracted_rag = extract_archive_member(
                        zf=zf,
                        member_name="rag.db",
                        destination_dir=tmp_path,
                    )
                    rag_validation_error = verify_extracted_database(
                        label="RAG",
                        file_path=extracted_rag,
                        expected_size_bytes=manifest.rag_db_size_bytes,
                        expected_sha256=manifest.rag_db_sha256,
                    )
                    if rag_validation_error is not None:
                        return RestoreResult(
                            success=False,
                            dry_run=dry_run,
                            backup_path=backup_path,
                            manifest=manifest,
                            core_restored=False,
                            rag_restored=False,
                            error=rag_validation_error,
                        )

                if dry_run:
                    return RestoreResult(
                        success=True,
                        dry_run=True,
                        backup_path=backup_path,
                        manifest=manifest,
                        core_restored=False,
                        rag_restored=False,
                    )

                staged_core = prepare_staged_restore_file(
                    source_path=extracted_core,
                    live_path=settings.core_db_path,
                    expected_sha256=manifest.core_db_sha256,
                    label="core",
                )
                staged_rag = (
                    prepare_staged_restore_file(
                        source_path=extracted_rag,
                        live_path=settings.rag_db_path,
                        expected_sha256=manifest.rag_db_sha256,
                        label="RAG",
                    )
                    if extracted_rag is not None
                    else None
                )

                apply_staged_restore(
                    core_db_path=settings.core_db_path,
                    rag_db_path=settings.rag_db_path,
                    staged_core_path=staged_core,
                    staged_rag_path=staged_rag,
                    replace_path_fn=replace_path_fn,
                )

                return RestoreResult(
                    success=True,
                    dry_run=False,
                    backup_path=backup_path,
                    manifest=manifest,
                    core_restored=True,
                    rag_restored=rag_present_in_backup,
                )
    except (OSError, IOError, zipfile.BadZipFile, shutil.Error, RuntimeError) as exc:
        logger.error("Backup restore failed: %s", type(exc).__name__)
        return RestoreResult(
            success=False,
            dry_run=dry_run,
            backup_path=backup_path,
            manifest=manifest,
            core_restored=False,
            rag_restored=False,
            error=f"Restore error: {type(exc).__name__}",
        )
