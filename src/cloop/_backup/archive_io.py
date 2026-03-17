"""Backup archive IO helpers.

Purpose:
    Provide shared extraction and integrity helpers for backup restore and
    verification flows.

Responsibilities:
    - Extract individual archive members into temporary directories
    - Validate extracted database files against manifest metadata
    - Run SQLite integrity checks on extracted database snapshots

Scope:
    - Archive-member extraction and database integrity helpers only

Non-scope:
    - Backup archive creation
    - Restore publication or backup inventory listing

Usage:
    - Imported by restore and verification modules

Invariants/Assumptions:
    - Callers validate archive membership before extraction when needed
    - Integrity checks operate on extracted snapshot files, not live database paths
"""

from __future__ import annotations

import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

from .manifesting import compute_sha256


def extract_archive_member(*, zf: zipfile.ZipFile, member_name: str, destination_dir: Path) -> Path:
    """Extract a single archive member into a destination directory."""
    zf.extract(member_name, destination_dir)
    return destination_dir / member_name


def verify_extracted_database(
    *,
    label: str,
    file_path: Path,
    expected_size_bytes: int,
    expected_sha256: str,
) -> str | None:
    """Validate an extracted database file against manifest metadata."""
    actual_size_bytes = file_path.stat().st_size
    if actual_size_bytes != expected_size_bytes:
        return (
            f"{label} database size mismatch: expected {expected_size_bytes} bytes, "
            f"found {actual_size_bytes}"
        )

    actual_sha256 = compute_sha256(file_path)
    if actual_sha256 != expected_sha256:
        return f"{label} database checksum mismatch"

    return None


def verify_sqlite_integrity(*, label: str, file_path: Path) -> str | None:
    """Run PRAGMA integrity_check against an extracted SQLite database."""
    with closing(sqlite3.connect(str(file_path))) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()

    if result is None or result[0] != "ok":
        return f"{label} database integrity check failed: {result[0] if result else 'unknown'}"

    return None
