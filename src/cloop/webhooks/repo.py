"""Webhook repository for database operations.

Purpose:
    Database operations for webhook subscriptions and deliveries.

Responsibilities:
    - CRUD for webhook subscriptions
    - Delivery record storage

Non-scope:
    - Delivery logic (see webhooks/service.py)
    - Signature generation (see webhooks/signer.py)
"""

import json
import sqlite3
from typing import Any
from urllib.parse import urlparse

from .models import DeliveryStatus, WebhookDelivery, WebhookSubscription


def _validate_url(url: str) -> None:
    """Validate that a URL is valid and uses HTTPS.

    Raises:
        ValueError: If the URL is invalid or doesn't use http/https scheme.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL: {url}") from e

    if not parsed.scheme:
        raise ValueError(f"URL must have a scheme (https): {url}")

    if parsed.scheme != "https":
        raise ValueError(f"URL scheme must be https, got: {parsed.scheme}")

    if not parsed.netloc:
        raise ValueError(f"URL must have a host: {url}")


def _row_to_subscription(row: sqlite3.Row) -> WebhookSubscription:
    """Convert a database row to a WebhookSubscription."""
    event_types_str = row["event_types"]
    event_types: list[str] = ["*"]
    if event_types_str:
        try:
            parsed = json.loads(event_types_str)
            if isinstance(parsed, list):
                event_types = parsed
        except json.JSONDecodeError:
            # Fallback to default for malformed JSON
            pass
    return WebhookSubscription(
        id=row["id"],
        url=row["url"],
        secret=row["secret"],
        event_types=event_types,
        active=bool(row["active"]),
        description=row["description"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_delivery(row: sqlite3.Row) -> WebhookDelivery:
    """Convert a database row to a WebhookDelivery."""
    return WebhookDelivery(
        id=row["id"],
        subscription_id=row["subscription_id"],
        event_id=row["event_id"],
        event_type=row["event_type"],
        source_payload_json=row["source_payload_json"],
        last_attempt_payload_json=row["last_attempt_payload_json"],
        status=DeliveryStatus(row["status"]),
        http_status=row["http_status"],
        response_body=row["response_body"],
        error_message=row["error_message"],
        signature_header=row["signature_header"],
        attempt_count=row["attempt_count"],
        last_attempted_at=row["last_attempted_at"],
        next_retry_at=row["next_retry_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_subscription(
    *,
    url: str,
    secret: str,
    event_types: list[str],
    description: str | None,
    conn: sqlite3.Connection,
) -> WebhookSubscription:
    """Create a new webhook subscription."""
    _validate_url(url)
    cursor = conn.execute(
        """
        INSERT INTO webhook_subscriptions (url, secret, event_types, description)
        VALUES (?, ?, ?, ?)
        """,
        (url, secret, json.dumps(event_types), description),
    )
    row = conn.execute(
        "SELECT * FROM webhook_subscriptions WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise RuntimeError("webhook_subscription_create_failed")
    return _row_to_subscription(row)


def list_subscriptions(*, conn: sqlite3.Connection) -> list[WebhookSubscription]:
    """List all webhook subscriptions."""
    rows = conn.execute("SELECT * FROM webhook_subscriptions ORDER BY created_at DESC").fetchall()
    return [_row_to_subscription(row) for row in rows]


def list_active_subscriptions(*, conn: sqlite3.Connection) -> list[WebhookSubscription]:
    """List all active webhook subscriptions."""
    rows = conn.execute(
        "SELECT * FROM webhook_subscriptions WHERE active = 1 ORDER BY created_at DESC"
    ).fetchall()
    return [_row_to_subscription(row) for row in rows]


def get_subscription(
    *, subscription_id: int, conn: sqlite3.Connection
) -> WebhookSubscription | None:
    """Get a webhook subscription by ID."""
    row = conn.execute(
        "SELECT * FROM webhook_subscriptions WHERE id = ?",
        (subscription_id,),
    ).fetchone()
    return _row_to_subscription(row) if row else None


def update_subscription(
    *,
    subscription_id: int,
    url: str | None = None,
    secret: str | None = None,
    event_types: list[str] | None = None,
    active: bool | None = None,
    description: str | None = None,
    conn: sqlite3.Connection,
) -> WebhookSubscription | None:
    """Update a webhook subscription."""
    updates: dict[str, Any] = {}
    if url is not None:
        updates["url"] = url
    if secret is not None:
        updates["secret"] = secret
    if event_types is not None:
        updates["event_types"] = json.dumps(event_types)
    if active is not None:
        updates["active"] = 1 if active else 0
    if description is not None:
        updates["description"] = description

    if not updates:
        return get_subscription(subscription_id=subscription_id, conn=conn)

    set_clause = ", ".join(f"{key} = ?" for key in updates)
    params = list(updates.values()) + [subscription_id]

    conn.execute(
        f"""
        UPDATE webhook_subscriptions
        SET {set_clause}, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        params,
    )
    return get_subscription(subscription_id=subscription_id, conn=conn)


def delete_subscription(*, subscription_id: int, conn: sqlite3.Connection) -> bool:
    """Delete a webhook subscription."""
    cursor = conn.execute(
        "DELETE FROM webhook_subscriptions WHERE id = ?",
        (subscription_id,),
    )
    return cursor.rowcount > 0


def create_delivery(
    *,
    subscription_id: int,
    event_id: int,
    event_type: str,
    payload: dict[str, Any],
    conn: sqlite3.Connection,
) -> WebhookDelivery:
    """Create a new webhook delivery record."""
    cursor = conn.execute(
        """
        INSERT INTO webhook_deliveries
            (subscription_id, event_id, event_type, source_payload_json, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            subscription_id,
            event_id,
            event_type,
            json.dumps(payload),
            DeliveryStatus.PENDING.value,
        ),
    )
    row = conn.execute(
        "SELECT * FROM webhook_deliveries WHERE id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        raise RuntimeError("webhook_delivery_create_failed")
    return _row_to_delivery(row)


def get_delivery(*, delivery_id: int, conn: sqlite3.Connection) -> WebhookDelivery | None:
    """Get a webhook delivery by ID."""
    row = conn.execute(
        "SELECT * FROM webhook_deliveries WHERE id = ?",
        (delivery_id,),
    ).fetchone()
    return _row_to_delivery(row) if row else None


def update_delivery_status(
    *,
    delivery_id: int,
    status: DeliveryStatus,
    signature_header: str | None = None,
    attempt_payload_json: str | None = None,
    last_attempted_at: str | None = None,
    http_status: int | None = None,
    response_body: str | None = None,
    error_message: str | None = None,
    next_retry_at: str | None = None,
    conn: sqlite3.Connection,
) -> None:
    """Update webhook delivery status."""
    conn.execute(
        """
        UPDATE webhook_deliveries
        SET status = ?,
            signature_header = ?,
            last_attempt_payload_json = ?,
            last_attempted_at = ?,
            http_status = ?,
            response_body = ?,
            error_message = ?,
            next_retry_at = ?,
            attempt_count = attempt_count + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            status.value,
            signature_header,
            attempt_payload_json,
            last_attempted_at,
            http_status,
            response_body,
            error_message,
            next_retry_at,
            delivery_id,
        ),
    )


def list_pending_deliveries(*, conn: sqlite3.Connection) -> list[WebhookDelivery]:
    """List all pending webhook deliveries that are ready for retry."""
    rows = conn.execute(
        """
        SELECT * FROM webhook_deliveries
        WHERE status = ?
          AND (next_retry_at IS NULL OR next_retry_at <= datetime('now'))
        ORDER BY created_at ASC
        """,
        (DeliveryStatus.PENDING.value,),
    ).fetchall()
    return [_row_to_delivery(row) for row in rows]


def list_deliveries_for_subscription(
    *,
    subscription_id: int,
    conn: sqlite3.Connection,
    limit: int = 100,
) -> list[WebhookDelivery]:
    """List recent deliveries for a subscription."""
    if not 1 <= limit <= 1000:
        raise ValueError(f"limit must be between 1 and 1000, got: {limit}")
    rows = conn.execute(
        """
        SELECT * FROM webhook_deliveries
        WHERE subscription_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (subscription_id, limit),
    ).fetchall()
    return [_row_to_delivery(row) for row in rows]
