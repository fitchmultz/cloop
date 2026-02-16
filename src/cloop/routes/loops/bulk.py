"""Loop bulk operation endpoints.

Purpose:
    HTTP endpoints for performing bulk operations on multiple loops.

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
