"""Webhook service for delivery and retry management.

Purpose:
    Manage webhook delivery with retry logic and circuit breaking.

Responsibilities:
    - Queue webhook deliveries
    - Retry failed deliveries with backoff
    - Sign webhook payloads

Non-scope:
    - HTTP endpoint handling (see routes/)
    - Database operations (see webhooks/repo.py)
"""

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
from typing import Any
from urllib.parse import urlparse

from ..settings import Settings, get_settings
from . import repo
from .models import DeliveryStatus
from .signer import sign_bytes

logger = logging.getLogger(__name__)


def _is_safe_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    if ip == ipaddress.ip_address("169.254.169.254"):
        return False
    return True


def _resolve_safe_delivery_targets(
    url: str,
) -> tuple[tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...], str, int, str]:
    """Resolve and validate all delivery targets for an outbound webhook."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("URL must use https and include a host")

    hostname = parsed.hostname
    if not hostname or hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Unsafe or missing hostname")

    port = parsed.port or 443
    infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    resolved_ips = []
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
    unique_ips = tuple(dict.fromkeys(resolved_ips))
    return unique_ips, hostname, port, path


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that dials a validated IP while verifying the hostname."""

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
        self._connect_ip = connect_ip
        self._ssl_context = ssl_context

    def connect(self) -> None:
        sock = socket.create_connection((self._connect_ip, self.port), self.timeout)
        self.sock = self._ssl_context.wrap_socket(sock, server_hostname=self.host)


def _send_pinned_webhook_request(
    *,
    url: str,
    payload_bytes: bytes,
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, str]:
    """Send a webhook request over a pinned, prevalidated HTTPS connection."""
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
            return response.status, response_body
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        finally:
            connection.close()

    if last_error is not None:
        raise last_error
    raise RuntimeError("Webhook delivery failed before attempting a connection")


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize a webhook payload deterministically."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _build_delivery_payload(
    *,
    delivery: Any,
    delivered_at: str,
    attempt_number: int,
) -> dict[str, Any]:
    """Build the canonical outbound webhook envelope."""
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
    """Calculate exponential backoff delay with jitter.

    Args:
        attempt_count: Number of delivery attempts made so far
        settings: Application settings containing retry configuration

    Returns:
        Delay in seconds before next retry
    """
    base = settings.webhook_retry_base_delay
    max_delay = settings.webhook_retry_max_delay

    # Exponential backoff: 2^attempt * base
    delay = base * (2**attempt_count)

    # Add jitter (±25% randomization) to prevent thundering herd
    jitter = delay * 0.25 * (2 * random.random() - 1)
    delay = delay + jitter

    # Cap at maximum delay
    return min(delay, max_delay)


def _should_deliver_event(event_type: str, subscription_event_types: list[str]) -> bool:
    """Check if an event should be delivered to a subscription.

    Args:
        event_type: The event type to check
        subscription_event_types: List of event types the subscription accepts

    Returns:
        True if the event should be delivered
    """
    if "*" in subscription_event_types:
        return True
    return event_type in subscription_event_types


def queue_deliveries(
    *,
    event_id: int,
    event_type: str,
    payload: dict[str, Any],
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> list[int]:
    """Queue webhook deliveries for a loop event.

    This is called synchronously during loop mutations to queue
    deliveries. The actual HTTP delivery happens asynchronously
    via background tasks.

    Args:
        event_id: The loop_events.id
        event_type: Type of event (e.g., 'capture', 'update')
        payload: Event payload dictionary
        conn: Database connection
        settings: Optional settings override

    Returns:
        List of created delivery IDs
    """
    settings = settings or get_settings()
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


def deliver_webhook(
    *,
    delivery_id: int,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
) -> DeliveryStatus:
    """Attempt to deliver a queued webhook.

    Args:
        delivery_id: The webhook delivery ID
        conn: Database connection
        settings: Optional settings override

    Returns:
        Final delivery status
    """
    settings = settings or get_settings()

    delivery = repo.get_delivery(delivery_id=delivery_id, conn=conn)
    if delivery is None:
        logger.error("Delivery %s not found", delivery_id)
        return DeliveryStatus.FAILED

    if delivery.status == DeliveryStatus.SUCCESS:
        return DeliveryStatus.SUCCESS

    if delivery.status == DeliveryStatus.DEAD_LETTER:
        return DeliveryStatus.DEAD_LETTER

    subscription = repo.get_subscription(
        subscription_id=delivery.subscription_id,
        conn=conn,
    )
    if subscription is None:
        logger.error(
            "Subscription %s not found for delivery %s", delivery.subscription_id, delivery_id
        )
        repo.update_delivery_status(
            delivery_id=delivery_id,
            status=DeliveryStatus.FAILED,
            error_message="Subscription not found",
            conn=conn,
        )
        return DeliveryStatus.FAILED

    try:
        _resolve_safe_delivery_targets(subscription.url)
    except ValueError as exc:
        logger.error("Unsafe URL for subscription %s: %s", subscription.id, subscription.url)
        repo.update_delivery_status(
            delivery_id=delivery_id,
            status=DeliveryStatus.FAILED,
            error_message=str(exc),
            conn=conn,
        )
        return DeliveryStatus.FAILED

    delivered_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    attempt_number = delivery.attempt_count + 1
    payload = _build_delivery_payload(
        delivery=delivery,
        delivered_at=delivered_at,
        attempt_number=attempt_number,
    )
    payload_bytes = _canonical_json_bytes(payload)
    timestamp = str(int(time.time()))
    signature_header = sign_bytes(payload_bytes, subscription.secret, timestamp)

    # Attempt delivery
    try:
        http_status, response_body = _send_pinned_webhook_request(
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

        # 2xx status codes are considered success
        if 200 <= http_status < 300:
            repo.update_delivery_status(
                delivery_id=delivery_id,
                status=DeliveryStatus.SUCCESS,
                signature_header=signature_header,
                attempt_payload_json=payload_bytes.decode("utf-8"),
                last_attempted_at=delivered_at,
                http_status=http_status,
                response_body=response_body,
                conn=conn,
            )
            logger.debug("Webhook delivery %s succeeded: HTTP %s", delivery_id, http_status)
            return DeliveryStatus.SUCCESS
        else:
            # Non-2xx is a failure that may be retried
            raise RuntimeError(f"HTTP {http_status}: Non-2xx response")

    except Exception as exc:
        error_message = str(exc)[:500]
        attempt_count = delivery.attempt_count + 1

        # Determine if we should retry or give up
        if attempt_count >= settings.webhook_max_retries:
            final_status = DeliveryStatus.DEAD_LETTER
            logger.warning(
                "Webhook delivery %s failed after %s attempts, moved to dead letter: %s",
                delivery_id,
                attempt_count,
                error_message,
            )
        else:
            final_status = DeliveryStatus.PENDING
            delay = _calculate_retry_delay(attempt_count, settings)
            next_retry = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
                seconds=delay
            )
            next_retry_at = next_retry.isoformat()

            repo.update_delivery_status(
                delivery_id=delivery_id,
                status=final_status,
                signature_header=signature_header,
                attempt_payload_json=payload_bytes.decode("utf-8"),
                last_attempted_at=delivered_at,
                error_message=error_message,
                next_retry_at=next_retry_at,
                conn=conn,
            )
            logger.debug(
                "Webhook delivery %s failed (attempt %s/%s), retry scheduled: %s",
                delivery_id,
                attempt_count,
                settings.webhook_max_retries,
                error_message,
            )
            return final_status

        # Final failure - update status
        repo.update_delivery_status(
            delivery_id=delivery_id,
            status=final_status,
            signature_header=signature_header,
            attempt_payload_json=payload_bytes.decode("utf-8"),
            last_attempted_at=delivered_at,
            error_message=error_message,
            conn=conn,
        )
        return final_status


def process_pending_deliveries(
    *,
    conn: sqlite3.Connection,
    settings: Settings | None = None,
    batch_size: int = 100,
) -> dict[str, int]:
    """Process all pending webhook deliveries.

    This is typically called by a background task/worker.

    Args:
        conn: Database connection
        settings: Optional settings override
        batch_size: Maximum number of deliveries to process

    Returns:
        Dict with counts of succeeded, failed, and dead_letter deliveries
    """
    settings = settings or get_settings()
    pending = repo.list_pending_deliveries(conn=conn)[:batch_size]

    results = {"succeeded": 0, "failed": 0, "dead_letter": 0}

    for delivery in pending:
        status = deliver_webhook(
            delivery_id=delivery.id,
            conn=conn,
            settings=settings,
        )

        if status == DeliveryStatus.SUCCESS:
            results["succeeded"] += 1
        elif status == DeliveryStatus.DEAD_LETTER:
            results["dead_letter"] += 1
        else:
            results["failed"] += 1

    return results
