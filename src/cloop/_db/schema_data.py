"""Database schema definition public surface for internal modules.

Purpose:
    Re-export focused schema-definition modules behind one internal
    `cloop._db.schema_data` surface.

Responsibilities:
    - Keep schema constants, bootstrap SQL, and migrations discoverable
    - Preserve one internal import path for database infrastructure callers
    - Avoid a monolithic schema-definition module

Non-scope:
    - Executing migrations or opening database connections
    - Owning public application imports outside `cloop.db`

Scope:
    - Internal schema-definition facade only
    - No runtime database behavior

Usage:
    Imported by `cloop.db` and sibling internal infrastructure modules.

Invariants/Assumptions:
    - Callers should not bypass `cloop.db` for public use
    - Schema definitions remain split by concern behind this facade
"""

from __future__ import annotations

from .core_migrations import _CORE_MIGRATIONS
from .core_schema import _CORE_SCHEMA
from .rag_schema import _RAG_SCHEMA
from .schema_constants import (
    _IDEMPOTENCY_PENDING_POLL_SECONDS,
    _IDEMPOTENCY_PENDING_WAIT_SECONDS,
    PRAGMAS,
    RAG_SCHEMA_VERSION,
    SCHEMA_VERSION,
)

__all__ = [
    "SCHEMA_VERSION",
    "RAG_SCHEMA_VERSION",
    "PRAGMAS",
    "_IDEMPOTENCY_PENDING_WAIT_SECONDS",
    "_IDEMPOTENCY_PENDING_POLL_SECONDS",
    "_CORE_SCHEMA",
    "_CORE_MIGRATIONS",
    "_RAG_SCHEMA",
]
