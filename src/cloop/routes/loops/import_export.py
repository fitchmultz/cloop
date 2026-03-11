"""Loop import and export endpoints.

Purpose:
    HTTP endpoints for exporting loop data and importing loop snapshots.

Responsibilities:
    - Export loops with optional filters
    - Import loop payloads with dry-run and conflict policy support

Non-scope:
    - Loop lifecycle mutations
    - Metrics, search, or review queries
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ... import db
from ...loops import service as loop_service
from ...loops.errors import ValidationError
from ...loops.models import parse_utc_datetime
from ...schemas.export_import import ConflictPolicy, ExportFilters, ImportOptions
from ...schemas.loops import (
    LoopExportItem,
    LoopExportResponse,
    LoopImportRequest,
    LoopImportResponse,
)
from ._common import IdempotencyKeyHeader, SettingsDep, run_idempotent_loop_route

router = APIRouter()


def _import_response(
    *,
    request: LoopImportRequest,
    options: ImportOptions,
    conn: Any,
) -> dict[str, Any]:
    result = loop_service.import_loops(loops=request.loops, conn=conn, options=options)
    return LoopImportResponse(
        imported=result.imported,
        skipped=result.skipped,
        updated=result.updated,
        conflicts_detected=result.conflicts_detected,
        dry_run=result.dry_run,
        preview=result.preview.model_dump() if result.preview else None,
    ).model_dump()


@router.get("/export", response_model=LoopExportResponse)
def loop_export_endpoint(
    settings: SettingsDep,
    status: Annotated[list[str] | None, Query(description="Filter by status values")] = None,
    project: Annotated[str | None, Query(description="Filter by project name")] = None,
    tag: Annotated[str | None, Query(description="Filter by tag")] = None,
    created_after: Annotated[
        str | None, Query(description="Only loops created after this ISO datetime")
    ] = None,
    created_before: Annotated[
        str | None, Query(description="Only loops created before this ISO datetime")
    ] = None,
    updated_after: Annotated[
        str | None, Query(description="Only loops updated after this ISO datetime")
    ] = None,
) -> LoopExportResponse:
    filters = None
    if any([status, project, tag, created_after, created_before, updated_after]):
        filters = ExportFilters(
            status=status,
            project=project,
            tag=tag,
            created_after=parse_utc_datetime(created_after) if created_after else None,
            created_before=parse_utc_datetime(created_before) if created_before else None,
            updated_after=parse_utc_datetime(updated_after) if updated_after else None,
        )

    with db.core_connection(settings) as conn:
        loops_data: list[dict[str, Any]] = loop_service.export_loops(conn=conn, filters=filters)
    export_items = [LoopExportItem(**loop_item) for loop_item in loops_data]
    return LoopExportResponse(version=1, loops=export_items, filtered=filters is not None)


@router.post("/import", response_model=LoopImportResponse)
def loop_import_endpoint(
    request: LoopImportRequest,
    settings: SettingsDep,
    dry_run: Annotated[bool, Query(description="Preview changes without writing")] = False,
    conflict_policy: Annotated[
        str, Query(description="How to handle conflicts: skip, update, fail")
    ] = "fail",
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> LoopImportResponse | JSONResponse:
    try:
        policy = ConflictPolicy(conflict_policy)
    except ValueError as exc:
        raise ValidationError(
            "conflict_policy",
            "must be one of: skip, update, fail",
        ) from exc

    options = ImportOptions(dry_run=dry_run, conflict_policy=policy)
    payload = {
        "loops": [loop.model_dump() for loop in request.loops],
        "dry_run": dry_run,
        "conflict_policy": conflict_policy,
    }

    result = run_idempotent_loop_route(
        settings=settings,
        method="POST",
        path="/loops/import",
        idempotency_key=idempotency_key,
        payload=payload,
        execute=lambda conn: _import_response(request=request, options=options, conn=conn),
    )

    if isinstance(result, JSONResponse):
        return result
    return LoopImportResponse(**result)
