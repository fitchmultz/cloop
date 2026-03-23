"""Push notification sending infrastructure.

Purpose:
    Send Web Push notifications to subscribed browsers.

Responsibilities:
    - Map continuity-owned delivery records to push notification payloads
    - Deliver notifications to all subscribed clients
    - Persist durable notification inbox state after successful sends
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
from datetime import UTC, datetime
from typing import Any

from .schemas._loops.continuity import (
    ContinuityLocationResponse,
    ContinuityNotificationRecordResponse,
    ContinuityNotificationStateUpsertRequest,
)
from .storage.continuity_store import (
    read_continuity_notification_records,
    read_continuity_snapshot,
    upsert_continuity_notification_state,
)

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


def _continuity_location_url(location: ContinuityLocationResponse) -> str:
    if location.state == "plan" and location.session_id is not None:
        return f"/#plan/session/{location.session_id}"
    if (
        location.state == "decide"
        and location.review_focus in {"relationship", "enrichment"}
        and location.session_id is not None
    ):
        return f"/#decide/{location.review_focus}/{location.session_id}"
    if location.state == "do" and location.loop_id is not None:
        return f"/#do/loop/{location.loop_id}"
    if location.state == "working_set" and location.working_set_id is not None:
        return f"/#working-set/{location.working_set_id}"
    if location.state == "recall":
        return f"/#recall/{location.recall_tool}"
    return "/#operator"


def _selected_continuity_notification(
    settings: Any,
    event_payload: dict[str, Any],
) -> ContinuityNotificationRecordResponse | None:
    selected_id = event_payload.get("notification_id")
    if isinstance(selected_id, str) and selected_id.strip():
        snapshot = read_continuity_snapshot(settings=settings)
        for notification in snapshot.notification_records:
            if notification.id == selected_id:
                return notification
        return None

    notifications = read_continuity_notification_records(limit=1, settings=settings, channel="push")
    return notifications[0] if notifications else None


def _continuity_push_payload(
    settings: Any,
    event_payload: dict[str, Any],
) -> tuple[str, PushPayload] | None:
    notification = _selected_continuity_notification(settings, event_payload)
    if notification is None:
        return None
    return (
        notification.id,
        PushPayload(
            title=notification.title,
            body=notification.body,
            url=_continuity_location_url(notification.resolved_location),
            data={
                "workflow_summary_id": notification.id,
                "workflow_thread_id": notification.workflow_thread.id,
            },
        ),
    )


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

    Scheduler-owned pushes now read the canonical continuity notification feed
    directly so browser delivery matches the same backend-authored notification
    record used by in-app banners and operator digests.
    """
    if event_type not in {"nudge_due_soon", "nudge_stale", "review_generated"}:
        return 0

    if event_type == "review_generated" and event_payload.get("total_items", 0) == 0:
        return 0
    if event_type in {"nudge_due_soon", "nudge_stale"} and not event_payload.get("details"):
        return 0

    continuity_notification = _continuity_push_payload(settings, event_payload)
    if continuity_notification is None:
        return 0

    notification_id, continuity_payload = continuity_notification
    continuity_payload.data = {
        **(continuity_payload.data or {}),
        "event_type": event_type,
    }
    sent = send_push_notification(continuity_payload, settings, conn)
    if sent > 0:
        upsert_continuity_notification_state(
            notification_id,
            ContinuityNotificationStateUpsertRequest(
                inboxed_at_utc=datetime.now(UTC)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
            ),
            settings=settings,
        )
    return sent
