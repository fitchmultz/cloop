"""Internal database infrastructure package.

Purpose:
    Hold focused SQLite infrastructure modules behind the canonical
    `cloop.db` facade.

Responsibilities:
    - Group schema definitions, schema operations, connection helpers, and vector state
    - Keep database infrastructure importable without expanding the public namespace

Scope:
    - Internal organization for database infrastructure only
    - No independent public API outside `cloop.db`

Usage:
    Imported by `cloop.db` and internal infrastructure modules.

Invariants/Assumptions:
    - External callers should continue using `cloop.db`
    - Internal modules may move as long as the facade contract stays stable
"""
