"""Tests for backup and restore functionality.

Purpose:
    Verify backup creation, restoration, verification, and rotation work correctly.

Responsibilities:
    - Test backup archive creation with manifest and checksums
    - Test restore from backup with dry-run and force options
    - Test backup verification and integrity checking
    - Test backup rotation based on retention settings
    - Test CLI commands for backup operations

Non-scope:
    - Scheduled backup triggering (future enhancement)
    - Cloud storage sync (future enhancement)
"""

import json
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

from cloop import backup, cli, db
from cloop.settings import Settings, get_settings


def _make_settings_with_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Create settings with initialized databases."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def test_create_backup_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test creating a basic backup."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    result = backup.create_backup(settings=settings, name="test")

    assert result.success
    assert result.backup_path is not None
    assert result.backup_path.exists()
    assert result.backup_path.suffix == ".zip"
    assert "test" in result.backup_path.name
    assert result.manifest is not None
    assert result.manifest.name == "test"


def test_create_backup_creates_valid_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that backup archive contains expected files."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    result = backup.create_backup(settings=settings)
    assert result.success
    assert result.backup_path is not None

    with zipfile.ZipFile(str(result.backup_path), "r") as zf:
        names = zf.namelist()
        assert "core.db" in names
        assert "manifest.json" in names

        manifest_data = json.loads(zf.read("manifest.json"))
        assert manifest_data["version"] == 1
        assert "core_schema_version" in manifest_data
        assert "core_db_sha256" in manifest_data


def test_create_backup_includes_rag_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that backup includes RAG database when it exists."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # RAG database should exist after init_databases
    assert settings.rag_db_path.exists()

    result = backup.create_backup(settings=settings)
    assert result.success
    assert result.backup_path is not None

    with zipfile.ZipFile(str(result.backup_path), "r") as zf:
        names = zf.namelist()
        assert "rag.db" in names

        manifest_data = json.loads(zf.read("manifest.json"))
        assert manifest_data["rag_db_size_bytes"] > 0


def test_create_backup_without_rag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test backup when RAG database doesn't exist."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Remove RAG database
    settings.rag_db_path.unlink()
    assert not settings.rag_db_path.exists()

    result = backup.create_backup(settings=settings)
    assert result.success
    assert result.backup_path is not None

    with zipfile.ZipFile(str(result.backup_path), "r") as zf:
        names = zf.namelist()
        assert "rag.db" not in names

        manifest_data = json.loads(zf.read("manifest.json"))
        assert manifest_data["rag_db_size_bytes"] == 0


def test_create_backup_missing_core_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test backup fails gracefully when core database is missing."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Remove core database
    settings.core_db_path.unlink()
    assert not settings.core_db_path.exists()

    result = backup.create_backup(settings=settings)
    assert not result.success
    assert result.backup_path is None
    assert result.error is not None
    assert "Core database not found" in result.error


def test_restore_backup_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test restore dry run doesn't modify files."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create backup
    backup_result = backup.create_backup(settings=settings)
    assert backup_result.success
    assert backup_result.backup_path is not None

    # Dry run restore
    restore_result = backup.restore_backup(
        settings=settings,
        backup_path=backup_result.backup_path,
        dry_run=True,
    )

    assert restore_result.success
    assert restore_result.dry_run
    assert not restore_result.core_restored  # Not restored in dry run


def test_restore_backup_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test full restore from backup."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create backup
    backup_result = backup.create_backup(settings=settings)
    assert backup_result.success
    assert backup_result.backup_path is not None

    # Restore
    restore_result = backup.restore_backup(
        settings=settings,
        backup_path=backup_result.backup_path,
        dry_run=False,
    )

    assert restore_result.success
    assert not restore_result.dry_run
    assert restore_result.core_restored


def test_restore_backup_not_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test restore fails gracefully when backup doesn't exist."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    restore_result = backup.restore_backup(
        settings=settings,
        backup_path=tmp_path / "nonexistent.cloop.zip",
        dry_run=False,
    )

    assert not restore_result.success
    assert restore_result.error is not None
    assert "Backup not found" in restore_result.error


def test_restore_backup_with_force(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test restore with force flag bypasses schema version check."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create backup
    backup_result = backup.create_backup(settings=settings)
    assert backup_result.success

    # Modify the manifest to simulate newer schema
    manifest_data = backup_result.manifest.__dict__.copy()
    manifest_data["core_schema_version"] = 999  # Impossibly high version

    # Create new backup with modified manifest
    modified_backup = tmp_path / "modified.cloop.zip"
    with zipfile.ZipFile(str(backup_result.backup_path), "r") as zf_in:
        with zipfile.ZipFile(modified_backup, "w") as zf_out:
            for item in zf_in.namelist():
                if item == "manifest.json":
                    zf_out.writestr("manifest.json", json.dumps(manifest_data, indent=2))
                else:
                    zf_out.writestr(item, zf_in.read(item))

    # Without force, should fail
    restore_result = backup.restore_backup(
        settings=settings,
        backup_path=modified_backup,
        dry_run=False,
        force=False,
    )
    assert not restore_result.success
    assert restore_result.error is not None
    assert "newer than current" in restore_result.error

    # With force, should succeed
    restore_result = backup.restore_backup(
        settings=settings,
        backup_path=modified_backup,
        dry_run=False,
        force=True,
    )
    assert restore_result.success


def test_verify_valid_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test verification of a valid backup."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    backup_result = backup.create_backup(settings=settings)
    assert backup_result.success
    assert backup_result.backup_path is not None

    verify_result = backup.verify_backup(backup_path=backup_result.backup_path)

    assert verify_result.valid
    assert verify_result.core_integrity
    assert len(verify_result.errors) == 0


def test_verify_missing_backup(tmp_path: Path) -> None:
    """Test verification of non-existent backup."""
    verify_result = backup.verify_backup(backup_path=tmp_path / "nonexistent.cloop.zip")

    assert not verify_result.valid
    assert len(verify_result.errors) > 0
    assert "Backup not found" in verify_result.errors[0]


def test_verify_corrupted_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test verification detects corrupted backup."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    backup_result = backup.create_backup(settings=settings)
    assert backup_result.success
    assert backup_result.backup_path is not None

    # Corrupt the backup by modifying core.db content in the zip
    corrupted_backup = tmp_path / "corrupted.cloop.zip"
    with zipfile.ZipFile(str(backup_result.backup_path), "r") as zf_in:
        with zipfile.ZipFile(corrupted_backup, "w") as zf_out:
            for item in zf_in.namelist():
                if item == "core.db":
                    # Write corrupted content
                    zf_out.writestr("core.db", b"corrupted data")
                else:
                    zf_out.writestr(item, zf_in.read(item))

    verify_result = backup.verify_backup(backup_path=corrupted_backup)

    assert not verify_result.valid
    assert not verify_result.core_integrity
    assert any("checksum mismatch" in e.lower() for e in verify_result.errors)


def test_list_backups_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing backups when none exist."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    backups = backup.list_backups(settings=settings)

    assert backups == []


def test_list_backups_sorted_by_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that backups are sorted by creation time (newest first)."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create multiple backups
    backup.create_backup(settings=settings, name="first")
    time.sleep(0.1)
    backup.create_backup(settings=settings, name="second")
    time.sleep(0.1)
    backup.create_backup(settings=settings, name="third")

    backups = backup.list_backups(settings=settings)

    assert len(backups) == 3
    assert backups[0].name == "third"
    assert backups[1].name == "second"
    assert backups[2].name == "first"


def test_list_backups_with_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test listing backups with limit."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create multiple backups
    for i in range(5):
        backup.create_backup(settings=settings, name=f"backup_{i}")
        time.sleep(0.01)

    backups = backup.list_backups(settings=settings, limit=3)

    assert len(backups) == 3


def test_list_backups_skips_corrupted_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that list_backups skips corrupted zip files."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    backup.create_backup(settings=settings, name="valid")

    corrupted_path = tmp_path / "backups" / "corrupted.cloop.zip"
    with open(corrupted_path, "wb") as f:
        f.write(b"not a valid zip file")

    backups = backup.list_backups(settings=settings)
    assert len(backups) == 1
    assert backups[0].name == "valid"


def test_list_backups_skips_invalid_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that list_backups skips backups with invalid manifests."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    backup.create_backup(settings=settings, name="valid")

    import zipfile

    invalid_path = tmp_path / "backups" / "invalid.cloop.zip"
    with zipfile.ZipFile(invalid_path, "w") as zf:
        zf.writestr("manifest.json", b"not valid json")

    backups = backup.list_backups(settings=settings)
    assert len(backups) == 1
    assert backups[0].name == "valid"


def test_list_backups_include_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that include_invalid returns both valid and invalid backups."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    backup.create_backup(settings=settings, name="valid")

    corrupted_path = tmp_path / "backups" / "corrupted.cloop.zip"
    with open(corrupted_path, "wb") as f:
        f.write(b"not a valid zip file")

    result = backup.list_backups(settings=settings, include_invalid=True)
    assert isinstance(result, tuple)
    valid, invalid = result
    assert len(valid) == 1
    assert valid[0].name == "valid"
    assert len(invalid) == 1
    assert invalid[0].path == corrupted_path
    assert "Corrupted zip file" in invalid[0].reason


def test_backup_rotation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that old backups are rotated when count exceeds limit."""
    monkeypatch.setenv("CLOOP_BACKUP_KEEP_COUNT", "2")
    get_settings.cache_clear()
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create more backups than limit
    backup.create_backup(settings=settings, name="first")
    time.sleep(0.1)
    backup.create_backup(settings=settings, name="second")
    time.sleep(0.1)
    backup.create_backup(settings=settings, name="third")

    # Rotate
    deleted = backup.rotate_backups(settings=settings)

    assert len(deleted) == 1
    remaining = backup.list_backups(settings=settings)
    assert len(remaining) == 2


def test_backup_rotation_no_rotation_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test rotation when no backups need to be deleted."""
    monkeypatch.setenv("CLOOP_BACKUP_KEEP_COUNT", "5")
    get_settings.cache_clear()
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create fewer backups than limit
    backup.create_backup(settings=settings, name="first")
    backup.create_backup(settings=settings, name="second")

    # Rotate
    deleted = backup.rotate_backups(settings=settings)

    assert len(deleted) == 0
    remaining = backup.list_backups(settings=settings)
    assert len(remaining) == 2


def test_cli_backup_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test CLI backup create command."""
    _make_settings_with_data(tmp_path, monkeypatch)

    exit_code = cli.main(["backup", "create", "--name", "cli_test"])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert "backup_path" in output


def test_cli_backup_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test CLI backup list command."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create a backup
    backup.create_backup(settings=settings)

    exit_code = cli.main(["backup", "list"])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert isinstance(output, list)
    assert len(output) >= 1


def test_cli_backup_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test CLI backup verify command."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    backup_result = backup.create_backup(settings=settings)
    assert backup_result.success
    assert backup_result.backup_path is not None

    exit_code = cli.main(["backup", "verify", str(backup_result.backup_path)])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True


def test_cli_backup_restore_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test CLI backup restore with dry run."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    backup_result = backup.create_backup(settings=settings)
    assert backup_result.success
    assert backup_result.backup_path is not None

    exit_code = cli.main(["backup", "restore", str(backup_result.backup_path), "--dry-run"])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["success"] is True
    assert output["dry_run"] is True


def test_cli_backup_rotate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    """Test CLI backup rotate command."""
    monkeypatch.setenv("CLOOP_BACKUP_KEEP_COUNT", "2")
    get_settings.cache_clear()
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create backups
    backup.create_backup(settings=settings, name="first")
    time.sleep(0.1)
    backup.create_backup(settings=settings, name="second")
    time.sleep(0.1)
    backup.create_backup(settings=settings, name="third")

    exit_code = cli.main(["backup", "rotate"])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert "deleted" in output
    assert len(output["deleted"]) == 1


def test_cli_backup_rotate_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """Test CLI backup rotate command with dry run."""
    monkeypatch.setenv("CLOOP_BACKUP_KEEP_COUNT", "2")
    get_settings.cache_clear()
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create backups
    backup.create_backup(settings=settings, name="first")
    time.sleep(0.1)
    backup.create_backup(settings=settings, name="second")
    time.sleep(0.1)
    backup.create_backup(settings=settings, name="third")

    exit_code = cli.main(["backup", "rotate", "--dry-run"])
    assert exit_code == 0

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["total_backups"] == 3
    assert len(output["would_delete"]) == 1

    # Verify no backups were actually deleted
    remaining = backup.list_backups(settings=settings)
    assert len(remaining) == 3


def test_backup_restore_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test full roundtrip: create backup, delete data, restore, verify data intact."""
    from cloop.loops.models import LoopStatus
    from cloop.loops.service import capture_loop, export_loops

    settings = _make_settings_with_data(tmp_path, monkeypatch)

    # Create some data
    with db.core_connection(settings) as conn:
        capture_loop(
            raw_text="Test loop for backup",
            captured_at_iso="2026-02-15T00:00:00+00:00",
            client_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )

    # Verify data exists
    with db.core_connection(settings) as conn:
        loops_before = export_loops(conn=conn)
    assert len(loops_before) == 1

    # Create backup
    backup_result = backup.create_backup(settings=settings)
    assert backup_result.success
    assert backup_result.backup_path is not None

    # Delete data
    settings.core_db_path.unlink()

    # Restore
    restore_result = backup.restore_backup(
        settings=settings,
        backup_path=backup_result.backup_path,
    )
    assert restore_result.success

    # Verify data intact
    with db.core_connection(settings) as conn:
        loops_after = export_loops(conn=conn)
    assert len(loops_after) == 1
    assert loops_after[0]["raw_text"] == "Test loop for backup"


def test_backup_manifest_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that backup manifest contains expected fields."""
    settings = _make_settings_with_data(tmp_path, monkeypatch)

    result = backup.create_backup(settings=settings, name="manifest_test")
    assert result.success
    assert result.manifest is not None

    # Verify manifest fields
    manifest = result.manifest
    assert manifest.version == 1
    assert manifest.name == "manifest_test"
    assert manifest.created_at_utc is not None
    assert manifest.core_schema_version > 0
    assert manifest.core_db_size_bytes > 0
    assert len(manifest.core_db_sha256) == 64  # SHA256 hex string length
    assert manifest.cloop_version is not None
