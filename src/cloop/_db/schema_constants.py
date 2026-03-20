"""Database schema constants and PRAGMA defaults.

Purpose:
    Store schema-version numbers, SQLite PRAGMA defaults, and related
    infrastructure constants shared by database bootstrap code.

Responsibilities:
    - Define current core and RAG schema versions
    - Hold canonical PRAGMA defaults for SQLite connections
    - Keep related infrastructure constants near schema metadata

Non-scope:
    - Bootstrap schema SQL and migration scripts
    - Runtime migration or connection behavior

Scope:
    - Static constants for database infrastructure only
    - No SQL execution or stateful orchestration

Usage:
    Imported by `cloop.db` and sibling database infrastructure modules.

Invariants/Assumptions:
    - Version constants stay aligned with the canonical schema SQL
    - PRAGMA defaults remain safe for all supported SQLite callers
"""

from __future__ import annotations

SCHEMA_VERSION: int = 41
RAG_SCHEMA_VERSION: int = 1

PRAGMAS = [
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("foreign_keys", "ON"),
    ("cache_size", "-20000"),
    ("temp_store", "MEMORY"),
]

_IDEMPOTENCY_PENDING_WAIT_SECONDS = 15.0
_IDEMPOTENCY_PENDING_POLL_SECONDS = 0.05

__all__ = [
    "SCHEMA_VERSION",
    "RAG_SCHEMA_VERSION",
    "PRAGMAS",
    "_IDEMPOTENCY_PENDING_WAIT_SECONDS",
    "_IDEMPOTENCY_PENDING_POLL_SECONDS",
]
