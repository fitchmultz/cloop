"""Push notification sending infrastructure.

Purpose:
    Send Web Push notifications to subscribed browsers.

Responsibilities:
    - Map scheduler events to push notification payloads
    - Deliver notifications to all subscribed clients
    - Handle push failures and remove invalid subscriptions

Non-scope:
    - Subscription management (see routes/loops/push.py)
    - Service worker handling (client-side)
    - VAPID key generation

Uses pywebpush library for VAPID-based push delivery.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Optional: VAPID configuration for authenticated push
# Generate keys with: npx web-push generate-vapid-keys
VAPID_PRIVATE_KEY = None  # Set via environment if needed
VAPID_SUBJECT = "mailto:admin@example.com"


@dataclass
class PushPayload:
    """Structured push notification payload."""

    title: str
    body: str
    icon: str = "/static/icons/icon-192.png"
    badge: str = "/static/icons/icon-192.png"
    url: str = "/"
    data: dict[str, Any] | None = None


def send_push_notification(
    payload: PushPayload,
    settings: Any,
    conn: sqlite3.Connection,
) -> int:
    """Send push notification to all subscribed clients.

    Returns count of successful sends.
    """
    # Try to import webpush (optional dependency)
    try:
        from pywebpush import WebPushException, webpush  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("pywebpush not installed, skipping push notifications")
        return 0

    subscriptions = conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions").fetchall()

    if not subscriptions:
        return 0

    message = {
        "title": payload.title,
        "body": payload.body,
        "icon": payload.icon,
        "badge": payload.badge,
        "url": payload.url,
        "data": payload.data or {},
    }

    success_count = 0
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {
                        "p256dh": sub["p256dh"],
                        "auth": sub["auth"],
                    },
                },
                data=json.dumps(message),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_SUBJECT} if VAPID_PRIVATE_KEY else None,
            )
            success_count += 1
        except WebPushException as e:
            logger.warning(f"Push failed for {sub['endpoint'][:50]}...: {e}")
            # Remove invalid subscription
            if e.response and e.response.status_code in (404, 410):
                conn.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint = ?",
                    (sub["endpoint"],),
                )
                conn.commit()
        except (ValueError, TypeError, ConnectionError, TimeoutError) as e:
            logger.error(f"Push delivery error: {e}")

    return success_count


def send_scheduler_push(
    event_type: str,
    event_payload: dict[str, Any],
    settings: Any,
    conn: sqlite3.Connection,
) -> int:
    """Send push notification for a scheduler event.

    Maps scheduler event types to appropriate push payloads.
    """
    if event_type == "nudge_due_soon":
        details = event_payload.get("details", [])
        urgent = sum(1 for d in details if d.get("escalation_level", 0) >= 2)
        overdue = sum(1 for d in details if d.get("is_overdue"))

        if overdue > 0:
            title = f"{overdue} overdue loops"
            body = "You have overdue items that need attention"
        elif urgent > 0:
            title = f"{urgent} urgent loops"
            body = "Some loops require immediate attention"
        else:
            title = f"{len(details)} loops due soon"
            body = "Plan ahead for upcoming deadlines"

        return send_push_notification(
            PushPayload(
                title=title,
                body=body,
                url="/?tab=review",
                data={"event_type": event_type, "count": len(details)},
            ),
            settings,
            conn,
        )

    elif event_type == "nudge_stale":
        details = event_payload.get("details", [])
        return send_push_notification(
            PushPayload(
                title=f"{len(details)} stale loops",
                body="Some loops haven't been updated recently",
                url="/?tab=review",
                data={"event_type": event_type, "count": len(details)},
            ),
            settings,
            conn,
        )

    elif event_type == "review_generated":
        review_type = event_payload.get("review_type", "daily")
        total = event_payload.get("total_items", 0)

        if total == 0:
            return 0

        return send_push_notification(
            PushPayload(
                title=f"{review_type.title()} review ready",
                body=f"{total} items to review",
                url="/?tab=review",
                data={"event_type": event_type, "review_type": review_type},
            ),
            settings,
            conn,
        )

    return 0
