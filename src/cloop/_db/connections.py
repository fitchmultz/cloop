"""Low-level SQLite connection helpers.

Purpose:
    Open SQLite connections with consistent row handling and PRAGMA setup
    for the database infrastructure facade.

Responsibilities:
    - Apply configured SQLite PRAGMAs to each opened connection
    - Configure row factories consistently for repository consumers
    - Close partially initialized connections on setup failure

Non-scope:
    - Schema migration orchestration or schema version checks
    - Feature-specific query logic above raw connection management

Scope:
    - Reusable low-level connection setup only
    - No application settings resolution or context management policy

Usage:
    Called by `cloop.db` wrappers that resolve settings and expose public
    context managers.

Invariants/Assumptions:
    - Returned connections use `sqlite3.Row` row factories
    - Failed setup never leaks open SQLite connections
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

type PragmaSetting = tuple[str, str]


def apply_pragmas(
    conn: sqlite3.Connection,
    *,
    pragmas: Sequence[PragmaSetting],
) -> None:
    for pragma, value in pragmas:
        conn.execute(f"PRAGMA {pragma}={value}")


def connect(
    path: Path,
    *,
    pragmas: Sequence[PragmaSetting],
) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    try:
        conn.row_factory = sqlite3.Row
        apply_pragmas(conn, pragmas=pragmas)
        return conn
    except Exception:
        conn.close()
        raise


__all__ = ["PragmaSetting", "apply_pragmas", "connect"]
