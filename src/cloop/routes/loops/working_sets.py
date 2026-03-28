"""Working-set HTTP endpoints.

Purpose:
    Expose durable working-set CRUD, membership management, and active
    focus-mode context for the operator shell.

Responsibilities:
    - Define FastAPI routes for working-set CRUD operations
    - Validate payloads with Pydantic schemas
    - Map working-set validation failures to stable HTTP errors
    - Return launch-ready working-set payloads for the frontend shell

Scope:
    - HTTP transport for working-set operations only

Usage:
    - Mounted under `/loops` via `cloop.routes.loops`

Invariants/Assumptions:
    - Service-layer validation remains the source of truth
    - Responses return resolved working-set payloads after each mutation

Non-scope:
    - Persisting working-set rows directly
    - Browser-only rendering or shell routing logic
    - Planning/review/chat execution beyond working-set selection
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ... import db
from ...loops import working_sets
from ...loops._repo.shared import _UNSET
from ...loops.errors import ValidationError
from ...schemas.loops import (
    WorkingSetBulkItemCreateRequest,
    WorkingSetContextResponse,
    WorkingSetContextUpdateRequest,
    WorkingSetCreateRequest,
    WorkingSetDeleteResponse,
    WorkingSetItemCreateRequest,
    WorkingSetReorderRequest,
    WorkingSetResponse,
    WorkingSetUndoRequest,
    WorkingSetUndoResponse,
    WorkingSetUpdateRequest,
)
from ._common import (
    IdempotencyKeyHeader,
    SettingsDep,
    map_not_found_to_404,
    map_validation_to_400,
    no_fields_to_update_http_exception,
    run_idempotent_loop_route,
)

router = APIRouter()


def _raise_working_set_http_exception(exc: ValidationError) -> None:
    """Map working-set validation failures to stable HTTP responses."""
    if exc.field == "name" and "already exists" in exc.reason.lower():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "working_set_name_conflict",
                "message": exc.reason,
                "field": exc.field,
            },
        ) from None
    if exc.field in {"working_set_id", "item_id"} and "not found" in exc.reason.lower():
        resource_type = "working set" if exc.field == "working_set_id" else "working-set item"
        raise map_not_found_to_404(resource_type=resource_type, message=exc.reason) from None
    raise map_validation_to_400(exc) from None


@router.get("/working-sets", response_model=list[WorkingSetResponse])
def list_working_sets_endpoint(settings: SettingsDep) -> list[WorkingSetResponse]:
    """List all durable working sets with resolved items."""
    with db.core_connection(settings) as conn:
        payloads = working_sets.list_working_sets(conn=conn)
    return [WorkingSetResponse.model_validate(payload) for payload in payloads]


@router.post("/working-sets", response_model=WorkingSetResponse, status_code=201)
def create_working_set_endpoint(
    request: WorkingSetCreateRequest,
    settings: SettingsDep,
) -> WorkingSetResponse:
    """Create a durable working set."""
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.create_working_set(
                name=request.name,
                description=request.description,
                conn=conn,
            )
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetResponse.model_validate(payload)


@router.get("/working-sets/context", response_model=WorkingSetContextResponse)
def get_working_set_context_endpoint(settings: SettingsDep) -> WorkingSetContextResponse:
    """Return the active working-set and focus-mode context."""
    with db.core_connection(settings) as conn:
        payload = working_sets.get_working_set_context(conn=conn)
    return WorkingSetContextResponse.model_validate(payload)


@router.patch("/working-sets/context", response_model=WorkingSetContextResponse)
def update_working_set_context_endpoint(
    request: WorkingSetContextUpdateRequest,
    settings: SettingsDep,
) -> WorkingSetContextResponse:
    """Update the active working-set and focus-mode context."""
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.update_working_set_context(
                active_working_set_id=request.active_working_set_id,
                focus_mode_enabled=request.focus_mode_enabled,
                conn=conn,
            )
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetContextResponse.model_validate(payload)


@router.get("/working-sets/{working_set_id}", response_model=WorkingSetResponse)
def get_working_set_endpoint(working_set_id: int, settings: SettingsDep) -> WorkingSetResponse:
    """Get one durable working set."""
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.get_working_set(working_set_id=working_set_id, conn=conn)
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetResponse.model_validate(payload)


@router.patch("/working-sets/{working_set_id}", response_model=WorkingSetResponse)
def update_working_set_endpoint(
    working_set_id: int,
    request: WorkingSetUpdateRequest,
    settings: SettingsDep,
) -> WorkingSetResponse:
    """Update working-set metadata."""
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise no_fields_to_update_http_exception() from None
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.update_working_set(
                working_set_id=working_set_id,
                name=fields.get("name"),
                description=fields.get("description", _UNSET),
                conn=conn,
            )
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetResponse.model_validate(payload)


@router.delete("/working-sets/{working_set_id}", response_model=WorkingSetDeleteResponse)
def delete_working_set_endpoint(
    working_set_id: int,
    settings: SettingsDep,
) -> WorkingSetDeleteResponse:
    """Delete one durable working set."""
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.delete_working_set(working_set_id=working_set_id, conn=conn)
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetDeleteResponse.model_validate(payload)


@router.post("/working-sets/{working_set_id}/items", response_model=WorkingSetResponse)
def add_working_set_item_endpoint(
    working_set_id: int,
    request: WorkingSetItemCreateRequest,
    settings: SettingsDep,
) -> WorkingSetResponse:
    """Add one item to a working set and return the updated set."""
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.add_working_set_item(
                working_set_id=working_set_id,
                item_type=request.item_type,
                item_id=request.item_id,
                label=request.label,
                description=request.description,
                metadata=request.metadata,
                conn=conn,
            )
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetResponse.model_validate(payload)


@router.post("/working-sets/{working_set_id}/items/bulk", response_model=WorkingSetResponse)
def add_working_set_items_bulk_endpoint(
    working_set_id: int,
    request: WorkingSetBulkItemCreateRequest,
    settings: SettingsDep,
) -> WorkingSetResponse:
    """Add multiple items to a working set atomically and return the updated set."""
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.add_working_set_items_bulk(
                working_set_id=working_set_id,
                items=[item.model_dump(mode="python") for item in request.items],
                conn=conn,
            )
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetResponse.model_validate(payload)


@router.delete("/working-sets/{working_set_id}/items/{item_id}", response_model=WorkingSetResponse)
def remove_working_set_item_endpoint(
    working_set_id: int,
    item_id: int,
    settings: SettingsDep,
) -> WorkingSetResponse:
    """Remove one item from a working set and return the updated set."""
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.remove_working_set_item(
                working_set_id=working_set_id,
                item_id=item_id,
                conn=conn,
            )
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetResponse.model_validate(payload)


@router.post("/working-sets/{working_set_id}/reorder", response_model=WorkingSetResponse)
def reorder_working_set_items_endpoint(
    working_set_id: int,
    request: WorkingSetReorderRequest,
    settings: SettingsDep,
) -> WorkingSetResponse:
    """Reorder one working set's membership rows."""
    with db.core_connection(settings) as conn:
        try:
            payload = working_sets.reorder_working_set_items(
                working_set_id=working_set_id,
                ordered_item_ids=request.ordered_item_ids,
                conn=conn,
            )
        except ValidationError as exc:
            _raise_working_set_http_exception(exc)
    return WorkingSetResponse.model_validate(payload)


@router.post("/working-sets/undo", response_model=WorkingSetUndoResponse)
def undo_working_set_endpoint(
    request: WorkingSetUndoRequest,
    settings: SettingsDep,
    idempotency_key: str | None = IdempotencyKeyHeader,
) -> WorkingSetUndoResponse | JSONResponse:
    """Undo one exact latest working-set mutation event."""
    payload = {"expected_event_id": request.expected_event_id}
    try:
        result = run_idempotent_loop_route(
            settings=settings,
            method="POST",
            path="/loops/working-sets/undo",
            idempotency_key=idempotency_key,
            payload=payload,
            execute=lambda conn: working_sets.undo_working_set_event(
                expected_event_id=request.expected_event_id,
                conn=conn,
            ),
        )
    except ValidationError as exc:
        _raise_working_set_http_exception(exc)
    if isinstance(result, dict):
        return WorkingSetUndoResponse.model_validate(result)
    return result
