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
import ipaddress
import json
import logging
import random
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from ..settings import Settings, get_settings
from . import repo
from .models import DeliveryStatus
from .signer import generate_signature

logger = logging.getLogger(__name__)


def _is_safe_url(url: str) -> bool:
    """Check if a URL is safe to fetch (SSRF protection).

    Args:
        url: The URL to validate

    Returns:
        True if the URL is safe to fetch
    """
    try:
        parsed = urlparse(url)

        # Must have scheme and netloc
        if not parsed.scheme or not parsed.netloc:
            return False

        # Only allow HTTPS
        if parsed.scheme != "https":
            return False

        # Extract hostname
        hostname = parsed.hostname
        if not hostname:
            return False

        # Block localhost hostname
        if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            return False

        # Check if hostname is an IP address
        try:
            ip = ipaddress.ip_address(hostname)
            # Block private IP ranges
            if ip.is_private:
                return False
            # Block loopback
            if ip.is_loopback:
                return False
            # Block link-local
            if ip.is_link_local:
                return False
            # Block AWS metadata service IP
            if ip == ipaddress.ip_address("169.254.169.254"):
                return False
        except ValueError:
            # Not an IP address, assume hostname is safe for now
            pass

        return True
    except Exception:
        return False


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

        # Generate signature with current timestamp
        timestamp = str(int(time.time()))
        signature = generate_signature(payload, subscription.secret, timestamp)

        delivery = repo.create_delivery(
            subscription_id=subscription.id,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            signature=signature,
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

    # Validate URL safety (SSRF protection)
    if not _is_safe_url(subscription.url):
        logger.error("Unsafe URL for subscription %s: %s", subscription.id, subscription.url)
        repo.update_delivery_status(
            delivery_id=delivery_id,
            status=DeliveryStatus.FAILED,
            error_message="Invalid or unsafe URL",
            conn=conn,
        )
        return DeliveryStatus.FAILED

    # Prepare payload
    payload = {
        "event_id": delivery.event_id,
        "event_type": delivery.event_type,
        "timestamp": delivery.created_at,
        "data": delivery.payload_json,
    }

    # Attempt delivery
    try:
        req = urllib.request.Request(
            subscription.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": delivery.signature,
                "X-Webhook-Event": delivery.event_type,
                "X-Webhook-Event-Id": str(delivery.event_id),
                "User-Agent": "cloop-webhook/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=settings.webhook_timeout_seconds) as response:
            http_status = response.status
            response_body = response.read().decode("utf-8", errors="replace")[:1000]

        # 2xx status codes are considered success
        if 200 <= http_status < 300:
            repo.update_delivery_status(
                delivery_id=delivery_id,
                status=DeliveryStatus.SUCCESS,
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
