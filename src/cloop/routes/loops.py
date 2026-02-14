"""Loop/task management endpoints.

Endpoints:
- POST /loops/capture: Create new loop
- GET /loops: List loops (filtered by status/tag)
- GET /loops/tags: List all tags
- GET /loops/export: Export all loops
- POST /loops/import: Import loops
- GET /loops/{id}: Get single loop
- PATCH /loops/{id}: Update loop fields
- POST /loops/{id}/close: Close loop (completed/dropped)
- POST /loops/{id}/status: Transition status
- POST /loops/{id}/enrich: Request AI enrichment
- GET /loops/next: Prioritized "Next Actions"
- GET /loops/events/stream: SSE stream of loop events
- POST /loops/webhooks/subscriptions: Create webhook subscription
- GET /loops/webhooks/subscriptions: List webhook subscriptions
- PATCH /loops/webhooks/subscriptions/{id}: Update webhook subscription
- DELETE /loops/webhooks/subscriptions/{id}: Delete webhook subscription

Idempotency:
All mutating endpoints support the Idempotency-Key header for safe retries.
Same key + same payload replays prior response without additional writes.
Same key + different payload returns 409 Conflict.
"""

import json
import secrets
import sqlite3
import time
from collections.abc import Iterator
from typing import Annotated, Any, List, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.responses import JSONResponse

from .. import db
from ..constants import DEFAULT_LOOP_LIST_LIMIT, DEFAULT_LOOP_NEXT_LIMIT
from ..idempotency import (
    IdempotencyConflictError,
    build_http_scope,
    canonical_request_hash,
    expiry_timestamp,
    normalize_idempotency_key,
)
from ..loops import enrichment as loop_enrichment
from ..loops import service as loop_service
from ..loops.models import LoopStatus, is_terminal_status, resolve_status_from_flags
from ..schemas.loops import (
    LoopCaptureRequest,
    LoopCloseRequest,
    LoopExportItem,
    LoopExportResponse,
    LoopImportRequest,
    LoopImportResponse,
    LoopNextResponse,
    LoopResponse,
    LoopSearchRequest,
    LoopSearchResponse,
    LoopStatusRequest,
    LoopUpdateRequest,
    LoopViewApplyResponse,
    LoopViewCreateRequest,
    LoopViewResponse,
    LoopViewUpdateRequest,
    WebhookDeliveryResponse,
    WebhookSubscriptionCreate,
    WebhookSubscriptionCreateResponse,
    WebhookSubscriptionResponse,
    WebhookSubscriptionUpdate,
)
from ..settings import Settings, get_settings
from ..sse import format_sse_comment, format_sse_event
from ..webhooks import repo as webhooks_repo

router = APIRouter(prefix="/loops", tags=["loops"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]
IdempotencyKeyHeader = Header(default=None, alias="Idempotency-Key")


def _idempotency_conflict(detail: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"message": "idempotency_key_conflict", "detail": detail},
    )


@router.post("/capture", response_model=LoopResponse)
def loop_capture_endpoint(
    request: LoopCaptureRequest,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    status = resolve_status_from_flags(
        scheduled=request.scheduled,
        blocked=request.blocked,
        actionable=request.actionable,
    )

    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", "/loops/capture")
        payload = request.model_dump()
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

            record = loop_service.capture_loop(
                raw_text=request.raw_text,
                captured_at_iso=request.captured_at,
                client_tz_offset_min=request.client_tz_offset_min,
                status=status,
                conn=conn,
            )
            if settings.autopilot_enabled:
                record = loop_service.request_enrichment(loop_id=record["id"], conn=conn)

            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            record = loop_service.capture_loop(
                raw_text=request.raw_text,
                captured_at_iso=request.captured_at,
                client_tz_offset_min=request.client_tz_offset_min,
                status=status,
                conn=conn,
            )
            if settings.autopilot_enabled:
                record = loop_service.request_enrichment(loop_id=record["id"], conn=conn)
        response = LoopResponse(**record).model_dump()

    if settings.autopilot_enabled:
        background_tasks.add_task(
            loop_enrichment.enrich_loop,
            loop_id=record["id"],
            settings=settings,
        )
    return LoopResponse(**response)


@router.get("", response_model=List[LoopResponse])
def loop_list_endpoint(
    settings: SettingsDep,
    status: Annotated[
        LoopStatus | Literal["all", "open"] | None,
        Query(description="Filter by loop status, 'open', or 'all'"),
    ] = "open",
    tag: Annotated[str | None, Query(description="Filter by tag")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_LOOP_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> List[LoopResponse]:
    tag_value = tag.strip().lower() if tag else None
    with db.core_connection(settings) as conn:
        if status == "open":
            statuses = [
                LoopStatus.INBOX,
                LoopStatus.ACTIONABLE,
                LoopStatus.BLOCKED,
                LoopStatus.SCHEDULED,
            ]
            if tag_value:
                loops = loop_service.list_loops_by_tag(
                    tag=tag_value,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
            else:
                loops = loop_service.list_loops_by_statuses(
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
        else:
            resolved_status = None if status is None or status == "all" else status
            if tag_value:
                statuses = [resolved_status] if resolved_status else None
                loops = loop_service.list_loops_by_tag(
                    tag=tag_value,
                    statuses=statuses,
                    limit=limit,
                    offset=offset,
                    conn=conn,
                )
            else:
                loops = loop_service.list_loops(
                    status=resolved_status, limit=limit, offset=offset, conn=conn
                )
    return [LoopResponse(**loop_item) for loop_item in loops]


@router.get("/tags", response_model=List[str])
def loop_tags_endpoint(settings: SettingsDep) -> List[str]:
    with db.core_connection(settings) as conn:
        return loop_service.list_tags(conn=conn)


@router.get("/export", response_model=LoopExportResponse)
def loop_export_endpoint(settings: SettingsDep) -> LoopExportResponse:
    with db.core_connection(settings) as conn:
        loops_data: list[dict[str, Any]] = loop_service.export_loops(conn=conn)
    export_items = [LoopExportItem(**loop_item) for loop_item in loops_data]
    return LoopExportResponse(version=1, loops=export_items)


@router.post("/import", response_model=LoopImportResponse)
def loop_import_endpoint(
    request: LoopImportRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopImportResponse | JSONResponse:
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", "/loops/import")
        payload = {"loops": [loop.model_dump() for loop in request.loops]}
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

            imported = loop_service.import_loops(loops=request.loops, conn=conn)
            response = LoopImportResponse(imported=imported).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
            return LoopImportResponse(**response)

    with db.core_connection(settings) as conn:
        imported = loop_service.import_loops(loops=request.loops, conn=conn)
    return LoopImportResponse(imported=imported)


@router.get("/next", response_model=LoopNextResponse)
def loop_next_endpoint(
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=20)] = DEFAULT_LOOP_NEXT_LIMIT,
) -> LoopNextResponse:
    with db.core_connection(settings) as conn:
        result: dict[str, list[dict[str, Any]]] = loop_service.next_loops(limit=limit, conn=conn)
    return LoopNextResponse(
        due_soon=[LoopResponse(**item) for item in result["due_soon"]],
        quick_wins=[LoopResponse(**item) for item in result["quick_wins"]],
        high_leverage=[LoopResponse(**item) for item in result["high_leverage"]],
    )


@router.post("/search", response_model=LoopSearchResponse)
def loop_search_endpoint(
    request: LoopSearchRequest,
    settings: SettingsDep,
) -> LoopSearchResponse:
    """Search loops using the DSL query language.

    This is the canonical query endpoint used by API, CLI, MCP, and UI.
    """
    with db.core_connection(settings) as conn:
        items = loop_service.search_loops_by_query(
            query=request.query,
            limit=request.limit,
            offset=request.offset,
            conn=conn,
        )
    return LoopSearchResponse(
        query=request.query,
        limit=request.limit,
        offset=request.offset,
        items=[LoopResponse(**item) for item in items],
    )


@router.post("/views", response_model=LoopViewResponse)
def loop_view_create_endpoint(
    request: LoopViewCreateRequest,
    settings: SettingsDep,
) -> LoopViewResponse:
    """Create a new saved view."""
    with db.core_connection(settings) as conn:
        view = loop_service.create_loop_view(
            name=request.name,
            query=request.query,
            description=request.description,
            conn=conn,
        )
    return LoopViewResponse(
        id=view["id"],
        name=view["name"],
        query=view["query"],
        description=view.get("description"),
        created_at_utc=view["created_at"],
        updated_at_utc=view["updated_at"],
    )


@router.get("/views", response_model=List[LoopViewResponse])
def loop_view_list_endpoint(settings: SettingsDep) -> List[LoopViewResponse]:
    """List all saved views."""
    with db.core_connection(settings) as conn:
        views = loop_service.list_loop_views(conn=conn)
    return [
        LoopViewResponse(
            id=v["id"],
            name=v["name"],
            query=v["query"],
            description=v.get("description"),
            created_at_utc=v["created_at"],
            updated_at_utc=v["updated_at"],
        )
        for v in views
    ]


@router.get("/views/{view_id}", response_model=LoopViewResponse)
def loop_view_get_endpoint(
    view_id: int,
    settings: SettingsDep,
) -> LoopViewResponse:
    """Get a saved view by ID."""
    with db.core_connection(settings) as conn:
        view = loop_service.get_loop_view(view_id=view_id, conn=conn)
    return LoopViewResponse(
        id=view["id"],
        name=view["name"],
        query=view["query"],
        description=view.get("description"),
        created_at_utc=view["created_at"],
        updated_at_utc=view["updated_at"],
    )


@router.patch("/views/{view_id}", response_model=LoopViewResponse)
def loop_view_update_endpoint(
    view_id: int,
    request: LoopViewUpdateRequest,
    settings: SettingsDep,
) -> LoopViewResponse:
    """Update a saved view."""
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    with db.core_connection(settings) as conn:
        view = loop_service.update_loop_view(
            view_id=view_id,
            name=fields.get("name"),
            query=fields.get("query"),
            description=fields.get("description"),
            conn=conn,
        )
    return LoopViewResponse(
        id=view["id"],
        name=view["name"],
        query=view["query"],
        description=view.get("description"),
        created_at_utc=view["created_at"],
        updated_at_utc=view["updated_at"],
    )


@router.delete("/views/{view_id}")
def loop_view_delete_endpoint(
    view_id: int,
    settings: SettingsDep,
) -> dict[str, bool]:
    """Delete a saved view."""
    with db.core_connection(settings) as conn:
        loop_service.delete_loop_view(view_id=view_id, conn=conn)
    return {"deleted": True}


@router.post("/views/{view_id}/apply", response_model=LoopViewApplyResponse)
def loop_view_apply_endpoint(
    view_id: int,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LoopViewApplyResponse:
    """Apply a saved view and return matching loops."""
    with db.core_connection(settings) as conn:
        result = loop_service.apply_loop_view(
            view_id=view_id,
            limit=limit,
            offset=offset,
            conn=conn,
        )
    view = result["view"]
    return LoopViewApplyResponse(
        view=LoopViewResponse(
            id=view["id"],
            name=view["name"],
            query=view["query"],
            description=view.get("description"),
            created_at_utc=view["created_at"],
            updated_at_utc=view["updated_at"],
        ),
        query=result["query"],
        limit=result["limit"],
        offset=result["offset"],
        items=[LoopResponse(**item) for item in result["items"]],
    )


@router.get("/{loop_id}", response_model=LoopResponse)
def loop_get_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> LoopResponse:
    with db.core_connection(settings) as conn:
        record = loop_service.get_loop(loop_id=loop_id, conn=conn)
    return LoopResponse(**record)


@router.patch("/{loop_id}", response_model=LoopResponse)
def loop_update_endpoint(
    loop_id: int,
    request: LoopUpdateRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("PATCH", f"/loops/{loop_id}")
        payload = {"loop_id": loop_id, "fields": fields}
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

            record = loop_service.update_loop(loop_id=loop_id, fields=fields, conn=conn)
            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            record = loop_service.update_loop(loop_id=loop_id, fields=fields, conn=conn)
        response = LoopResponse(**record).model_dump()

    return LoopResponse(**response)


@router.post("/{loop_id}/close", response_model=LoopResponse)
def loop_close_endpoint(
    loop_id: int,
    request: LoopCloseRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    if not is_terminal_status(request.status):
        raise HTTPException(status_code=400, detail="status must be completed or dropped")

    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/close")
        payload = {"loop_id": loop_id, "status": request.status.value, "note": request.note}
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

            record = loop_service.transition_status(
                loop_id=loop_id,
                to_status=request.status,
                conn=conn,
                note=request.note,
            )
            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            record = loop_service.transition_status(
                loop_id=loop_id,
                to_status=request.status,
                conn=conn,
                note=request.note,
            )
        response = LoopResponse(**record).model_dump()

    return LoopResponse(**response)


@router.post("/{loop_id}/status", response_model=LoopResponse)
def loop_status_endpoint(
    loop_id: int,
    request: LoopStatusRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/status")
        payload = {"loop_id": loop_id, "status": request.status.value, "note": request.note}
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

            record = loop_service.transition_status(
                loop_id=loop_id,
                to_status=request.status,
                conn=conn,
                note=request.note,
            )
            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            record = loop_service.transition_status(
                loop_id=loop_id,
                to_status=request.status,
                conn=conn,
                note=request.note,
            )
        response = LoopResponse(**record).model_dump()

    return LoopResponse(**response)


@router.post("/{loop_id}/enrich", response_model=LoopResponse)
def loop_enrich_endpoint(
    loop_id: int,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopResponse | JSONResponse:
    if idempotency_key is not None:
        try:
            key = normalize_idempotency_key(idempotency_key, settings.idempotency_max_key_length)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

        scope = build_http_scope("POST", f"/loops/{loop_id}/enrich")
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

            record = loop_service.request_enrichment(loop_id=loop_id, conn=conn)
            response = LoopResponse(**record).model_dump()
            db.finalize_idempotency_response(
                scope=scope,
                idempotency_key=key,
                response_status=200,
                response_body=response,
                conn=conn,
            )
    else:
        with db.core_connection(settings) as conn:
            record = loop_service.request_enrichment(loop_id=loop_id, conn=conn)
        response = LoopResponse(**record).model_dump()

    background_tasks.add_task(
        loop_enrichment.enrich_loop,
        loop_id=loop_id,
        settings=settings,
    )
    return LoopResponse(**response)


@router.get("/events/stream")
def loop_events_stream(
    settings: SettingsDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    cursor: Annotated[
        str | None, Query(description="Cursor for replay from specific event ID")
    ] = None,
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
            # Open database connection
            conn = sqlite3.connect(settings.core_db_path)
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


def _generate_webhook_secret() -> str:
    """Generate a secure random webhook secret.

    Returns:
        A URL-safe base64-encoded secret string.
    """
    return secrets.token_urlsafe(32)


@router.post("/webhooks/subscriptions", response_model=WebhookSubscriptionCreateResponse)
def create_webhook_subscription(
    request: WebhookSubscriptionCreate,
    settings: SettingsDep,
) -> WebhookSubscriptionCreateResponse:
    """Create a new webhook subscription.

    The secret returned in the response is the ONLY time it will be
    provided. Store it securely to verify webhook signatures.
    """
    secret = _generate_webhook_secret()
    with db.core_connection(settings) as conn:
        subscription = webhooks_repo.create_subscription(
            url=request.url,
            secret=secret,
            event_types=request.event_types,
            description=request.description,
            conn=conn,
        )
    return WebhookSubscriptionCreateResponse(
        id=subscription.id,
        url=subscription.url,
        event_types=subscription.event_types,
        active=subscription.active,
        description=subscription.description,
        created_at_utc=subscription.created_at,
        updated_at_utc=subscription.updated_at,
        secret=secret,
    )


@router.get("/webhooks/subscriptions", response_model=List[WebhookSubscriptionResponse])
def list_webhook_subscriptions(settings: SettingsDep) -> List[WebhookSubscriptionResponse]:
    """List all webhook subscriptions."""
    with db.core_connection(settings) as conn:
        subscriptions = webhooks_repo.list_subscriptions(conn=conn)
    return [
        WebhookSubscriptionResponse(
            id=sub.id,
            url=sub.url,
            event_types=sub.event_types,
            active=sub.active,
            description=sub.description,
            created_at_utc=sub.created_at,
            updated_at_utc=sub.updated_at,
        )
        for sub in subscriptions
    ]


@router.patch(
    "/webhooks/subscriptions/{subscription_id}", response_model=WebhookSubscriptionResponse
)
def update_webhook_subscription(
    subscription_id: int,
    request: WebhookSubscriptionUpdate,
    settings: SettingsDep,
) -> WebhookSubscriptionResponse:
    """Update a webhook subscription."""
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no_fields_to_update")

    with db.core_connection(settings) as conn:
        subscription = webhooks_repo.update_subscription(
            subscription_id=subscription_id,
            url=fields.get("url"),
            event_types=fields.get("event_types"),
            active=fields.get("active"),
            description=fields.get("description"),
            conn=conn,
        )
        if subscription is None:
            raise HTTPException(status_code=404, detail="subscription_not_found")

    return WebhookSubscriptionResponse(
        id=subscription.id,
        url=subscription.url,
        event_types=subscription.event_types,
        active=subscription.active,
        description=subscription.description,
        created_at_utc=subscription.created_at,
        updated_at_utc=subscription.updated_at,
    )


@router.delete("/webhooks/subscriptions/{subscription_id}")
def delete_webhook_subscription(
    subscription_id: int,
    settings: SettingsDep,
) -> dict[str, bool]:
    """Delete a webhook subscription."""
    with db.core_connection(settings) as conn:
        deleted = webhooks_repo.delete_subscription(
            subscription_id=subscription_id,
            conn=conn,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="subscription_not_found")
    return {"deleted": True}


@router.get(
    "/webhooks/subscriptions/{subscription_id}/deliveries",
    response_model=List[WebhookDeliveryResponse],
)
def list_webhook_deliveries(
    subscription_id: int,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> List[WebhookDeliveryResponse]:
    """List recent deliveries for a webhook subscription."""
    with db.core_connection(settings) as conn:
        # Verify subscription exists
        subscription = webhooks_repo.get_subscription(
            subscription_id=subscription_id,
            conn=conn,
        )
        if subscription is None:
            raise HTTPException(status_code=404, detail="subscription_not_found")

        deliveries = webhooks_repo.list_deliveries_for_subscription(
            subscription_id=subscription_id,
            conn=conn,
            limit=limit,
        )

    return [
        WebhookDeliveryResponse(
            id=d.id,
            subscription_id=d.subscription_id,
            event_id=d.event_id,
            event_type=d.event_type,
            status=d.status.value,
            http_status=d.http_status,
            error_message=d.error_message,
            attempt_count=d.attempt_count,
            next_retry_at=d.next_retry_at,
            created_at_utc=d.created_at,
            updated_at_utc=d.updated_at,
        )
        for d in deliveries
    ]
