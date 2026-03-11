"""Webhook delivery service with durable attempts and pinned HTTPS transport.

Purpose:
    Queue logical webhook deliveries and execute claimed HTTP attempts safely.

Responsibilities:
    - Queue logical deliveries for loop events without committing caller transactions
    - Resolve and validate webhook targets before outbound delivery
    - Claim, execute, and finalize durable delivery attempts
    - Retry failed deliveries with worker-owned durability

Non-scope:
    - HTTP route handling for subscription CRUD
    - Signature verification on receivers
    - Webhook payload transformation beyond the canonical envelope

Invariants/Assumptions:
    - Exact transmitted bytes are signed and persisted per attempt.
    - Worker processing owns attempt claim/finalize transactions.
    - HTTPS transport is pinned to prevalidated resolved IPs.
"""

from __future__ import annotations

import datetime
import http.client
import ipaddress
import json
import logging
import random
import socket
import sqlite3
import ssl
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from ..settings import Settings, get_settings
from . import repo
from .models import DeliveryAttemptStatus, DeliveryStatus, WebhookDelivery, WebhookDeliveryAttempt
from .signer import sign_bytes

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return the current UTC time in canonical ISO format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _is_safe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Reject internal, special-use, and metadata IPs."""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    if ip == ipaddress.ip_address("169.254.169.254"):
        return False
    return True


def _resolve_safe_delivery_targets(
    url: str,
) -> tuple[tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...], str, int, str]:
    """Resolve an HTTPS target once and validate every resolved connect IP."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("URL must use https and include a host")

    hostname = parsed.hostname
    if not hostname or hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Unsafe or missing hostname")

    port = parsed.port or 443
    infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    resolved_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        if info[0] not in {socket.AF_INET, socket.AF_INET6}:
            continue
        ip = ipaddress.ip_address(info[4][0])
        if not _is_safe_ip(ip):
            raise ValueError(f"Unsafe resolved address: {ip}")
        resolved_ips.append(ip)
    if not resolved_ips:
        raise ValueError("No safe resolved addresses")

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return tuple(dict.fromkeys(resolved_ips)), hostname, port, path


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials a validated IP while verifying the hostname."""

    def __init__(
        self,
        *,
        hostname: str,
        connect_ip: str,
        port: int,
        timeout: float,
    ) -> None:
        ssl_context = ssl.create_default_context()
        super().__init__(hostname, port=port, timeout=timeout, context=ssl_context)
        self._ssl_context = ssl_context
        self._connect_ip = connect_ip

    def connect(self) -> None:
        sock = socket.create_connection((self._connect_ip, self.port), self.timeout)
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


def _send_pinned_webhook_request(
    *,
    url: str,
    payload_bytes: bytes,
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, str, str]:
    """Send a webhook request to one of the prevalidated connect IPs."""
    resolved_ips, hostname, port, path = _resolve_safe_delivery_targets(url)
    last_error: Exception | None = None

    for ip in resolved_ips:
        connection = _PinnedHTTPSConnection(
            hostname=hostname,
            connect_ip=str(ip),
            port=port,
            timeout=timeout_seconds,
        )
        try:
            connection.request("POST", path, body=payload_bytes, headers=headers)
            response = connection.getresponse()
            response_body = response.read().decode("utf-8", errors="replace")[:1000]
            if 300 <= response.status < 400:
                raise RuntimeError(f"Redirects are not allowed: HTTP {response.status}")
            return response.status, response_body, str(ip)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        finally:
            connection.close()

    if last_error is not None:
        raise last_error
    raise RuntimeError("Webhook delivery failed before attempting a connection")


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize payload deterministically for signing and persistence."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _build_delivery_payload(
    *,
    delivery: WebhookDelivery,
    delivered_at: str,
    attempt_number: int,
) -> dict[str, Any]:
    """Build the canonical outbound webhook JSON envelope."""
    return {
        "delivery_id": delivery.id,
        "event_id": delivery.event_id,
        "event_type": delivery.event_type,
        "occurred_at": delivery.created_at,
        "delivered_at": delivered_at,
        "attempt": attempt_number,
        "data": json.loads(delivery.source_payload_json),
    }


def _calculate_retry_delay(attempt_count: int, settings: Settings) -> float:
    """Calculate exponential backoff with bounded jitter."""
    base = settings.webhook_retry_base_delay
    max_delay = settings.webhook_retry_max_delay
    delay = base * (2**attempt_count)
    delay += delay * 0.25 * (2 * random.random() - 1)
    return min(delay, max_delay)


def _should_deliver_event(event_type: str, subscription_event_types: list[str]) -> bool:
    """Return whether a subscription should receive a given event type."""
    return "*" in subscription_event_types or event_type in subscription_event_types


def queue_deliveries(
    *,
    event_id: int,
    event_type: str,
    payload: dict[str, Any],
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> list[int]:
    """Queue logical deliveries for a loop event without committing the caller transaction."""
    _ = settings or get_settings()
    delivery_ids: list[int] = []
    subscriptions = repo.list_active_subscriptions(conn=conn)
    for subscription in subscriptions:
        if not _should_deliver_event(event_type, subscription.event_types):
            continue
        delivery = repo.create_delivery(
            subscription_id=subscription.id,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            conn=conn,
        )
        delivery_ids.append(delivery.id)
    return delivery_ids


def _lease_seconds(settings: Settings) -> int:
    """Choose a webhook in-flight lease long enough to cover one HTTP request."""
    return max(int(settings.webhook_timeout_seconds) + 30, 60)


def deliver_webhook(
    *,
    delivery_id: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
    owner_token: str | None = None,
) -> DeliveryStatus:
    """Claim and execute one logical webhook delivery by ID."""
    settings = settings or get_settings()
    claimed = repo.claim_delivery_attempt(
        conn=conn,
        owner_token=owner_token or f"webhook-{uuid.uuid4()}",
        lease_seconds=_lease_seconds(settings),
        delivery_id=delivery_id,
    )
    if claimed is None:
        delivery = repo.get_delivery(delivery_id=delivery_id, conn=conn)
        return delivery.status if delivery is not None else DeliveryStatus.DEAD_LETTER

    delivery, attempt = claimed
    return _deliver_claimed_webhook(
        delivery=delivery,
        attempt=attempt,
        conn=conn,
        settings=settings,
        owner_token=claimed[0].lease_owner or "",
    )


def _deliver_claimed_webhook(
    *,
    delivery: WebhookDelivery,
    attempt: WebhookDeliveryAttempt,
    conn: sqlite3.Connection,
    settings: Settings,
    owner_token: str,
) -> DeliveryStatus:
    """Execute one already-claimed webhook attempt and persist the final state."""
    subscription = repo.get_subscription(subscription_id=delivery.subscription_id, conn=conn)
    if subscription is None:
        repo.finalize_delivery_attempt(
            conn=conn,
            delivery_id=delivery.id,
            attempt_number=attempt.attempt_number,
            owner_token=owner_token,
            delivery_status=DeliveryStatus.DEAD_LETTER,
            attempt_status=DeliveryAttemptStatus.FAILED,
            request_bytes=b"",
            signature_header="",
            started_at=attempt.started_at,
            finished_at=_utc_now_iso(),
            http_status=None,
            response_body=None,
            error_message="Subscription not found",
            connect_ip=None,
            next_retry_at_epoch=None,
        )
        return DeliveryStatus.DEAD_LETTER

    delivered_at = _utc_now_iso()
    payload = _build_delivery_payload(
        delivery=delivery,
        delivered_at=delivered_at,
        attempt_number=attempt.attempt_number,
    )
    payload_bytes = _canonical_json_bytes(payload)
    timestamp = str(int(time.time()))
    signature_header = sign_bytes(payload_bytes, subscription.secret, timestamp)

    try:
        send_result = _send_pinned_webhook_request(
            url=subscription.url,
            payload_bytes=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": signature_header,
                "X-Webhook-Event": delivery.event_type,
                "X-Webhook-Event-Id": str(delivery.event_id),
                "User-Agent": "cloop-webhook/1.0",
            },
            timeout_seconds=settings.webhook_timeout_seconds,
        )
        if len(send_result) == 2:
            http_status, response_body = send_result
            connect_ip = None
        else:
            http_status, response_body, connect_ip = send_result

        if 200 <= http_status < 300:
            repo.finalize_delivery_attempt(
                conn=conn,
                delivery_id=delivery.id,
                attempt_number=attempt.attempt_number,
                owner_token=owner_token,
                delivery_status=DeliveryStatus.SUCCEEDED,
                attempt_status=DeliveryAttemptStatus.SUCCEEDED,
                request_bytes=payload_bytes,
                signature_header=signature_header,
                started_at=attempt.started_at,
                finished_at=delivered_at,
                http_status=http_status,
                response_body=response_body,
                error_message=None,
                connect_ip=connect_ip,
                next_retry_at_epoch=None,
            )
            return DeliveryStatus.SUCCEEDED

        error_message = f"HTTP {http_status}: Non-2xx response"
        delivery_status = DeliveryStatus.DEAD_LETTER
        next_retry_at_epoch: int | None = None
        if attempt.attempt_number < settings.webhook_max_retries:
            delivery_status = DeliveryStatus.QUEUED
            next_retry_at_epoch = int(
                time.time() + _calculate_retry_delay(attempt.attempt_number, settings)
            )

        repo.finalize_delivery_attempt(
            conn=conn,
            delivery_id=delivery.id,
            attempt_number=attempt.attempt_number,
            owner_token=owner_token,
            delivery_status=delivery_status,
            attempt_status=DeliveryAttemptStatus.FAILED,
            request_bytes=payload_bytes,
            signature_header=signature_header,
            started_at=attempt.started_at,
            finished_at=delivered_at,
            http_status=http_status,
            response_body=response_body,
            error_message=error_message,
            connect_ip=connect_ip,
            next_retry_at_epoch=next_retry_at_epoch,
        )
        return delivery_status
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)[:500]
        delivery_status = DeliveryStatus.DEAD_LETTER
        next_retry_at_epoch: int | None = None
        if attempt.attempt_number < settings.webhook_max_retries:
            delivery_status = DeliveryStatus.QUEUED
            next_retry_at_epoch = int(
                time.time() + _calculate_retry_delay(attempt.attempt_number, settings)
            )

        repo.finalize_delivery_attempt(
            conn=conn,
            delivery_id=delivery.id,
            attempt_number=attempt.attempt_number,
            owner_token=owner_token,
            delivery_status=delivery_status,
            attempt_status=DeliveryAttemptStatus.FAILED,
            request_bytes=payload_bytes,
            signature_header=signature_header,
            started_at=attempt.started_at,
            finished_at=delivered_at,
            http_status=None,
            response_body=None,
            error_message=error_message,
            connect_ip=None,
            next_retry_at_epoch=next_retry_at_epoch,
        )
        return delivery_status


def process_pending_deliveries(
    *,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
    batch_size: int = 100,
    owner_token: str | None = None,
) -> dict[str, int]:
    """Claim and process up to `batch_size` eligible deliveries."""
    settings = settings or get_settings()
    results = {"succeeded": 0, "queued": 0, "dead_letter": 0}
    worker_token = owner_token or f"webhook-worker-{uuid.uuid4()}"

    for index in range(batch_size):
        claimed = repo.claim_delivery_attempt(
            conn=conn,
            owner_token=f"{worker_token}:{index}",
            lease_seconds=_lease_seconds(settings),
        )
        if claimed is None:
            break
        delivery, attempt = claimed
        status = _deliver_claimed_webhook(
            delivery=delivery,
            attempt=attempt,
            conn=conn,
            settings=settings,
            owner_token=delivery.lease_owner or "",
        )
        if status == DeliveryStatus.SUCCEEDED:
            results["succeeded"] += 1
        elif status == DeliveryStatus.DEAD_LETTER:
            results["dead_letter"] += 1
        else:
            results["queued"] += 1

    return results
