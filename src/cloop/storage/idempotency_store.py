"""Idempotency key persistence.

Purpose:
    Own the database-backed claim/replay lifecycle for idempotent mutations.

Responsibilities:
    - Purge expired keys
    - Claim or replay a request by scope/key/hash
    - Finalize a stored response

Non-scope:
    - Request hashing or scope construction
    - HTTP/MCP transport behavior

Invariants/Assumptions:
    - `(scope, idempotency_key)` is unique.
    - Pending claims eventually finalize or expire.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Mapping
from typing import Any

_IDEMPOTENCY_PENDING_WAIT_SECONDS = 15.0
_IDEMPOTENCY_PENDING_POLL_SECONDS = 0.05


def purge_expired_idempotency_keys(*, conn: sqlite3.Connection) -> int:
    """Delete expired idempotency rows."""
    cursor = conn.execute("DELETE FROM idempotency_keys WHERE expires_at < CURRENT_TIMESTAMP")
    conn.commit()
    return cursor.rowcount


def _read_idempotency_row(
    *,
    scope: str,
    idempotency_key: str,
    conn: sqlite3.Connection,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT request_hash,
               response_status,
               response_body_json,
               datetime(expires_at) < datetime('now') AS is_expired
        FROM idempotency_keys
        WHERE scope = ? AND idempotency_key = ?
        """,
        (scope, idempotency_key),
    ).fetchone()


def _try_claim_expired_idempotency_key(
    *,
    scope: str,
    idempotency_key: str,
    request_hash: str,
    expires_at: str,
    conn: sqlite3.Connection,
) -> bool:
    cursor = conn.execute(
        """
        UPDATE idempotency_keys
        SET request_hash = ?,
            response_status = NULL,
            response_body_json = NULL,
            created_at = CURRENT_TIMESTAMP,
            last_seen_at = CURRENT_TIMESTAMP,
            expires_at = ?
        WHERE scope = ?
          AND idempotency_key = ?
          AND datetime(expires_at) < datetime('now')
        """,
        (request_hash, expires_at, scope, idempotency_key),
    )
    conn.commit()
    return cursor.rowcount == 1


def claim_or_replay_idempotency(
    *,
    scope: str,
    idempotency_key: str,
    request_hash: str,
    expires_at: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Claim a key or return a prior response."""
    from ..idempotency import IdempotencyConflictError

    purge_expired_idempotency_keys(conn=conn)
    try:
        conn.execute(
            """
            INSERT INTO idempotency_keys
                (scope, idempotency_key, request_hash, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (scope, idempotency_key, request_hash, expires_at),
        )
        conn.commit()
        return {"is_new": True, "replay": None}
    except sqlite3.IntegrityError:
        conn.rollback()

    deadline = time.monotonic() + _IDEMPOTENCY_PENDING_WAIT_SECONDS
    while True:
        row = _read_idempotency_row(
            scope=scope,
            idempotency_key=idempotency_key,
            conn=conn,
        )
        if row is None:
            try:
                conn.execute(
                    """
                    INSERT INTO idempotency_keys
                        (scope, idempotency_key, request_hash, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (scope, idempotency_key, request_hash, expires_at),
                )
                conn.commit()
                return {"is_new": True, "replay": None}
            except sqlite3.IntegrityError:
                conn.rollback()
                continue

        stored_hash = row["request_hash"]
        response_status = row["response_status"]
        response_body_json = row["response_body_json"]
        is_expired = bool(row["is_expired"])

        if is_expired:
            if _try_claim_expired_idempotency_key(
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expires_at=expires_at,
                conn=conn,
            ):
                return {"is_new": True, "replay": None}
            continue

        if stored_hash != request_hash:
            raise IdempotencyConflictError(
                "Idempotency key conflict: "
                f"key '{idempotency_key}' already used with different payload"
            )

        if response_status is not None and response_body_json is not None:
            conn.execute(
                """
                UPDATE idempotency_keys
                SET last_seen_at = CURRENT_TIMESTAMP
                WHERE scope = ? AND idempotency_key = ?
                """,
                (scope, idempotency_key),
            )
            conn.commit()
            return {
                "is_new": False,
                "replay": {
                    "status_code": response_status,
                    "response_body": json.loads(response_body_json),
                },
            }

        if time.monotonic() >= deadline:
            raise IdempotencyConflictError(
                f"Idempotency key '{idempotency_key}' is currently in progress; retry shortly"
            )
        time.sleep(_IDEMPOTENCY_PENDING_POLL_SECONDS)


def finalize_idempotency_response(
    *,
    scope: str,
    idempotency_key: str,
    response_status: int,
    response_body: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist the finalized response for an idempotent mutation."""
    conn.execute(
        """
        UPDATE idempotency_keys
        SET response_status = ?,
            response_body_json = ?,
            last_seen_at = CURRENT_TIMESTAMP
        WHERE scope = ? AND idempotency_key = ?
        """,
        (response_status, json.dumps(response_body), scope, idempotency_key),
    )
    conn.commit()
