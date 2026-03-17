"""Database infrastructure public surface.

Purpose:
    Re-export focused database infrastructure modules behind the canonical
    `cloop.db` import surface.

Responsibilities:
    - Preserve stable database connection, schema, and vector APIs for callers and tests
    - Keep facade-owned mutable schema globals patchable at this module
    - Delegate implementation details to focused internal infrastructure modules

Non-scope:
    - Feature-level repositories or business-rule orchestration
    - Inline ownership of the full schema SQL and migration implementations

Scope:
    - Public database facade only
    - No transport or domain logic above infrastructure concerns

Usage:
    Import from `cloop.db` for schema bootstrapping, connection context
    managers, vector-extension status, and health checks.

Invariants/Assumptions:
    - External callers continue using `cloop.db` instead of `cloop._db.*`
    - `_CORE_MIGRATIONS` and `PRAGMAS` remain patchable at this facade for tests
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ._db.connections import apply_pragmas as _apply_pragmas_impl
from ._db.connections import connect as _connect_impl
from ._db.schema_data import _CORE_MIGRATIONS as _DEFAULT_CORE_MIGRATIONS
from ._db.schema_data import _CORE_SCHEMA as _DEFAULT_CORE_SCHEMA
from ._db.schema_data import (
    _IDEMPOTENCY_PENDING_POLL_SECONDS as _DEFAULT_IDEMPOTENCY_PENDING_POLL_SECONDS,
)
from ._db.schema_data import (
    _IDEMPOTENCY_PENDING_WAIT_SECONDS as _DEFAULT_IDEMPOTENCY_PENDING_WAIT_SECONDS,
)
from ._db.schema_data import _RAG_SCHEMA as _DEFAULT_RAG_SCHEMA
from ._db.schema_data import PRAGMAS as _DEFAULT_PRAGMAS
from ._db.schema_data import RAG_SCHEMA_VERSION as _DEFAULT_RAG_SCHEMA_VERSION
from ._db.schema_data import SCHEMA_VERSION as _DEFAULT_SCHEMA_VERSION
from ._db.schema_ops import assert_schema as _assert_schema_impl
from ._db.schema_ops import ensure_core_schema as _ensure_core_schema_impl
from ._db.schema_ops import has_application_tables as _has_application_tables_impl
from ._db.schema_ops import initialize_schema_if_needed as _initialize_schema_if_needed_impl
from ._db.schema_ops import migrate_core_db as _migrate_core_db_impl
from ._db.schema_ops import split_sql_statements as _split_sql_statements_impl
from ._db.schema_ops import user_version as _user_version_impl
from ._db.vector import VectorBackend, VectorExtensionManager, VectorExtensionState
from ._db.vector import detect_vector_backend as _detect_vector_backend_impl
from ._db.vector import get_vector_backend as _get_vector_backend_impl
from ._db.vector import get_vector_load_error as _get_vector_load_error_impl
from ._db.vector import get_vector_manager as _get_vector_manager_impl
from ._db.vector import maybe_load_vector_extension as _maybe_load_vector_extension_impl
from ._db.vector import reset_vector_backend as _reset_vector_backend_impl
from ._db.vector import vector_extension_available as _vector_extension_available_impl
from .settings import Settings, get_settings

SCHEMA_VERSION: int = _DEFAULT_SCHEMA_VERSION
RAG_SCHEMA_VERSION: int = _DEFAULT_RAG_SCHEMA_VERSION
PRAGMAS = list(_DEFAULT_PRAGMAS)
_IDEMPOTENCY_PENDING_WAIT_SECONDS = _DEFAULT_IDEMPOTENCY_PENDING_WAIT_SECONDS
_IDEMPOTENCY_PENDING_POLL_SECONDS = _DEFAULT_IDEMPOTENCY_PENDING_POLL_SECONDS
_CORE_SCHEMA = _DEFAULT_CORE_SCHEMA
_CORE_MIGRATIONS: dict[int, str] = dict(_DEFAULT_CORE_MIGRATIONS)
_RAG_SCHEMA = _DEFAULT_RAG_SCHEMA


def _get_vector_manager() -> VectorExtensionManager:
    return _get_vector_manager_impl()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    _apply_pragmas_impl(conn, pragmas=PRAGMAS)


def _user_version(conn: sqlite3.Connection) -> int:
    return _user_version_impl(conn)


def _has_application_tables(conn: sqlite3.Connection) -> bool:
    return _has_application_tables_impl(conn)


def _assert_schema(conn: sqlite3.Connection, expected: int) -> None:
    _assert_schema_impl(conn, expected)


def _initialize_schema_if_needed(
    conn: sqlite3.Connection,
    schema_sql: str,
    *,
    expected_version: int,
) -> None:
    _initialize_schema_if_needed_impl(conn, schema_sql, expected_version=expected_version)


def _split_sql_statements(script: str) -> list[str]:
    return _split_sql_statements_impl(script)


def migrate_core_db(
    conn: sqlite3.Connection,
    *,
    from_version: int,
    to_version: int,
) -> None:
    _migrate_core_db_impl(
        conn,
        from_version=from_version,
        to_version=to_version,
        migrations=_CORE_MIGRATIONS,
    )


def ensure_core_schema(conn: sqlite3.Connection) -> None:
    _ensure_core_schema_impl(
        conn,
        core_schema=_CORE_SCHEMA,
        schema_version=SCHEMA_VERSION,
        migrations=_CORE_MIGRATIONS,
    )


def _detect_vector_backend(conn: sqlite3.Connection) -> VectorBackend:
    return _detect_vector_backend_impl(conn)


def _connect(path: Path) -> sqlite3.Connection:
    return _connect_impl(path, pragmas=PRAGMAS)


@contextmanager
def core_connection(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    settings = settings or get_settings()
    conn = _connect(settings.core_db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def rag_connection(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    settings = settings or get_settings()
    conn = _connect(settings.rag_db_path)
    _maybe_load_vector_extension(conn, settings)
    try:
        yield conn
    finally:
        conn.close()


def _maybe_load_vector_extension(conn: sqlite3.Connection, settings: Settings) -> None:
    _maybe_load_vector_extension_impl(conn, extension_path=settings.sqlite_vector_extension)


def vector_extension_available() -> bool:
    return _vector_extension_available_impl()


def get_vector_backend() -> VectorBackend:
    return _get_vector_backend_impl()


def get_vector_load_error() -> str | None:
    """Return the error message from the last vector extension load attempt, if any."""
    return _get_vector_load_error_impl()


def reset_vector_backend() -> None:
    """Reset vector extension state to allow re-detection.

    Call this when vector operations fail to force re-detection on next use.
    """
    _reset_vector_backend_impl()


def init_core_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with core_connection(settings) as conn:
        ensure_core_schema(conn)


def init_rag_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with rag_connection(settings) as conn:
        _initialize_schema_if_needed(conn, _RAG_SCHEMA, expected_version=RAG_SCHEMA_VERSION)


def init_databases(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    init_core_db(settings)
    init_rag_db(settings)
    with core_connection(settings) as core_conn:
        _assert_schema(core_conn, SCHEMA_VERSION)
    with rag_connection(settings) as rag_conn:
        _assert_schema(rag_conn, RAG_SCHEMA_VERSION)


def get_core_schema_version(settings: Settings | None = None) -> int:
    """Get current core database schema version.

    Args:
        settings: Application settings. Uses global settings if not provided.

    Returns:
        The current schema version number (PRAGMA user_version).
        Returns 0 if database does not exist or is uninitialized.
    """
    settings = settings or get_settings()
    if not settings.core_db_path.exists():
        return 0
    with core_connection(settings) as conn:
        return _user_version(conn)


def get_rag_schema_version(settings: Settings | None = None) -> int:
    """Get current RAG database schema version.

    Args:
        settings: Application settings. Uses global settings if not provided.

    Returns:
        The current schema version number (PRAGMA user_version).
        Returns 0 if database does not exist or is uninitialized.
    """
    settings = settings or get_settings()
    if not settings.rag_db_path.exists():
        return 0
    with rag_connection(settings) as conn:
        return _user_version(conn)


def check_database_connectivity(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Check connectivity to both core and RAG databases.

    This function performs lightweight SELECT 1 queries to verify that
    both databases are accessible and responding. Used by the /health
    endpoint to report actual dependency status.

    Args:
        settings: Application settings. Uses global settings if not provided.

    Returns:
        A dict with keys 'core_db' and 'rag_db', each containing:
            - ok: bool - whether the database is accessible
            - latency_ms: float - time taken for SELECT 1 query in milliseconds
            - error: str | None - error message if check failed
    """
    settings = settings or get_settings()
    results: dict[str, dict[str, Any]] = {}

    core_result: dict[str, Any] = {"ok": False, "latency_ms": 0.0, "error": None}
    try:
        start = time.monotonic()
        with core_connection(settings) as conn:
            conn.execute("SELECT 1").fetchone()
        core_result["latency_ms"] = (time.monotonic() - start) * 1000
        core_result["ok"] = True
    except (sqlite3.Error, OSError) as e:
        core_result["error"] = f"{type(e).__name__}: {e}"
    results["core_db"] = core_result

    rag_result: dict[str, Any] = {"ok": False, "latency_ms": 0.0, "error": None}
    try:
        start = time.monotonic()
        with rag_connection(settings) as conn:
            conn.execute("SELECT 1").fetchone()
        rag_result["latency_ms"] = (time.monotonic() - start) * 1000
        rag_result["ok"] = True
    except (sqlite3.Error, OSError) as e:
        rag_result["error"] = f"{type(e).__name__}: {e}"
    results["rag_db"] = rag_result

    return results


__all__ = [
    "VectorBackend",
    "VectorExtensionManager",
    "VectorExtensionState",
    "SCHEMA_VERSION",
    "RAG_SCHEMA_VERSION",
    "PRAGMAS",
    "_IDEMPOTENCY_PENDING_WAIT_SECONDS",
    "_IDEMPOTENCY_PENDING_POLL_SECONDS",
    "_CORE_SCHEMA",
    "_CORE_MIGRATIONS",
    "_RAG_SCHEMA",
    "_get_vector_manager",
    "_apply_pragmas",
    "_user_version",
    "_has_application_tables",
    "_assert_schema",
    "_initialize_schema_if_needed",
    "_split_sql_statements",
    "migrate_core_db",
    "ensure_core_schema",
    "_detect_vector_backend",
    "_connect",
    "core_connection",
    "rag_connection",
    "_maybe_load_vector_extension",
    "vector_extension_available",
    "get_vector_backend",
    "get_vector_load_error",
    "reset_vector_backend",
    "init_core_db",
    "init_rag_db",
    "init_databases",
    "get_core_schema_version",
    "get_rag_schema_version",
    "check_database_connectivity",
]
