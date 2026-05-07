"""Scheduler Life-agent task implementation.

Purpose:
    Run a background Life organizer pass from the dedicated scheduler.

Responsibilities:
    - Delegate background cleanup and memory-gardening judgment to the Life agent
    - Persist one scheduler-owned summary event for the completed pass
    - Return a compact scheduler result without exposing Life internals

Scope:
    - Scheduler task wrapper around `life_orchestration.handle_life_message`

Non-scope:
    - Slot claiming or runtime orchestration
    - Deterministic stale, due-soon, or notification candidate selection
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from ..life_orchestration import handle_life_message
from ..loops.models import LoopEventType, format_utc_datetime, utc_now
from ..push_sender import send_scheduler_push
from ..schemas.life import LifeMessageResponse
from ..settings import Settings
from .cadence import resolved_context
from .models import SchedulerPushSender, SchedulerRunContext
from .side_effects import emit_scheduler_event, send_scheduler_push_once

logger = logging.getLogger(__name__)

_LIFE_GARDEN_MESSAGE = (
    "Run a background Life garden pass. Review open loops, recent history, and durable "
    "memory. Use your judgment under the Life authority contract: apply only low-risk or "
    "clearly delegated internal cleanup, preserve anything uncertain for review, group what "
    "needs the user's call, and decide whether a user-visible digest is worth interrupting "
    "for. Do not create new user tasks unless needed to repair a duplicate or missing "
    "context link you can explain from the evidence."
)


def _life_garden_payload(response: LifeMessageResponse) -> dict[str, Any]:
    cleanup = response.cleanup
    return {
        "mode": response.mode,
        "reply": response.reply,
        "notify_user": response.notify_user,
        "notification_title": response.notification_title,
        "notification_body": response.notification_body,
        "captured_count": len(response.captured),
        "updated_count": len(response.updated),
        "memory_count": len(response.memories),
        "memory_ids": [memory.id for memory in response.memories],
        "group_counts": {group.name: len(group.items) for group in response.groups},
        "cleanup": None
        if cleanup is None
        else {
            "open_count": cleanup.open_count,
            "recommendation": cleanup.recommendation,
            "close_candidate_count": len(cleanup.close_candidates),
            "archive_candidate_count": len(cleanup.archive_candidates),
            "keep_active_count": len(cleanup.keep_active),
            "review_needed_count": len(cleanup.review_needed),
            "applied_automatic_cleanup_count": len(cleanup.applied_automatic_cleanup),
            "undo_count": len(cleanup.undo),
        },
        "loop_ids": sorted(
            {item.loop.id for group in response.groups for item in group.items}
            | {item.loop.id for item in response.captured}
            | {item.loop.id for item in response.updated}
        ),
        "generated_at_utc": format_utc_datetime(utc_now()),
    }


def _agent_requested_life_garden_digest(payload: dict[str, Any]) -> bool:
    return payload.get("notify_user") is True


async def run_life_garden(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
    *,
    send_push_fn: SchedulerPushSender = send_scheduler_push,
) -> dict[str, Any]:
    """Run one background Life organizer cleanup and memory-gardening pass."""
    resolved = resolved_context(context, task_name="life_garden", settings=settings)
    resolved.assert_active()
    response = handle_life_message(
        message=_LIFE_GARDEN_MESSAGE,
        settings=settings,
        conn=conn,
        interaction_source="background",
    )
    payload = _life_garden_payload(response)
    event_id = emit_scheduler_event(
        LoopEventType.LIFE_GARDENED,
        payload,
        context=resolved,
        conn=conn,
    )
    push_count = 0
    if _agent_requested_life_garden_digest(payload):
        try:
            push_count = send_scheduler_push_once(
                push_kind="life_garden",
                payload=payload,
                context=resolved,
                conn=conn,
                send_push_fn=send_push_fn,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Life garden push notification failed: %s", type(exc).__name__)
    return {"event_id": event_id, "push_count": push_count, **payload}
