import logging
import sqlite3
from pathlib import Path

import pytest

from cloop import db
from cloop.settings import get_settings


def _prepare_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    settings = get_settings()
    return settings


def test_init_databases_sets_schema_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _prepare_settings(tmp_path, monkeypatch)
    db.init_databases(settings)

    with sqlite3.connect(settings.core_db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert int(version) == db.SCHEMA_VERSION

    with sqlite3.connect(settings.rag_db_path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert int(version) == db.RAG_SCHEMA_VERSION


def test_init_databases_errors_on_version_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_settings(tmp_path, monkeypatch)

    # Create mismatched schema versions.
    for path_name in ("CLOOP_CORE_DB_PATH", "CLOOP_RAG_DB_PATH"):
        db_path = tmp_path / f"{path_name.lower()}.db"
        monkeypatch.setenv(path_name, str(db_path))

    get_settings.cache_clear()
    settings = get_settings()

    for path in (settings.core_db_path, settings.rag_db_path):
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA user_version = 999")
            conn.commit()

    with pytest.raises(RuntimeError, match="schema_mismatch"):
        db.init_databases(settings)


def test_vector_extension_loading_failure_logs_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that a warning is logged when vector extension fails to load."""
    caplog.set_level(logging.WARNING)

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_SQLITE_VECTOR_EXTENSION", "/nonexistent/extension.so")
    get_settings.cache_clear()
    db.reset_vector_backend()

    settings = get_settings()
    with db.rag_connection(settings):
        pass

    assert any(
        "Failed to load SQLite vector extension" in record.message
        for record in caplog.records
        if record.levelno == logging.WARNING
    )

    error = db.get_vector_load_error()
    assert error is not None

    get_settings.cache_clear()
