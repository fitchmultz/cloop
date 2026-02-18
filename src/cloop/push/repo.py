"""Database repository for push subscription management.

Purpose:
    Provide SQLite operations for push subscription persistence.

Responsibilities:
    - Upsert subscriptions (insert new or update existing)
    - List active subscriptions for broadcast
    - Deactivate subscriptions when push fails (404/410)

Non-scope:
    - Push message construction (see service.py)
    - HTTP endpoint handling (see routes/push.py)
"""

import sqlite3


def upsert_subscription(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
    conn: sqlite3.Connection,
) -> int:
    """Insert or update a push subscription.

    Args:
        endpoint: Push service endpoint URL
        p256dh: ECDH public key
        auth: Authentication secret
        user_agent: Optional client user agent
        conn: SQLite connection to core database

    Returns:
        Row ID of the subscription
    """
    cursor = conn.execute(
        """
        INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent, active)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(endpoint) DO UPDATE SET
            p256dh = excluded.p256dh,
            auth = excluded.auth,
            user_agent = excluded.user_agent,
            active = 1,
            updated_at = CURRENT_TIMESTAMP
        """,
        (endpoint, p256dh, auth, user_agent),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


def list_active(*, conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """List all active push subscriptions.

    Args:
        conn: SQLite connection to core database

    Returns:
        List of subscription rows
    """
    return conn.execute(
        "SELECT * FROM push_subscriptions WHERE active = 1 ORDER BY id ASC"
    ).fetchall()


def deactivate_endpoint(*, endpoint: str, conn: sqlite3.Connection) -> None:
    """Mark a subscription as inactive (e.g., after 404/410 response).

    Args:
        endpoint: Push service endpoint URL
        conn: SQLite connection to core database
    """
    conn.execute(
        """
        UPDATE push_subscriptions
        SET active = 0, updated_at = CURRENT_TIMESTAMP
        WHERE endpoint = ?
        """,
        (endpoint,),
    )
    conn.commit()
