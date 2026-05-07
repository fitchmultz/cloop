"""Scheduler nudge tasks delegated to the Life agent.

Purpose:
    Keep scheduler slots deterministic while giving due-soon and stale-rescue
    judgment to the Life organizer.

Responsibilities:
    - Run background Life-agent passes for due-soon and stale-rescue slots
    - Persist compact scheduler events from the agent response
    - Send a digest only when the agent explicitly requests notification

Non-scope:
    - Ranking loops, assigning escalation levels, deciding staleness, or writing
      notification copy in deterministic Python
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

_DUE_SOON_MESSAGE = (
    "Run a background Life due-soon pass. Review the full Life context and decide "
    "whether anything due, overdue, vague, blocked, emotionally heavy, or easily prepared "
    "deserves attention now. Do not use dumb reminder behavior. If a digest is worth "
    "interrupting for, set notify_user true and write the notification copy yourself. "
    "If nothing is worth interrupting for, quietly return no notification."
)

_STALE_RESCUE_MESSAGE = (
    "Run a background Life stale-rescue pass. Review the full Life context and decide "
    "which old, avoided, vague, repeatedly deferred, blocked, or no-longer-relevant loops "
    "need cleanup, preparation, grouping, or quiet reversible action under the Life "
    "authority contract. You decide what stale means from the evidence. If a digest is "
    "worth interrupting for, set notify_user true and write the notification copy yourself."
)


def _life_nudge_loop_ids(response: LifeMessageResponse) -> list[int]:
    return sorted(
        {item.loop.id for group in response.groups for item in group.items}
        | {item.loop.id for item in response.captured}
        | {item.loop.id for item in response.updated}
    )


def _life_nudge_payload(*, response: LifeMessageResponse, nudge_type: str) -> dict[str, Any]:
    cleanup = response.cleanup
    loop_ids = _life_nudge_loop_ids(response)
    return {
        "nudge_type": nudge_type,
        "mode": response.mode,
        "reply": response.reply,
        "notify_user": response.notify_user,
        "notification_title": response.notification_title,
        "notification_body": response.notification_body,
        "loop_ids": loop_ids,
        "details": [
            {
                "id": item.loop.id,
                "title": item.loop.title,
                "life_state": item.life_state,
                "rationale": item.rationale,
            }
            for group in response.groups
            for item in group.items
        ],
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
        "generated_at_utc": format_utc_datetime(utc_now()),
    }


async def _run_life_nudge_pass(
    *,
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None,
    task_name: str,
    event_type: LoopEventType,
    push_kind: str,
    message: str,
    send_push_fn: SchedulerPushSender,
) -> dict[str, Any]:
    resolved = resolved_context(context, task_name=task_name, settings=settings)
    resolved.assert_active()
    response = handle_life_message(
        message=message,
        settings=settings,
        conn=conn,
        interaction_source="background",
    )
    payload = _life_nudge_payload(response=response, nudge_type=push_kind.removeprefix("nudge_"))
    event_id = emit_scheduler_event(event_type, payload, context=resolved, conn=conn)
    push_count = 0
    if payload.get("notify_user") is True:
        try:
            push_count = send_scheduler_push_once(
                push_kind=push_kind,
                payload=payload,
                context=resolved,
                conn=conn,
                send_push_fn=send_push_fn,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Life nudge push notification failed: %s", exc)
    return {"event_id": event_id, "push_count": push_count, **payload}


async def run_due_soon_nudge(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
    *,
    send_push_fn: SchedulerPushSender = send_scheduler_push,
) -> dict[str, Any]:
    """Run one due-soon nudge slot through the Life agent."""
    result = await _run_life_nudge_pass(
        settings=settings,
        conn=conn,
        context=context,
        task_name="due_soon_nudge",
        event_type=LoopEventType.NUDGE_DUE_SOON,
        push_kind="nudge_due_soon",
        message=_DUE_SOON_MESSAGE,
        send_push_fn=send_push_fn,
    )
    return {
        "nudged": len(result["loop_ids"]),
        "escalation_summary": {},
        "bucket_summary": {},
        **result,
    }


async def run_stale_rescue(
    settings: Settings,
    conn: sqlite3.Connection,
    context: SchedulerRunContext | None = None,
    *,
    send_push_fn: SchedulerPushSender = send_scheduler_push,
) -> dict[str, Any]:
    """Run one stale-rescue slot through the Life agent."""
    result = await _run_life_nudge_pass(
        settings=settings,
        conn=conn,
        context=context,
        task_name="stale_rescue",
        event_type=LoopEventType.NUDGE_STALE,
        push_kind="nudge_stale",
        message=_STALE_RESCUE_MESSAGE,
        send_push_fn=send_push_fn,
    )
    return {"rescued": len(result["loop_ids"]), **result}
