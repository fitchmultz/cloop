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
"""

from typing import Annotated, Any, List, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from .. import db
from ..constants import DEFAULT_LOOP_LIST_LIMIT, DEFAULT_LOOP_NEXT_LIMIT
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
    LoopStatusRequest,
    LoopUpdateRequest,
)
from ..settings import Settings, get_settings

router = APIRouter(prefix="/loops", tags=["loops"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


@router.post("/capture", response_model=LoopResponse)
def loop_capture_endpoint(
    request: LoopCaptureRequest,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
) -> LoopResponse:
    status = resolve_status_from_flags(
        scheduled=request.scheduled,
        blocked=request.blocked,
        actionable=request.actionable,
    )
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
    if settings.autopilot_enabled:
        background_tasks.add_task(
            loop_enrichment.enrich_loop,
            loop_id=record["id"],
            settings=settings,
        )
    return LoopResponse(**record)


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
) -> LoopImportResponse:
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
) -> LoopResponse:
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no_fields_to_update")
    with db.core_connection(settings) as conn:
        record = loop_service.update_loop(loop_id=loop_id, fields=fields, conn=conn)
    return LoopResponse(**record)


@router.post("/{loop_id}/close", response_model=LoopResponse)
def loop_close_endpoint(
    loop_id: int,
    request: LoopCloseRequest,
    settings: SettingsDep,
) -> LoopResponse:
    if not is_terminal_status(request.status):
        raise HTTPException(status_code=400, detail="status must be completed or dropped")
    with db.core_connection(settings) as conn:
        record = loop_service.transition_status(
            loop_id=loop_id,
            to_status=request.status,
            conn=conn,
            note=request.note,
        )
    return LoopResponse(**record)


@router.post("/{loop_id}/status", response_model=LoopResponse)
def loop_status_endpoint(
    loop_id: int,
    request: LoopStatusRequest,
    settings: SettingsDep,
) -> LoopResponse:
    with db.core_connection(settings) as conn:
        record = loop_service.transition_status(
            loop_id=loop_id,
            to_status=request.status,
            conn=conn,
            note=request.note,
        )
    return LoopResponse(**record)


@router.post("/{loop_id}/enrich", response_model=LoopResponse)
def loop_enrich_endpoint(
    loop_id: int,
    background_tasks: BackgroundTasks,
    settings: SettingsDep,
) -> LoopResponse:
    with db.core_connection(settings) as conn:
        record = loop_service.request_enrichment(loop_id=loop_id, conn=conn)
    background_tasks.add_task(
        loop_enrichment.enrich_loop,
        loop_id=loop_id,
        settings=settings,
    )
    return LoopResponse(**record)
