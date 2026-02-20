"""Loop event history and undo endpoints.

Purpose:
    HTTP endpoints for loop event history and undo operations.

Responsibilities:
    - Retrieve paginated event history for a loop
    - Undo reversible events (update, status_change, close)
    - Provide SSE stream for real-time loop events
    - Support cursor-based replay for event stream reconnection
    - Send periodic heartbeats to keep SSE connections alive

Non-scope:
    - Does not allow undo of enrichment, claim, or timer events
    - Does not modify or delete historical events
    - Does not provide webhook-based event delivery

Endpoints:
- GET /{loop_id}/events: Get event history for a loop
- POST /{loop_id}/undo: Undo the most recent reversible event
- GET /events/stream: SSE stream of loop events
"""

import json
import sqlite3
import time
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from ... import db
from ...idempotency import (
    IdempotencyConflictError,
    build_http_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ...loops import service as loop_service
from ...loops.errors import ClaimNotFoundError, LoopClaimedError, UndoNotPossibleError
from ...schemas.loops import (
    LoopEventListResponse,
    LoopEventResponse,
    LoopResponse,
    LoopUndoResponse,
)
from ...sse import format_sse_comment, format_sse_event
from ._common import IdempotencyKeyHeader, SettingsDep, _idempotency_conflict

router = APIRouter()


@router.get("/{loop_id}/events", response_model=LoopEventListResponse)
def loop_events_endpoint(
    loop_id: int,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before_id: Annotated[int | None, Query(description="Pagination cursor")] = None,
) -> LoopEventListResponse:
    """Get event history for a loop.

    Returns events in reverse chronological order (newest first).
    Use before_id cursor for pagination.
    """
    from ...loops.errors import LoopNotFoundError

    with db.core_connection(settings) as conn:
        try:
            events = loop_service.get_loop_events(
                loop_id=loop_id,
                limit=limit + 1,  # Fetch one extra to detect has_more
                before_id=before_id,
                conn=conn,
            )
        except LoopNotFoundError:
            raise HTTPException(status_code=404, detail="Loop not found") from None

    has_more = len(events) > limit
    if has_more:
        events = events[:limit]

    return LoopEventListResponse(
        loop_id=loop_id,
        events=[LoopEventResponse(**e) for e in events],
        has_more=has_more,
        next_cursor=events[-1]["id"] if has_more else None,
    )


@router.post("/{loop_id}/undo", response_model=LoopUndoResponse)
def loop_undo_endpoint(
    loop_id: int,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopUndoResponse | JSONResponse:
    """Undo the most recent reversible event for a loop.

    Reversible events include: update, status_change, close.
    Enrichment, claim, and timer events cannot be undone.

    Returns the updated loop and details of the undone event.
    """
    from ...loops.errors import LoopNotFoundError

    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/undo")
        payload = {"loop_id": loop_id}
        request_hash = canonical_request_hash(payload)
        expires_at = expiry_timestamp(settings.idempotency_ttl_seconds)

        with db.core_connection(settings) as conn:
            try:
                claim = db.claim_or_replay_idempotency(
                    scope=scope,
                    idempotency_key=key,
                    request_hash=request_hash,
                    expires_at=expires_at,
                    conn=conn,
                )
            except IdempotencyConflictError as e:
                raise _idempotency_conflict(str(e)) from None

            if not claim["is_new"] and claim["replay"]:
                replay = claim["replay"]
                return JSONResponse(
                    content=replay["response_body"],
                    status_code=replay["status_code"],
                )

            try:
                result = loop_service.undo_last_event(
                    loop_id=loop_id,
                    conn=conn,
                )
            except UndoNotPossibleError as e:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "undo_not_possible",
                        "reason": e.reason,
                        "message": e.message,
                    },
                ) from None
            except LoopNotFoundError:
                raise HTTPException(status_code=404, detail="Loop not found") from None
            except LoopClaimedError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "loop_claimed",
                        "message": str(e),
                        "owner": e.owner,
                        "lease_until": e.lease_until,
                    },
                ) from None
            except ClaimNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "invalid_claim_token",
                        "message": "Invalid or expired claim token",
                    },
                ) from None

            response = LoopUndoResponse(
                loop=LoopResponse(**result["loop"]),
                undone_event_id=result["undone_event_id"],
                undone_event_type=result["undone_event_type"],
            ).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            try:
                result = loop_service.undo_last_event(
                    loop_id=loop_id,
                    conn=conn,
                )
            except UndoNotPossibleError as e:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "undo_not_possible",
                        "reason": e.reason,
                        "message": e.message,
                    },
                ) from None
            except LoopNotFoundError:
                raise HTTPException(status_code=404, detail="Loop not found") from None
            except LoopClaimedError as e:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "loop_claimed",
                        "message": str(e),
                        "owner": e.owner,
                        "lease_until": e.lease_until,
                    },
                ) from None
            except ClaimNotFoundError:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "invalid_claim_token",
                        "message": "Invalid or expired claim token",
                    },
                ) from None
        response = LoopUndoResponse(
            loop=LoopResponse(**result["loop"]),
            undone_event_id=result["undone_event_id"],
            undone_event_type=result["undone_event_type"],
        ).model_dump()

    return LoopUndoResponse(**response)


@router.get("/events/stream")
def loop_events_stream(
    settings: SettingsDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    cursor: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """SSE stream of loop events with cursor replay support.

    Clients can reconnect using Last-Event-ID header to resume from
    where they left off. Events are delivered in order with monotonic IDs.

    Heartbeat comments are sent every 30 seconds to keep connection alive.
    """
    heartbeat_interval = settings.webhook_heartbeat_interval
    # For testing: if heartbeat is very short, also limit stream duration
    max_iterations = 100 if heartbeat_interval < 1 else None

    def event_generator() -> Iterator[str]:
        conn = None
        iterations = 0
        try:
            # Open database connection (check_same_thread=False for SSE generator thread safety)
            conn = sqlite3.connect(settings.core_db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            for pragma, value in db.PRAGMAS:
                conn.execute(f"PRAGMA {pragma}={value}")

            # Determine starting point for replay
            start_id = 0
            if last_event_id is not None:
                try:
                    start_id = int(last_event_id)
                except ValueError:
                    pass
            elif cursor is not None:
                try:
                    start_id = int(cursor)
                except ValueError:
                    pass

            # Send historical events first (for replay)
            if start_id > 0:
                rows = conn.execute(
                    """
                    SELECT id, loop_id, event_type, payload_json, created_at
                    FROM loop_events
                    WHERE id > ?
                    ORDER BY id ASC
                    """,
                    (start_id,),
                ).fetchall()
                for row in rows:
                    payload = json.loads(row["payload_json"])
                    event_data = {
                        "event_id": row["id"],
                        "event_type": row["event_type"],
                        "loop_id": row["loop_id"],
                        "payload": payload,
                        "timestamp": row["created_at"],
                    }
                    yield format_sse_event(
                        event="loop_event",
                        payload=event_data,
                        event_id=str(row["id"]),
                    )

            # Send live events via polling
            last_id = start_id
            last_heartbeat = time.monotonic()

            while True:
                iterations += 1
                if max_iterations is not None and iterations > max_iterations:
                    break

                # Send heartbeat if needed
                now = time.monotonic()
                if now - last_heartbeat >= heartbeat_interval:
                    yield format_sse_comment(f"heartbeat {now}")
                    last_heartbeat = now

                # Check for new events
                rows = conn.execute(
                    """
                    SELECT id, loop_id, event_type, payload_json, created_at
                    FROM loop_events
                    WHERE id > ?
                    ORDER BY id ASC
                    """,
                    (last_id,),
                ).fetchall()

                for row in rows:
                    payload = json.loads(row["payload_json"])
                    event_data = {
                        "event_id": row["id"],
                        "event_type": row["event_type"],
                        "loop_id": row["loop_id"],
                        "payload": payload,
                        "timestamp": row["created_at"],
                    }
                    yield format_sse_event(
                        event="loop_event",
                        payload=event_data,
                        event_id=str(row["id"]),
                    )
                    last_id = row["id"]

                # Short sleep to prevent tight loop
                time.sleep(0.5)

        finally:
            if conn is not None:
                conn.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
