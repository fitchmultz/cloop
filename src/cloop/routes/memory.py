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

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..schemas.memory import (
    MemoryCategory,
    MemoryCreateRequest,
    MemoryListResponse,
    MemoryResponse,
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
    return db.list_memory_entries(
        category=category.value if category else None,
        source=source.value if source else None,
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
    entry = db.create_memory_entry(
        key=request.key,
        content=request.content,
        category=request.category.value,
        priority=request.priority,
        source=request.source.value,
        metadata=request.metadata,
        settings=settings,
    )
    return entry


@router.get("/search", response_model=MemoryListResponse)
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
    return db.search_memory_entries(
        query=q,
        category=category.value if category else None,
        source=source.value if source else None,
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
    entry = db.get_memory_entry(entry_id, settings)
    if entry is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return entry


@router.put("/{entry_id}", response_model=MemoryResponse)
def update_memory(
    entry_id: int,
    request: MemoryUpdateRequest,
    settings: SettingsDep,
) -> Dict[str, Any]:
    """Update a memory entry."""
    existing = db.get_memory_entry(entry_id, settings)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory entry not found")

    entry = db.update_memory_entry(
        entry_id,
        key=request.key,
        content=request.content,
        category=request.category.value if request.category else None,
        priority=request.priority,
        source=request.source.value if request.source else None,
        metadata=request.metadata,
        settings=settings,
    )
    assert entry is not None
    return entry


@router.delete("/{entry_id}", status_code=204)
def delete_memory(
    entry_id: int,
    settings: SettingsDep,
) -> None:
    """Delete a memory entry."""
    deleted = db.delete_memory_entry(entry_id, settings)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory entry not found")
