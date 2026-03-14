"""Memory entry CRUD endpoints.

Purpose:
    HTTP endpoints for assistant memory management.

Responsibilities:
    - GET /memory: List memories with filters
    - POST /memory: Create new memory
    - GET /memory/search: Search memories by content
    - GET /memory/{id}: Get single memory
    - PUT /memory/{id}: Update memory
    - DELETE /memory/{id}: Delete memory

Non-scope:
    - LLM integration (see routes/chat.py)
    - Tool execution (see tools.py)
"""

from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, Query, Response, status

from .. import memory_management
from ..schemas.memory import (
    MemoryCategory,
    MemoryCreateRequest,
    MemoryListResponse,
    MemoryResponse,
    MemorySearchResponse,
    MemorySource,
    MemoryUpdateRequest,
)
from ..settings import Settings, get_settings

router = APIRouter(prefix="/memory", tags=["memory"])

SettingsDep = Annotated[Settings, Depends(lambda: get_settings())]


@router.get("", response_model=MemoryListResponse)
def list_memories(
    settings: SettingsDep,
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
    source: Annotated[MemorySource | None, Query(description="Filter by source")] = None,
    min_priority: Annotated[int | None, Query(ge=0, description="Minimum priority")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 50,
    cursor: Annotated[str | None, Query(description="Pagination cursor")] = None,
) -> Dict[str, Any]:
    """List memory entries with optional filters."""
    return memory_management.list_memory_entries(
        category=category,
        source=source,
        min_priority=min_priority,
        limit=limit,
        cursor=cursor,
        settings=settings,
    )


@router.post("", response_model=MemoryResponse, status_code=201)
def create_memory(
    request: MemoryCreateRequest,
    settings: SettingsDep,
) -> Dict[str, Any]:
    """Create a new memory entry."""
    return memory_management.create_memory_entry(
        payload=request.model_dump(),
        settings=settings,
    )


@router.get("/search", response_model=MemorySearchResponse)
def search_memories(
    settings: SettingsDep,
    q: Annotated[str, Query(max_length=200, description="Search query")],
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
    source: Annotated[MemorySource | None, Query(description="Filter by source")] = None,
    min_priority: Annotated[int | None, Query(ge=0, description="Minimum priority")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 50,
    cursor: Annotated[str | None, Query(description="Pagination cursor")] = None,
) -> Dict[str, Any]:
    """Search memory entries by text."""
    return memory_management.search_memory_entries(
        query=q,
        category=category,
        source=source,
        min_priority=min_priority,
        limit=limit,
        cursor=cursor,
        settings=settings,
    )


@router.get("/{entry_id}", response_model=MemoryResponse)
def get_memory(
    entry_id: int,
    settings: SettingsDep,
) -> Dict[str, Any]:
    """Get a single memory entry by ID."""
    return memory_management.get_memory_entry(entry_id=entry_id, settings=settings)


@router.put("/{entry_id}", response_model=MemoryResponse)
def update_memory(
    entry_id: int,
    request: MemoryUpdateRequest,
    settings: SettingsDep,
) -> Dict[str, Any]:
    """Update a memory entry."""
    return memory_management.update_memory_entry(
        entry_id=entry_id,
        fields=request.model_dump(exclude_unset=True),
        settings=settings,
    )


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    entry_id: int,
    settings: SettingsDep,
) -> Response:
    """Delete a memory entry."""
    memory_management.delete_memory_entry(entry_id=entry_id, settings=settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
