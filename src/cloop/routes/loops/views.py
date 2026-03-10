"""Loop saved view endpoints.

Purpose:
    HTTP endpoints for managing saved loop views (filtered queries).

Responsibilities:
    - Define FastAPI routes for saved view CRUD operations
    - Validate incoming requests using Pydantic schemas
    - Apply saved views to filter and return matching loops
    - Convert service layer results to HTTP responses
    - Handle pagination parameters for view application

Non-scope:
    - Does not implement view query parsing or execution logic
    - Does not persist views directly (delegated to service layer)
    - Does not manage loop state or lifecycle
    - Does not implement authentication or authorization
    - Does not handle idempotency (views are simple CRUD)

Endpoints:
- POST /views: Create a new saved view
- GET /views: List all saved views
- GET /views/{view_id}: Get a saved view
- PATCH /views/{view_id}: Update a saved view
- DELETE /views/{view_id}: Delete a saved view
- POST /views/{view_id}/apply: Apply a saved view and return matching loops
"""

from typing import Annotated

from fastapi import APIRouter, Query

from ... import db
from ...loops import service as loop_service
from ...loops.errors import ValidationError
from ...schemas.loops import (
    LoopViewApplyResponse,
    LoopViewCreateRequest,
    LoopViewResponse,
    LoopViewUpdateRequest,
)
from ._common import (
    SettingsDep,
    build_loop_responses,
    build_loop_view_response,
    map_not_found_to_404,
    map_validation_to_400,
    no_fields_to_update_http_exception,
)

router = APIRouter()


def _raise_view_http_exception(exc: ValidationError) -> None:
    """Map saved-view validation failures to stable HTTP responses."""
    if exc.field == "view_id" and "not found" in exc.reason.lower():
        raise map_not_found_to_404(resource_type="view", message=exc.reason) from None
    raise map_validation_to_400(exc) from None


@router.post("/views", response_model=LoopViewResponse)
def loop_view_create_endpoint(
    request: LoopViewCreateRequest,
    settings: SettingsDep,
) -> LoopViewResponse:
    """Create a new saved view."""
    with db.core_connection(settings) as conn:
        try:
            view = loop_service.create_loop_view(
                name=request.name,
                query=request.query,
                description=request.description,
                conn=conn,
            )
        except ValidationError as exc:
            _raise_view_http_exception(exc)
    return build_loop_view_response(view)


@router.get("/views", response_model=list[LoopViewResponse])
def loop_view_list_endpoint(settings: SettingsDep) -> list[LoopViewResponse]:
    """List all saved views."""
    with db.core_connection(settings) as conn:
        views = loop_service.list_loop_views(conn=conn)
    return [build_loop_view_response(view) for view in views]


@router.get("/views/{view_id}", response_model=LoopViewResponse)
def loop_view_get_endpoint(
    view_id: int,
    settings: SettingsDep,
) -> LoopViewResponse:
    """Get a saved view by ID."""
    with db.core_connection(settings) as conn:
        try:
            view = loop_service.get_loop_view(view_id=view_id, conn=conn)
        except ValidationError as exc:
            _raise_view_http_exception(exc)
    return build_loop_view_response(view)


@router.patch("/views/{view_id}", response_model=LoopViewResponse)
def loop_view_update_endpoint(
    view_id: int,
    request: LoopViewUpdateRequest,
    settings: SettingsDep,
) -> LoopViewResponse:
    """Update a saved view."""
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise no_fields_to_update_http_exception() from None

    with db.core_connection(settings) as conn:
        try:
            view = loop_service.update_loop_view(
                view_id=view_id,
                name=fields.get("name"),
                query=fields.get("query"),
                description=fields.get("description"),
                conn=conn,
            )
        except ValidationError as exc:
            _raise_view_http_exception(exc)
    return build_loop_view_response(view)


@router.delete("/views/{view_id}")
def loop_view_delete_endpoint(
    view_id: int,
    settings: SettingsDep,
) -> dict[str, bool]:
    """Delete a saved view."""
    with db.core_connection(settings) as conn:
        try:
            loop_service.delete_loop_view(view_id=view_id, conn=conn)
        except ValidationError as exc:
            _raise_view_http_exception(exc)
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
        try:
            result = loop_service.apply_loop_view(
                view_id=view_id,
                limit=limit,
                offset=offset,
                conn=conn,
            )
        except ValidationError as exc:
            _raise_view_http_exception(exc)
    view = result["view"]
    return LoopViewApplyResponse(
        view=build_loop_view_response(view),
        query=result["query"],
        limit=result["limit"],
        offset=result["offset"],
        items=build_loop_responses(result["items"]),
    )
