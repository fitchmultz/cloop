"""Loop dependency management endpoints.

Purpose:
    HTTP endpoints for managing loop dependencies (blockers and dependents).

Responsibilities:
    - Add and remove dependencies between loops
    - List blocking dependencies (what a loop depends on)
    - List blocked dependents (what a loop blocks)

Non-scope:
    - Dependency graph resolution or topological sorting
    - Automatic unblocking when dependencies complete
    - Circular dependency detection (handled by service layer)

Endpoints:
- POST /{loop_id}/dependencies: Add a dependency
- DELETE /{loop_id}/dependencies/{depends_on_id}: Remove a dependency
- GET /{loop_id}/dependencies: List dependencies (blockers)
- GET /{loop_id}/blocking: List dependents (what this loop blocks)
"""

from fastapi import APIRouter

from ... import db
from ...loops.service import (
    add_loop_dependency,
    get_loop_blocking,
    get_loop_dependencies,
    remove_loop_dependency,
)
from ...schemas.loops import DependencyAddRequest, DependencyInfo, LoopWithDependenciesResponse
from ._common import SettingsDep

router = APIRouter()


@router.post("/{loop_id}/dependencies", response_model=LoopWithDependenciesResponse)
def add_dependency_endpoint(
    loop_id: int,
    request: DependencyAddRequest,
    settings: SettingsDep,
) -> LoopWithDependenciesResponse:
    """Add a dependency to a loop."""
    with db.core_connection(settings) as conn:
        result = add_loop_dependency(
            loop_id=loop_id,
            depends_on_loop_id=request.depends_on_loop_id,
            conn=conn,
        )
    return LoopWithDependenciesResponse(**result)


@router.delete(
    "/{loop_id}/dependencies/{depends_on_id}", response_model=LoopWithDependenciesResponse
)
async def remove_dependency_endpoint(
    loop_id: int,
    depends_on_id: int,
    settings: SettingsDep,
) -> LoopWithDependenciesResponse:
    """Remove a dependency from a loop."""
    with db.core_connection(settings) as conn:
        result = remove_loop_dependency(
            loop_id=loop_id,
            depends_on_loop_id=depends_on_id,
            conn=conn,
        )
    return LoopWithDependenciesResponse(**result)


@router.get("/{loop_id}/dependencies", response_model=list[DependencyInfo])
async def list_dependencies_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> list[DependencyInfo]:
    """List all dependencies (blockers) for a loop."""
    with db.core_connection(settings) as conn:
        deps = get_loop_dependencies(loop_id=loop_id, conn=conn)
    return [DependencyInfo(**dep) for dep in deps]


@router.get("/{loop_id}/blocking", response_model=list[DependencyInfo])
async def list_blocking_endpoint(
    loop_id: int,
    settings: SettingsDep,
) -> list[DependencyInfo]:
    """List all loops that depend on this loop (dependents)."""
    with db.core_connection(settings) as conn:
        blocking = get_loop_blocking(loop_id=loop_id, conn=conn)
    return [DependencyInfo(**blk) for blk in blocking]
