"""Loop saved view endpoints.

Purpose:
    HTTP endpoints for managing saved loop views (filtered queries).

Endpoints:
- POST /views: Create a new saved view
- GET /views: List all saved views
- GET /views/{view_id}: Get a saved view
- PATCH /views/{view_id}: Update a saved view
- DELETE /views/{view_id}: Delete a saved view
- POST /views/{view_id}/apply: Apply a saved view and return matching loops
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from ... import db
from ...loops import service as loop_service
from ...schemas.loops import (
    LoopResponse,
    LoopViewApplyResponse,
    LoopViewCreateRequest,
    LoopViewResponse,
    LoopViewUpdateRequest,
)
from ._common import SettingsDep

router = APIRouter()


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


@router.get("/views", response_model=list[LoopViewResponse])
def loop_view_list_endpoint(settings: SettingsDep) -> list[LoopViewResponse]:
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
