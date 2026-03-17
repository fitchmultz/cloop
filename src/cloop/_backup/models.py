"""Shared backup domain models.

Purpose:
    Define the transport-neutral result and manifest models used by the public
    backup facade and backup internals.

Responsibilities:
    - Describe backup manifests and operation results
    - Provide typed records for backup listing and verification flows
    - Keep backup metadata centralized for all callers

Scope:
    - Backup dataclasses only

Non-scope:
    - Backup archive IO
    - Restore, verification, or rotation execution logic

Usage:
    - Imported by backup creation, restore, verification, and inventory modules

Invariants/Assumptions:
    - Dataclass fields remain JSON-serializable for CLI and API-style consumers
    - Backup manifests reflect one archive snapshot of core.db and optional rag.db
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
