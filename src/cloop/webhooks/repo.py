"""Webhook repository for subscriptions, logical deliveries, and attempts.

Purpose:
    Own webhook persistence and transactional claim/finalize operations.

Responsibilities:
    - CRUD for webhook subscriptions
    - Queue logical deliveries without committing caller-owned mutations
    - Atomically claim delivery attempts for worker processing
    - Persist durable per-attempt outcomes and logical delivery summaries

Non-scope:
    - Network delivery logic
    - Signature generation or verification
    - HTTP route serialization

Invariants/Assumptions:
    - Queueing functions are transaction-neutral.
    - Worker claim/finalize functions own their own transactions.
    - Logical delivery status is separate from the per-attempt history table.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any
from urllib.parse import urlparse

from .models import (
    DeliveryAttemptStatus,
    DeliveryStatus,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)


def _validate_url(url: str) -> None:
    """Validate that a subscription URL is syntactically valid and HTTPS-only."""
    try:
        parsed = urlparse(url)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid URL: {url}") from exc

    if parsed.scheme != "https":
        raise ValueError(f"URL scheme must be https, got: {parsed.scheme or '<missing>'}")
    if not parsed.netloc:
        raise ValueError(f"URL must have a host: {url}")


def _row_to_subscription(row: sqlite3.Row) -> WebhookSubscription:
    event_types = ["*"]
    if row["event_types"]:
        parsed = json.loads(row["event_types"])
        if isinstance(parsed, list):
            event_types = [str(item) for item in parsed]
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
        active_attempt_number=row["active_attempt_number"],
        last_attempted_at=row["last_attempted_at"],
        next_retry_at_epoch=row["next_retry_at_epoch"],
        lease_owner=row["lease_owner"],
        lease_until_epoch=row["lease_until_epoch"],
        last_connect_ip=row["last_connect_ip"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_attempt(row: sqlite3.Row) -> WebhookDeliveryAttempt:
    request_bytes = row["request_bytes"]
    if isinstance(request_bytes, memoryview):
        request_bytes = request_bytes.tobytes()
    return WebhookDeliveryAttempt(
        id=row["id"],
        delivery_id=row["delivery_id"],
        attempt_number=row["attempt_number"],
        status=DeliveryAttemptStatus(row["status"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        request_bytes=request_bytes,
        signature_header=row["signature_header"],
        http_status=row["http_status"],
        response_body=row["response_body"],
        error_message=row["error_message"],
        connect_ip=row["connect_ip"],
        created_at=row["created_at"],
    )


def create_subscription(
    *,
    url: str,
    secret: str,
    event_types: list[str],
    description: str | None,
    conn: sqlite3.Connection,
) -> WebhookSubscription:
    """Create a webhook subscription."""
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
    """List active webhook subscriptions."""
    rows = conn.execute(
        "SELECT * FROM webhook_subscriptions WHERE active = 1 ORDER BY created_at DESC"
    ).fetchall()
    return [_row_to_subscription(row) for row in rows]


def get_subscription(
    *, subscription_id: int, conn: sqlite3.Connection
) -> WebhookSubscription | None:
    """Fetch a subscription by ID."""
    row = conn.execute(
        "SELECT * FROM webhook_subscriptions WHERE id = ?",
        (subscription_id,),
    ).fetchone()
    return _row_to_subscription(row) if row is not None else None


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
    """Update a subscription."""
    updates: dict[str, Any] = {}
    if url is not None:
        _validate_url(url)
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

    params = [*updates.values(), subscription_id]
    set_clause = ", ".join(f"{column} = ?" for column in updates)
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
    """Delete a subscription."""
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
    """Queue a logical webhook delivery without committing the outer transaction."""
    cursor = conn.execute(
        """
        INSERT INTO webhook_deliveries (
            subscription_id,
            event_id,
            event_type,
            source_payload_json,
            status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            subscription_id,
            event_id,
            event_type,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            DeliveryStatus.QUEUED.value,
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
    """Fetch a logical delivery by ID."""
    row = conn.execute(
        "SELECT * FROM webhook_deliveries WHERE id = ?",
        (delivery_id,),
    ).fetchone()
    return _row_to_delivery(row) if row is not None else None


def list_deliveries_for_subscription(
    *,
    subscription_id: int,
    conn: sqlite3.Connection,
    limit: int = 100,
) -> list[WebhookDelivery]:
    """List recent logical deliveries for one subscription."""
    rows = conn.execute(
        """
        SELECT *
        FROM webhook_deliveries
        WHERE subscription_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (subscription_id, limit),
    ).fetchall()
    return [_row_to_delivery(row) for row in rows]


def list_attempts_for_delivery(
    *, delivery_id: int, conn: sqlite3.Connection
) -> list[WebhookDeliveryAttempt]:
    """Return durable attempt history for a logical delivery."""
    rows = conn.execute(
        """
        SELECT *
        FROM webhook_delivery_attempts
        WHERE delivery_id = ?
        ORDER BY attempt_number DESC
        """,
        (delivery_id,),
    ).fetchall()
    return [_row_to_attempt(row) for row in rows]


def claim_delivery_attempt(
    *,
    conn: sqlite3.Connection,
    owner_token: str,
    lease_seconds: int,
    delivery_id: int | None = None,
) -> tuple[WebhookDelivery, WebhookDeliveryAttempt] | None:
    """Atomically claim one eligible logical delivery and create its attempt row."""
    now_epoch = int(time.time())
    lease_until_epoch = now_epoch + max(1, lease_seconds)

    conn.execute("BEGIN IMMEDIATE")
    try:
        params: list[Any] = [
            DeliveryStatus.QUEUED.value,
            now_epoch,
            DeliveryStatus.IN_FLIGHT.value,
            now_epoch,
        ]
        sql = """
            SELECT *
            FROM webhook_deliveries
            WHERE (
                (status = ? AND (next_retry_at_epoch IS NULL OR next_retry_at_epoch <= ?))
                OR (status = ? AND lease_until_epoch IS NOT NULL AND lease_until_epoch <= ?)
            )
        """
        if delivery_id is not None:
            sql += " AND id = ?"
            params.append(delivery_id)
        sql += " ORDER BY COALESCE(next_retry_at_epoch, 0) ASC, created_at ASC, id ASC LIMIT 1"

        row = conn.execute(sql, params).fetchone()
        if row is None:
            conn.rollback()
            return None

        if row["status"] == DeliveryStatus.IN_FLIGHT.value:
            conn.execute(
                """
                UPDATE webhook_delivery_attempts
                SET status = ?,
                    finished_at = ?,
                    error_message = ?
                WHERE delivery_id = ?
                  AND status = ?
                """,
                (
                    DeliveryAttemptStatus.FAILED.value,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_epoch)),
                    "Attempt lease expired and was reclaimed by a new worker",
                    row["id"],
                    DeliveryAttemptStatus.RUNNING.value,
                ),
            )

        claimed = conn.execute(
            """
            UPDATE webhook_deliveries
            SET status = ?,
                lease_owner = ?,
                lease_until_epoch = ?,
                active_attempt_number = attempt_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND (
                (status = ? AND (next_retry_at_epoch IS NULL OR next_retry_at_epoch <= ?))
                OR (status = ? AND lease_until_epoch IS NOT NULL AND lease_until_epoch <= ?)
              )
            """,
            (
                DeliveryStatus.IN_FLIGHT.value,
                owner_token,
                lease_until_epoch,
                row["id"],
                DeliveryStatus.QUEUED.value,
                now_epoch,
                DeliveryStatus.IN_FLIGHT.value,
                now_epoch,
            ),
        )
        if claimed.rowcount != 1:
            conn.rollback()
            return None

        attempt_number_row = conn.execute(
            """
            SELECT COALESCE(MAX(attempt_number), 0) AS attempt_number
            FROM webhook_delivery_attempts
            WHERE delivery_id = ?
            """,
            (row["id"],),
        ).fetchone()
        attempt_number = int(attempt_number_row["attempt_number"]) + 1
        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_epoch))
        attempt_cursor = conn.execute(
            """
            INSERT INTO webhook_delivery_attempts (
                delivery_id,
                attempt_number,
                status,
                started_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (row["id"], attempt_number, DeliveryAttemptStatus.RUNNING.value, started_at),
        )
        attempt_row = conn.execute(
            "SELECT * FROM webhook_delivery_attempts WHERE id = ?",
            (attempt_cursor.lastrowid,),
        ).fetchone()
        delivery_row = conn.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?",
            (row["id"],),
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if attempt_row is None or delivery_row is None:
        raise RuntimeError("webhook_delivery_claim_failed")
    return _row_to_delivery(delivery_row), _row_to_attempt(attempt_row)


def finalize_delivery_attempt(
    *,
    conn: sqlite3.Connection,
    delivery_id: int,
    attempt_number: int,
    owner_token: str,
    delivery_status: DeliveryStatus,
    attempt_status: DeliveryAttemptStatus,
    request_bytes: bytes,
    signature_header: str,
    started_at: str,
    finished_at: str,
    http_status: int | None,
    response_body: str | None,
    error_message: str | None,
    connect_ip: str | None,
    next_retry_at_epoch: int | None,
) -> WebhookDelivery:
    """Persist the final outcome for one claimed delivery attempt."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            UPDATE webhook_delivery_attempts
            SET status = ?,
                finished_at = ?,
                request_bytes = ?,
                signature_header = ?,
                http_status = ?,
                response_body = ?,
                error_message = ?,
                connect_ip = ?
            WHERE delivery_id = ?
              AND attempt_number = ?
              AND status = ?
            """,
            (
                attempt_status.value,
                finished_at,
                sqlite3.Binary(request_bytes),
                signature_header,
                http_status,
                response_body,
                error_message,
                connect_ip,
                delivery_id,
                attempt_number,
                DeliveryAttemptStatus.RUNNING.value,
            ),
        )
        cursor = conn.execute(
            """
            UPDATE webhook_deliveries
            SET status = ?,
                attempt_count = ?,
                active_attempt_number = NULL,
                lease_owner = NULL,
                lease_until_epoch = NULL,
                last_attempt_payload_json = ?,
                http_status = ?,
                response_body = ?,
                error_message = ?,
                signature_header = ?,
                last_attempted_at = ?,
                next_retry_at_epoch = ?,
                last_connect_ip = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND lease_owner = ?
            """,
            (
                delivery_status.value,
                attempt_number,
                request_bytes.decode("utf-8"),
                http_status,
                response_body,
                error_message,
                signature_header,
                finished_at,
                next_retry_at_epoch,
                connect_ip,
                delivery_id,
                owner_token,
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise RuntimeError("webhook_delivery_finalize_lost_claim")

        row = conn.execute(
            "SELECT * FROM webhook_deliveries WHERE id = ?", (delivery_id,)
        ).fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if row is None:
        raise RuntimeError("webhook_delivery_finalize_missing_row")
    return _row_to_delivery(row)
