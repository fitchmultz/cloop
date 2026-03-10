"""Loop bulk operation endpoints.

Purpose:
    HTTP endpoints for performing bulk operations on multiple loops.

Responsibilities:
    - Bulk update fields on multiple loops
    - Bulk close loops with configurable status (completed/dropped)
    - Bulk snooze loops with scheduled wake times
    - Support transactional mode (all-or-nothing) for bulk operations
    - Return per-item success/failure status

Non-scope:
    - Does not perform duplicate detection during bulk operations
    - Does not validate claim tokens for individual loops
    - Does not support partial field updates per item (all items use same field set)

Endpoints:
- POST /bulk/update: Bulk update multiple loops
- POST /bulk/close: Bulk close multiple loops
- POST /bulk/snooze: Bulk snooze multiple loops
"""

from fastapi import APIRouter

from ... import db
from ...loops import bulk as loop_bulk
from ...schemas.loops import (
    BulkCloseRequest,
    BulkCloseResponse,
    BulkSnoozeRequest,
    BulkSnoozeResponse,
    BulkUpdateRequest,
    BulkUpdateResponse,
    QueryBulkCloseRequest,
    QueryBulkCloseResponse,
    QueryBulkPreviewResponse,
    QueryBulkSnoozeRequest,
    QueryBulkSnoozeResponse,
    QueryBulkUpdateRequest,
    QueryBulkUpdateResponse,
)
from ._common import (
    SettingsDep,
    build_bulk_result_items,
    build_query_bulk_preview_response,
)

router = APIRouter()


def _serialize_bulk_update_request(request: BulkUpdateRequest) -> list[dict[str, object]]:
    """Convert bulk update request items into service-layer payloads."""
    return [
        {
            "loop_id": item.loop_id,
            "fields": item.fields.model_dump(exclude_unset=True),
        }
        for item in request.updates
    ]


def _serialize_bulk_close_request(request: BulkCloseRequest) -> list[dict[str, object]]:
    """Convert bulk close request items into service-layer payloads."""
    return [
        {
            key: value
            for key, value in {
                "loop_id": item.loop_id,
                "status": item.status.value,
                "note": item.note,
            }.items()
            if value is not None
        }
        for item in request.items
    ]


def _serialize_bulk_snooze_request(request: BulkSnoozeRequest) -> list[dict[str, object]]:
    """Convert bulk snooze request items into service-layer payloads."""
    return [
        {
            "loop_id": item.loop_id,
            "snooze_until_utc": item.snooze_until_utc,
        }
        for item in request.items
    ]


@router.post("/bulk/update", response_model=BulkUpdateResponse)
def bulk_update_endpoint(
    request: BulkUpdateRequest,
    settings: SettingsDep,
) -> BulkUpdateResponse:
    """Bulk update multiple loops."""
    with db.core_connection(settings) as conn:
        result = loop_bulk.bulk_update_loops(
            updates=_serialize_bulk_update_request(request),
            transactional=request.transactional,
            conn=conn,
        )

    return BulkUpdateResponse(
        ok=result["ok"],
        transactional=result["transactional"],
        results=build_bulk_result_items(result["results"]),
        succeeded=result["succeeded"],
        failed=result["failed"],
    )


@router.post("/bulk/close", response_model=BulkCloseResponse)
def bulk_close_endpoint(
    request: BulkCloseRequest,
    settings: SettingsDep,
) -> BulkCloseResponse:
    """Bulk close multiple loops (completed or dropped)."""
    with db.core_connection(settings) as conn:
        result = loop_bulk.bulk_close_loops(
            items=_serialize_bulk_close_request(request),
            transactional=request.transactional,
            conn=conn,
        )

    return BulkCloseResponse(
        ok=result["ok"],
        transactional=result["transactional"],
        results=build_bulk_result_items(result["results"]),
        succeeded=result["succeeded"],
        failed=result["failed"],
    )


@router.post("/bulk/snooze", response_model=BulkSnoozeResponse)
def bulk_snooze_endpoint(
    request: BulkSnoozeRequest,
    settings: SettingsDep,
) -> BulkSnoozeResponse:
    """Bulk snooze multiple loops."""
    with db.core_connection(settings) as conn:
        result = loop_bulk.bulk_snooze_loops(
            items=_serialize_bulk_snooze_request(request),
            transactional=request.transactional,
            conn=conn,
        )

    return BulkSnoozeResponse(
        ok=result["ok"],
        transactional=result["transactional"],
        results=build_bulk_result_items(result["results"]),
        succeeded=result["succeeded"],
        failed=result["failed"],
    )


@router.post("/bulk/query/update", response_model=None)
def query_bulk_update_endpoint(
    request: QueryBulkUpdateRequest,
    settings: SettingsDep,
) -> QueryBulkUpdateResponse | QueryBulkPreviewResponse:
    """Bulk update loops matching DSL query."""
    with db.core_connection(settings) as conn:
        result = loop_bulk.query_bulk_update_loops(
            query=request.query,
            fields=request.fields.model_dump(exclude_unset=True),
            transactional=request.transactional,
            dry_run=request.dry_run,
            limit=request.limit,
            conn=conn,
        )

    if result.get("dry_run"):
        return QueryBulkPreviewResponse(**build_query_bulk_preview_response(result))

    return QueryBulkUpdateResponse(
        query=result["query"],
        dry_run=result["dry_run"],
        ok=result["ok"],
        transactional=result["transactional"],
        matched_count=result["matched_count"],
        limited=result.get("limited", False),
        results=build_bulk_result_items(result.get("results", [])),
        succeeded=result["succeeded"],
        failed=result["failed"],
    )


@router.post("/bulk/query/close", response_model=None)
def query_bulk_close_endpoint(
    request: QueryBulkCloseRequest,
    settings: SettingsDep,
) -> QueryBulkCloseResponse | QueryBulkPreviewResponse:
    """Bulk close loops matching DSL query."""
    with db.core_connection(settings) as conn:
        result = loop_bulk.query_bulk_close_loops(
            query=request.query,
            status=request.status.value,
            note=request.note,
            transactional=request.transactional,
            dry_run=request.dry_run,
            limit=request.limit,
            conn=conn,
        )

    if result.get("dry_run"):
        return QueryBulkPreviewResponse(**build_query_bulk_preview_response(result))

    return QueryBulkCloseResponse(
        query=result["query"],
        dry_run=result["dry_run"],
        ok=result["ok"],
        transactional=result["transactional"],
        matched_count=result["matched_count"],
        limited=result.get("limited", False),
        results=build_bulk_result_items(result.get("results", [])),
        succeeded=result["succeeded"],
        failed=result["failed"],
    )


@router.post("/bulk/query/snooze", response_model=None)
def query_bulk_snooze_endpoint(
    request: QueryBulkSnoozeRequest,
    settings: SettingsDep,
) -> QueryBulkSnoozeResponse | QueryBulkPreviewResponse:
    """Bulk snooze loops matching DSL query."""
    with db.core_connection(settings) as conn:
        result = loop_bulk.query_bulk_snooze_loops(
            query=request.query,
            snooze_until_utc=request.snooze_until_utc,
            transactional=request.transactional,
            dry_run=request.dry_run,
            limit=request.limit,
            conn=conn,
        )

    if result.get("dry_run"):
        return QueryBulkPreviewResponse(**build_query_bulk_preview_response(result))

    return QueryBulkSnoozeResponse(
        query=result["query"],
        dry_run=result["dry_run"],
        ok=result["ok"],
        transactional=result["transactional"],
        matched_count=result["matched_count"],
        limited=result.get("limited", False),
        results=build_bulk_result_items(result.get("results", [])),
        succeeded=result["succeeded"],
        failed=result["failed"],
    )
