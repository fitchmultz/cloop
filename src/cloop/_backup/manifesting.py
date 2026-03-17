"""Backup manifest and checksum helpers.

Purpose:
    Centralize archive-manifest assembly, manifest loading, and checksum helpers
    used across backup creation, restore, listing, and verification flows.

Responsibilities:
    - Compute database checksums and timestamps for backup metadata
    - Build canonical manifest records from current on-disk databases
    - Load typed manifest records from backup archives

Scope:
    - Backup metadata assembly and low-level manifest helpers only

Non-scope:
    - Writing zip archives
    - Restore publication or backup rotation

Usage:
    - Imported by the focused backup implementation modules under `cloop._backup`

Invariants/Assumptions:
    - Manifest records stay compatible with JSON serialization
    - Missing rag.db is represented by zero sizes, zero schema version, and empty checksum
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .. import db
from ..settings import Settings
from .models import BackupManifest


def compute_sha256(file_path: Path) -> str:
    """Compute the SHA256 checksum for a file."""
    sha256_hash = hashlib.sha256()
    with file_path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def get_current_utc_timestamp() -> str:
    """Return the current UTC timestamp in archive filename format."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def get_cloop_version() -> str:
    """Return the installed Cloop version string when available."""
    try:
        from importlib.metadata import version

        return version("cloop")
    except ImportError, ModuleNotFoundError:
        return "0.1.0"


def create_backup_manifest(*, settings: Settings, name: str) -> BackupManifest:
    """Create the manifest describing the current database snapshot."""
    core_db_path = settings.core_db_path
    rag_db_path = settings.rag_db_path
    rag_exists = rag_db_path.exists()

    return BackupManifest(
        version=1,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        core_schema_version=db.get_core_schema_version(settings),
        rag_schema_version=db.get_rag_schema_version(settings) if rag_exists else 0,
        core_db_size_bytes=core_db_path.stat().st_size,
        rag_db_size_bytes=rag_db_path.stat().st_size if rag_exists else 0,
        core_db_sha256=compute_sha256(core_db_path),
        rag_db_sha256=compute_sha256(rag_db_path) if rag_exists else "",
        name=name,
        cloop_version=get_cloop_version(),
    )


def backup_manifest_to_json(manifest: BackupManifest) -> str:
    """Serialize a manifest to the canonical archive JSON payload."""
    return json.dumps(asdict(manifest), indent=2)


def load_backup_manifest(zf: zipfile.ZipFile) -> BackupManifest:
    """Load and validate manifest data from a backup archive."""
    manifest_data = json.loads(zf.read("manifest.json"))
    return BackupManifest(**manifest_data)
