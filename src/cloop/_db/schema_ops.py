"""Schema validation and migration helpers.

Purpose:
    Provide reusable schema-version checks, bootstrap helpers, and
    migration execution for the `cloop.db` facade.

Responsibilities:
    - Read and validate SQLite `PRAGMA user_version` values
    - Bootstrap versioned schemas safely for fresh databases
    - Apply migrations atomically with per-migration savepoints

Non-scope:
    - Connection lifecycle management or settings lookup
    - Feature-layer repositories or business logic

Scope:
    - Shared schema operation primitives for core and RAG databases
    - No ownership of facade-level mutable schema globals

Usage:
    Imported by `cloop.db`, which passes the current facade schema data
    into these helpers.

Invariants/Assumptions:
    - Migration versions are contiguous from `from_version + 1` to `to_version`
    - Migrations must preserve savepoint semantics by executing statement-by-statement
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping


def user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def has_application_tables(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return bool(rows)


def assert_schema(conn: sqlite3.Connection, expected: int) -> None:
    found = user_version(conn)
    if found != expected:
        raise RuntimeError(f"schema_mismatch: expected={expected} found={found}")


def initialize_schema_if_needed(
    conn: sqlite3.Connection,
    schema_sql: str,
    *,
    expected_version: int,
) -> None:
    version = user_version(conn)
    if version == 0:
        if has_application_tables(conn):
            raise RuntimeError("schema_mismatch: detected unversioned tables")
        conn.executescript(schema_sql)
        conn.execute(f"PRAGMA user_version = {expected_version}")
        conn.commit()
        return
    if version != expected_version:
        raise RuntimeError(f"schema_mismatch: expected={expected_version} found={version}")


def split_sql_statements(script: str) -> list[str]:
    """Split a SQL script into individual statements.

    Handles comments and semicolon-separated statements, filtering out
    empty statements. This is needed because conn.executescript() commits
    any pending transaction, which would destroy savepoints.
    """
    statements: list[str] = []
    current: list[str] = []

    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue

        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip()
            if stmt and stmt != ";":
                statements.append(stmt)
            current = []

    if current:
        stmt = "\n".join(current).strip()
        if stmt and stmt != ";":
            statements.append(stmt)

    return statements


def migrate_core_db(
    conn: sqlite3.Connection,
    *,
    from_version: int,
    to_version: int,
    migrations: Mapping[int, str],
) -> None:
    """Apply pending schema migrations with savepoint protection.

    Each migration is wrapped in a SAVEPOINT to ensure atomic per-migration
    behavior. If a migration fails, its savepoint is rolled back before
    re-raising the exception, leaving the database at the last successful
    migration version.

    Note: We use execute() for each statement instead of executescript()
    because executescript() commits the pending transaction, which would
    destroy our savepoints and prevent rollback.
    """
    if from_version >= to_version:
        return
    for version in range(from_version + 1, to_version + 1):
        migration = migrations.get(version)
        if migration is None:
            raise RuntimeError(f"missing core migration for version {version}")
        savepoint_name = f"migration_{version}"
        conn.execute(f"SAVEPOINT {savepoint_name}")
        try:
            for stmt in split_sql_statements(migration):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
            raise
    conn.commit()


def ensure_core_schema(
    conn: sqlite3.Connection,
    *,
    core_schema: str,
    schema_version: int,
    migrations: Mapping[int, str],
) -> None:
    version = user_version(conn)
    if version == 0:
        if has_application_tables(conn):
            raise RuntimeError("schema_mismatch: detected unversioned tables")
        conn.executescript(core_schema)
        conn.execute(f"PRAGMA user_version = {schema_version}")
        conn.commit()
        return
    if version > schema_version:
        raise RuntimeError(f"schema_mismatch: expected={schema_version} found={version}")
    if version < schema_version:
        migrate_core_db(
            conn,
            from_version=version,
            to_version=schema_version,
            migrations=migrations,
        )


__all__ = [
    "assert_schema",
    "ensure_core_schema",
    "has_application_tables",
    "initialize_schema_if_needed",
    "migrate_core_db",
    "split_sql_statements",
    "user_version",
]
