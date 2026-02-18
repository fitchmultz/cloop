"""Web push notification service.

Purpose:
    Send push notifications to subscribed clients via Web Push protocol.

Responsibilities:
    - Build push payloads for scheduler events
    - Send push messages to all active subscriptions
    - Handle push failures and deactivate invalid subscriptions

Non-scope:
    - Subscription storage (see repo.py)
    - HTTP endpoint handling (see routes/push.py)
"""

import json
import logging
import sqlite3
from typing import Any, Callable

from ..settings import Settings
from . import repo

logger = logging.getLogger(__name__)

# Allow tests to inject a fake webpush function
_webpush_fn: Callable | None = None


def set_webpush_fn(fn: Callable | None) -> None:
    """Set a custom webpush function for testing.

    Args:
        fn: Custom function or None to use real pywebpush
    """
    global _webpush_fn
    _webpush_fn = fn


def push_enabled(settings: Settings) -> bool:
    """Check if web push is configured.

    Args:
        settings: Application settings

    Returns:
        True if both VAPID keys are configured
    """
    return bool(settings.push_vapid_public_key and settings.push_vapid_private_key)


def build_push_payload_for_scheduler_event(
    *, event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Build push notification payload for scheduler events.

    The payload shape must match what sw.js expects: {title, body, url}

    Args:
        event_type: Scheduler event type (nudge_due_soon, nudge_stale, review_generated)
        payload: Event payload from scheduler

    Returns:
        Dict with title, body, and url for push notification
    """
    if event_type == "nudge_due_soon":
        count = len(payload.get("loop_ids") or [])
        first = (payload.get("details") or [{}])[0].get("title") or "A loop"
        return {
            "title": f"Due soon: {count} loop{'s' if count != 1 else ''}",
            "body": first if count <= 1 else f"First: {first}",
            "url": "/#review",
        }

    if event_type == "nudge_stale":
        count = len(payload.get("loop_ids") or [])
        first = (payload.get("details") or [{}])[0].get("title") or "A loop"
        return {
            "title": f"Stale rescue: {count} loop{'s' if count != 1 else ''}",
            "body": first if count <= 1 else f"Oldest: {first}",
            "url": "/#review",
        }

    if event_type == "review_generated":
        review_type = payload.get("review_type") or "daily"
        total = payload.get("total_items", 0)
        return {
            "title": f"{review_type.title()} review generated",
            "body": f"Items: {total}",
            "url": "/#review",
        }

    return {"title": "Cloop reminder", "body": "You have an update", "url": "/"}


def _send_webpush(
    *, subscription_row: sqlite3.Row, message: dict[str, Any], settings: Settings
) -> None:
    """Send a push notification to a single subscription.

    Args:
        subscription_row: Database row with subscription details
        message: Payload dict (will be JSON-encoded)
        settings: Application settings with VAPID keys
    """
    if _webpush_fn is not None:
        _webpush_fn(
            subscription_info={
                "endpoint": subscription_row["endpoint"],
                "keys": {
                    "p256dh": subscription_row["p256dh"],
                    "auth": subscription_row["auth"],
                },
            },
            data=json.dumps(message),
            vapid_private_key=settings.push_vapid_private_key,
            vapid_claims={"sub": settings.push_vapid_subject},
        )
    else:
        from pywebpush import webpush

        webpush(
            subscription_info={
                "endpoint": subscription_row["endpoint"],
                "keys": {
                    "p256dh": subscription_row["p256dh"],
                    "auth": subscription_row["auth"],
                },
            },
            data=json.dumps(message),
            vapid_private_key=settings.push_vapid_private_key,
            vapid_claims={"sub": settings.push_vapid_subject},
        )


def send_to_all(*, message: dict[str, Any], conn: sqlite3.Connection, settings: Settings) -> int:
    """Send push notification to all active subscriptions.

    Args:
        message: Payload dict
        conn: SQLite connection to core database
        settings: Application settings

    Returns:
        Number of successful sends
    """
    if not push_enabled(settings):
        return 0

    sent = 0
    for sub in repo.list_active(conn=conn):
        try:
            _send_webpush(subscription_row=sub, message=message, settings=settings)
            sent += 1
        except Exception as e:
            # Check for permanent failure (404 Gone, 410 Not Found)
            status = getattr(e, "response", None)
            code = getattr(status, "status_code", None)
            if code in (404, 410):
                repo.deactivate_endpoint(endpoint=sub["endpoint"], conn=conn)
            logger.warning(
                "push send failed endpoint=%s err=%s",
                sub["endpoint"][:50],
                str(e)[:200],
            )
    return sent
