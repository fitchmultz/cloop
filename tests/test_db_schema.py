import logging
import sqlite3
from concurrent import futures
from contextlib import closing
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

    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert int(version) == db.SCHEMA_VERSION

    with closing(sqlite3.connect(settings.rag_db_path)) as conn:
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
        with closing(sqlite3.connect(path)) as conn:
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


def test_idempotency_keys_table_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that idempotency_keys table is created after init_databases."""
    settings = _prepare_settings(tmp_path, monkeypatch)
    db.init_databases(settings)

    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='idempotency_keys'"
        ).fetchone()
    assert row is not None


def test_review_workflow_tables_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Saved review actions and sessions should have durable schema tables."""
    settings = _prepare_settings(tmp_path, monkeypatch)
    db.init_databases(settings)

    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
                ("review_action_presets", "review_sessions"),
            ).fetchall()
        }

    assert table_names == {"review_action_presets", "review_sessions"}


def test_planning_workflow_tables_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Planning sessions and checkpoint runs should have durable schema tables."""
    settings = _prepare_settings(tmp_path, monkeypatch)
    db.init_databases(settings)

    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
                ("planning_sessions", "planning_session_runs"),
            ).fetchall()
        }

    assert table_names == {"planning_sessions", "planning_session_runs"}


def test_idempotency_keys_table_has_unique_constraint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that idempotency_keys has unique constraint on (scope, idempotency_key)."""
    settings = _prepare_settings(tmp_path, monkeypatch)
    db.init_databases(settings)

    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        info = conn.execute("PRAGMA index_list('idempotency_keys')").fetchall()
    has_unique = False
    for row in info:
        is_unique = row[2]
        if is_unique:
            has_unique = True
            break
    assert has_unique, f"No unique index found. Indexes: {info}"


def test_vector_extension_manager_thread_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that concurrent access to vector extension state is safe."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db.reset_vector_backend()

    errors: list[Exception] = []
    results: list[bool] = []

    def access_vector_state() -> None:
        try:
            # Each thread tries to access state
            state = db.vector_extension_available()
            results.append(state)
            # Reset and access again
            db.reset_vector_backend()
            _ = db.get_vector_backend()
        except Exception as e:
            errors.append(e)

    with futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures_list = [executor.submit(access_vector_state) for _ in range(50)]
        futures.wait(futures_list)

    assert not errors, f"Thread-safety errors: {errors}"
    get_settings.cache_clear()


def test_migration_rollback_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that a failing migration rolls back both version and data changes."""
    settings = _prepare_settings(tmp_path, monkeypatch)
    db.init_databases(settings)

    # Verify we're at the current schema version
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        initial_version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert initial_version == db.SCHEMA_VERSION

    # Manually set version back to simulate being at an older version
    # and inject a bad migration that will fail
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        conn.execute("PRAGMA user_version = 4")  # Set to version before data migrations
        conn.commit()

    # Create a migration that succeeds partially then fails
    # This tests that partial data changes are rolled back
    original_migrations = db._CORE_MIGRATIONS.copy()
    db._CORE_MIGRATIONS[5] = """
        CREATE TABLE test_rollback_marker (id INTEGER PRIMARY KEY, value TEXT);
        INSERT INTO test_rollback_marker (value) VALUES ('should be rolled back');
        SELECT * FROM nonexistent_table;
    """

    try:
        with pytest.raises(sqlite3.OperationalError):
            with db.core_connection(settings) as conn:
                db.migrate_core_db(conn, from_version=4, to_version=5)
    finally:
        db._CORE_MIGRATIONS = original_migrations

    # Verify database is still at version 4 (rolled back)
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        version_after_failure = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version_after_failure == 4

    # Verify the table created by partial migration was rolled back
    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_rollback_marker'"
        ).fetchone()
    assert table_exists is None, "Migration data should have been rolled back"


def test_critical_performance_indexes_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that performance-critical indexes are created."""
    settings = _prepare_settings(tmp_path, monkeypatch)
    db.init_databases(settings)

    with closing(sqlite3.connect(settings.core_db_path)) as conn:
        # Check loop_events indexes
        events_indexes = conn.execute(
            "SELECT name FROM pragma_index_list('loop_events') WHERE name IN "
            "('idx_loop_events_loop_id', 'idx_loop_events_type_created')"
        ).fetchall()
        events_index_names = {row[0] for row in events_indexes}
        assert "idx_loop_events_type_created" in events_index_names, (
            "Missing idx_loop_events_type_created index"
        )

        # Check loop_claims indexes
        claims_indexes = conn.execute(
            "SELECT name FROM pragma_index_list('loop_claims') WHERE name IN "
            "('idx_loop_claims_lease_until', 'idx_loop_claims_owner_lease')"
        ).fetchall()
        claims_index_names = {row[0] for row in claims_indexes}
        assert "idx_loop_claims_owner_lease" in claims_index_names, (
            "Missing idx_loop_claims_owner_lease index"
        )
