from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import db
from .loops import enrichment as loop_enrichment
from .loops import repo as loop_repo
from .loops import service as loop_service
from .loops.models import LoopStatus
from .settings import get_settings

mcp = FastMCP("Cloop Loops", json_response=True)


@mcp.tool(name="loop.create")
def loop_create(
    raw_text: str,
    captured_at: str,
    client_tz_offset_min: int,
    status: str = "inbox",
) -> dict[str, Any]:
    settings = get_settings()
    db.init_databases(settings)
    loop_status = LoopStatus(status)
    with db.core_connection(settings) as conn:
        record = loop_service.capture_loop(
            raw_text=raw_text,
            captured_at_iso=captured_at,
            client_tz_offset_min=client_tz_offset_min,
            status=loop_status,
            conn=conn,
        )
    return record


@mcp.tool(name="loop.update")
def loop_update(loop_id: int, fields: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    db.init_databases(settings)
    with db.core_connection(settings) as conn:
        return loop_service.update_loop(loop_id=loop_id, fields=fields, conn=conn)


@mcp.tool(name="loop.close")
def loop_close(loop_id: int, status: str = "done", note: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    db.init_databases(settings)
    loop_status = LoopStatus(status)
    if loop_status not in {LoopStatus.DONE, LoopStatus.DROPPED}:
        raise ValueError("status must be done or dropped")
    with db.core_connection(settings) as conn:
        return loop_service.transition_status(
            loop_id=loop_id,
            to_status=loop_status,
            note=note,
            conn=conn,
        )


@mcp.tool(name="loop.list")
def loop_list(status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    settings = get_settings()
    db.init_databases(settings)
    parsed_status = LoopStatus(status) if status else None
    with db.core_connection(settings) as conn:
        return loop_service.list_loops(
            status=parsed_status,
            limit=limit,
            offset=offset,
            conn=conn,
        )


@mcp.tool(name="loop.search")
def loop_search(query: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    settings = get_settings()
    db.init_databases(settings)
    with db.core_connection(settings) as conn:
        return loop_service.search_loops(query=query, limit=limit, offset=offset, conn=conn)


@mcp.tool(name="loop.snooze")
def loop_snooze(loop_id: int, snooze_until_utc: str) -> dict[str, Any]:
    settings = get_settings()
    db.init_databases(settings)
    with db.core_connection(settings) as conn:
        return loop_service.update_loop(
            loop_id=loop_id,
            fields={"snooze_until_utc": snooze_until_utc},
            conn=conn,
        )


@mcp.tool(name="loop.enrich")
def loop_enrich(loop_id: int) -> dict[str, Any]:
    settings = get_settings()
    db.init_databases(settings)
    with db.core_connection(settings) as conn:
        loop_service.request_enrichment(loop_id=loop_id, conn=conn)
        result = loop_enrichment.enrich_loop(loop_id=loop_id, conn=conn, settings=settings)
    return result


@mcp.tool(name="project.list")
def project_list() -> list[dict[str, Any]]:
    settings = get_settings()
    db.init_databases(settings)
    with db.core_connection(settings) as conn:
        return loop_repo.list_projects(conn=conn)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
