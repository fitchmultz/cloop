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
from ...loops import service as loop_service
from ...schemas.loops import (
    BulkCloseRequest,
    BulkCloseResponse,
    BulkResultItem,
    BulkSnoozeRequest,
    BulkSnoozeResponse,
    BulkUpdateRequest,
    BulkUpdateResponse,
    LoopResponse,
    QueryBulkCloseRequest,
    QueryBulkCloseResponse,
    QueryBulkPreviewResponse,
    QueryBulkSnoozeRequest,
    QueryBulkSnoozeResponse,
    QueryBulkUpdateRequest,
    QueryBulkUpdateResponse,
)
from ._common import SettingsDep

router = APIRouter()


@router.post("/bulk/update", response_model=BulkUpdateResponse)
def bulk_update_endpoint(
    request: BulkUpdateRequest,
    settings: SettingsDep,
) -> BulkUpdateResponse:
    """Bulk update multiple loops."""
    # Convert Pydantic models to dicts for service layer
    updates = []
    for item in request.updates:
        update_dict = {
            "loop_id": item.loop_id,
            "fields": item.fields.model_dump(exclude_unset=True),
        }
        updates.append(update_dict)

    with db.core_connection(settings) as conn:
        result = loop_service.bulk_update_loops(
            updates=updates,
            transactional=request.transactional,
            conn=conn,
        )

    # Convert results to response models
    results = []
    for r in result["results"]:
        result_item = BulkResultItem(
            index=r["index"],
            loop_id=r["loop_id"],
            ok=r["ok"],
            loop=LoopResponse(**r["loop"]) if r.get("loop") else None,
            error=r.get("error"),
        )
        results.append(result_item)

    return BulkUpdateResponse(
        ok=result["ok"],
        transactional=result["transactional"],
        results=results,
        succeeded=result["succeeded"],
        failed=result["failed"],
    )


@router.post("/bulk/close", response_model=BulkCloseResponse)
def bulk_close_endpoint(
    request: BulkCloseRequest,
    settings: SettingsDep,
) -> BulkCloseResponse:
    """Bulk close multiple loops (completed or dropped)."""
    # Convert Pydantic models to dicts for service layer
    items = []
    for item in request.items:
        item_dict = {
            "loop_id": item.loop_id,
            "status": item.status.value,
        }
        if item.note:
            item_dict["note"] = item.note
        items.append(item_dict)

    with db.core_connection(settings) as conn:
        result = loop_service.bulk_close_loops(
            items=items,
            transactional=request.transactional,
            conn=conn,
        )

    # Convert results to response models
    results = []
    for r in result["results"]:
        result_item = BulkResultItem(
            index=r["index"],
            loop_id=r["loop_id"],
            ok=r["ok"],
            loop=LoopResponse(**r["loop"]) if r.get("loop") else None,
            error=r.get("error"),
        )
        results.append(result_item)

    return BulkCloseResponse(
        ok=result["ok"],
        transactional=result["transactional"],
        results=results,
        succeeded=result["succeeded"],
        failed=result["failed"],
    )


@router.post("/bulk/snooze", response_model=BulkSnoozeResponse)
def bulk_snooze_endpoint(
    request: BulkSnoozeRequest,
    settings: SettingsDep,
) -> BulkSnoozeResponse:
    """Bulk snooze multiple loops."""
    # Convert Pydantic models to dicts for service layer
    items = []
    for item in request.items:
        item_dict = {
            "loop_id": item.loop_id,
            "snooze_until_utc": item.snooze_until_utc,
        }
        items.append(item_dict)

    with db.core_connection(settings) as conn:
        result = loop_service.bulk_snooze_loops(
            items=items,
            transactional=request.transactional,
            conn=conn,
        )

    # Convert results to response models
    results = []
    for r in result["results"]:
        result_item = BulkResultItem(
            index=r["index"],
            loop_id=r["loop_id"],
            ok=r["ok"],
            loop=LoopResponse(**r["loop"]) if r.get("loop") else None,
            error=r.get("error"),
        )
        results.append(result_item)

    return BulkSnoozeResponse(
        ok=result["ok"],
        transactional=result["transactional"],
        results=results,
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
        result = loop_service.query_bulk_update_loops(
            query=request.query,
            fields=request.fields.model_dump(exclude_unset=True),
            transactional=request.transactional,
            dry_run=request.dry_run,
            limit=request.limit,
            conn=conn,
        )

    if result.get("dry_run"):
        return QueryBulkPreviewResponse(
            query=result["query"],
            dry_run=True,
            matched_count=result["matched_count"],
            limited=result.get("limited", False),
            targets=[LoopResponse(**t) for t in result.get("targets", [])],
        )

    results = [
        BulkResultItem(
            index=r["index"],
            loop_id=r["loop_id"],
            ok=r["ok"],
            loop=LoopResponse(**r["loop"]) if r.get("loop") else None,
            error=r.get("error"),
        )
        for r in result.get("results", [])
    ]

    return QueryBulkUpdateResponse(
        query=result["query"],
        dry_run=result["dry_run"],
        ok=result["ok"],
        transactional=result["transactional"],
        matched_count=result["matched_count"],
        limited=result.get("limited", False),
        results=results,
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
        result = loop_service.query_bulk_close_loops(
            query=request.query,
            status=request.status.value,
            note=request.note,
            transactional=request.transactional,
            dry_run=request.dry_run,
            limit=request.limit,
            conn=conn,
        )

    if result.get("dry_run"):
        return QueryBulkPreviewResponse(
            query=result["query"],
            dry_run=True,
            matched_count=result["matched_count"],
            limited=result.get("limited", False),
            targets=[LoopResponse(**t) for t in result.get("targets", [])],
        )

    results = [
        BulkResultItem(
            index=r["index"],
            loop_id=r["loop_id"],
            ok=r["ok"],
            loop=LoopResponse(**r["loop"]) if r.get("loop") else None,
            error=r.get("error"),
        )
        for r in result.get("results", [])
    ]

    return QueryBulkCloseResponse(
        query=result["query"],
        dry_run=result["dry_run"],
        ok=result["ok"],
        transactional=result["transactional"],
        matched_count=result["matched_count"],
        limited=result.get("limited", False),
        results=results,
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
        result = loop_service.query_bulk_snooze_loops(
            query=request.query,
            snooze_until_utc=request.snooze_until_utc,
            transactional=request.transactional,
            dry_run=request.dry_run,
            limit=request.limit,
            conn=conn,
        )

    if result.get("dry_run"):
        return QueryBulkPreviewResponse(
            query=result["query"],
            dry_run=True,
            matched_count=result["matched_count"],
            limited=result.get("limited", False),
            targets=[LoopResponse(**t) for t in result.get("targets", [])],
        )

    results = [
        BulkResultItem(
            index=r["index"],
            loop_id=r["loop_id"],
            ok=r["ok"],
            loop=LoopResponse(**r["loop"]) if r.get("loop") else None,
            error=r.get("error"),
        )
        for r in result.get("results", [])
    ]

    return QueryBulkSnoozeResponse(
        query=result["query"],
        dry_run=result["dry_run"],
        ok=result["ok"],
        transactional=result["transactional"],
        matched_count=result["matched_count"],
        limited=result.get("limited", False),
        results=results,
        succeeded=result["succeeded"],
        failed=result["failed"],
    )
