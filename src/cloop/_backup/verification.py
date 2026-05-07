"""Backup archive verification flow.

Purpose:
    Verify backup archives without mutating live databases behind the public
    `cloop.backup.verify_backup()` facade.

Responsibilities:
    - Validate manifest presence and manifest decoding
    - Check extracted database checksums against manifest metadata
    - Run SQLite integrity checks on archived core.db and optional rag.db snapshots

Scope:
    - Read-only backup verification only

Non-scope:
    - Restore publication
    - Backup rotation or archive creation

Usage:
    - Imported by `cloop.backup` for verify_backup()

Invariants/Assumptions:
    - A backup is valid only when core.db passes checksum and SQLite integrity checks
    - rag.db is verified only when the manifest says it should exist
    - Verification operates entirely on extracted temporary snapshot files
"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path

from .archive_io import extract_archive_member, verify_sqlite_integrity
from .manifesting import compute_sha256, load_backup_manifest
from .models import VerifyResult

logger = logging.getLogger(__name__)


def _verify_archive_database(
    *,
    zf: zipfile.ZipFile,
    tmp_path: Path,
    member_name: str,
    label: str,
    expected_size_bytes: int,
    expected_sha256: str,
) -> tuple[bool, list[str]]:
    """Verify one archived database member against manifest and SQLite integrity."""
    extracted_database = extract_archive_member(
        zf=zf,
        member_name=member_name,
        destination_dir=tmp_path,
    )
    database_errors: list[str] = []

    actual_size_bytes = extracted_database.stat().st_size
    if actual_size_bytes != expected_size_bytes:
        database_errors.append(
            f"{label} database size mismatch: expected {expected_size_bytes} bytes, "
            f"found {actual_size_bytes}"
        )

    actual_sha256 = compute_sha256(extracted_database)
    if actual_sha256 != expected_sha256:
        database_errors.append(f"{label} database checksum mismatch")

    if database_errors:
        return False, database_errors

    integrity_error = verify_sqlite_integrity(label=label, file_path=extracted_database)
    if integrity_error is not None:
        database_errors.append(integrity_error)
        return False, database_errors

    return True, database_errors


def verify_backup(*, backup_path: Path) -> VerifyResult:
    """Verify backup integrity without restoring."""
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
            if "manifest.json" not in zf.namelist():
                return VerifyResult(
                    valid=False,
                    backup_path=backup_path,
                    manifest=None,
                    core_integrity=False,
                    rag_integrity=False,
                    errors=["Missing manifest.json"],
                )

            manifest = load_backup_manifest(zf)
            core_integrity = False
            rag_integrity = False

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)

                if "core.db" not in zf.namelist():
                    errors.append("Missing core.db")
                else:
                    core_integrity, core_errors = _verify_archive_database(
                        zf=zf,
                        tmp_path=tmp_path,
                        member_name="core.db",
                        label="Core",
                        expected_size_bytes=manifest.core_db_size_bytes,
                        expected_sha256=manifest.core_db_sha256,
                    )
                    errors.extend(core_errors)

                if manifest.rag_db_size_bytes > 0:
                    if "rag.db" not in zf.namelist():
                        errors.append("Missing rag.db (expected per manifest)")
                    else:
                        rag_integrity, rag_errors = _verify_archive_database(
                            zf=zf,
                            tmp_path=tmp_path,
                            member_name="rag.db",
                            label="RAG",
                            expected_size_bytes=manifest.rag_db_size_bytes,
                            expected_sha256=manifest.rag_db_sha256,
                        )
                        errors.extend(rag_errors)

            return VerifyResult(
                valid=len(errors) == 0 and core_integrity,
                backup_path=backup_path,
                manifest=manifest,
                core_integrity=core_integrity,
                rag_integrity=rag_integrity,
                errors=errors,
            )
    except (
        OSError,
        IOError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        logger.error("Backup verification failed: %s", type(exc).__name__)
        return VerifyResult(
            valid=False,
            backup_path=backup_path,
            manifest=None,
            core_integrity=False,
            rag_integrity=False,
            errors=[f"Verification error: {type(exc).__name__}"],
        )
