"""Shared orchestration for explicit loop enrichment flows.

Purpose:
    Centralize the request + execute + readback sequence for explicit enrichment
    so HTTP routes, CLI commands, MCP tools, and manual tool calls all expose
    the same contract.

Responsibilities:
    - Mark a loop as pending enrichment before execution
    - Run the synchronous enrichment worker
    - Return the canonical updated loop snapshot plus enrichment metadata
    - Execute explicit enrichment across selected loop sets
    - Preview and run query-selected bulk enrichment flows

Non-scope:
    - Prompt construction or LLM parsing (see enrichment.py)
    - Transport-specific response modeling or error mapping
    - Background enrichment for capture/autopilot flows
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .. import typingx
from ..constants import BULK_OPERATION_MAX_ITEMS
from ..settings import Settings
from . import enrichment as loop_enrichment
from . import read_service, repo, service
from .errors import LoopNotFoundError, ValidationError
from .write_ops import _enrich_records_batch


@dataclass(slots=True, frozen=True)
class LoopEnrichmentResult:
    """Canonical result for one explicit enrichment execution."""

    loop: dict[str, Any]
    suggestion_id: int
    applied_fields: list[str]
    needs_clarification: list[str]

    def to_payload(self) -> dict[str, Any]:
        """Convert the result into a transport-ready payload."""
        return {
            "loop": self.loop,
            "suggestion_id": self.suggestion_id,
            "applied_fields": self.applied_fields,
            "needs_clarification": self.needs_clarification,
        }


@dataclass(slots=True, frozen=True)
class BulkLoopEnrichmentItemResult:
    """Canonical result for one loop inside a bulk enrichment execution."""

    index: int
    loop_id: int
    ok: bool
    loop: dict[str, Any] | None = None
    suggestion_id: int | None = None
    applied_fields: list[str] = field(default_factory=list)
    needs_clarification: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        """Convert the item result into a transport-ready payload."""
        payload: dict[str, Any] = {
            "index": self.index,
            "loop_id": self.loop_id,
            "ok": self.ok,
        }
        if self.loop is not None:
            payload["loop"] = self.loop
        if self.suggestion_id is not None:
            payload["suggestion_id"] = self.suggestion_id
        if self.applied_fields:
            payload["applied_fields"] = self.applied_fields
        if self.needs_clarification:
            payload["needs_clarification"] = self.needs_clarification
        if self.error is not None:
            payload["error"] = self.error
        return payload


@dataclass(slots=True, frozen=True)
class BulkLoopEnrichmentResult:
    """Canonical result for bulk enrichment across multiple loops."""

    ok: bool
    results: list[BulkLoopEnrichmentItemResult]
    succeeded: int
    failed: int

    def to_payload(self) -> dict[str, Any]:
        """Convert the bulk result into a transport-ready payload."""
        return {
            "ok": self.ok,
            "results": [result.to_payload() for result in self.results],
            "succeeded": self.succeeded,
            "failed": self.failed,
        }


def _classify_bulk_enrichment_error(exc: Exception) -> str:
    if isinstance(exc, LoopNotFoundError):
        return "not_found"
    if isinstance(exc, ValidationError | ValueError):
        return "validation_error"
    return "internal_error"


@typingx.validate_io()
def preview_query_loop_enrichment_targets(
    *,
    query: str,
    limit: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Preview loops that would be targeted by query-based bulk enrichment."""
    if limit < 1:
        raise ValidationError("limit", "must be positive")
    if limit > BULK_OPERATION_MAX_ITEMS:
        raise ValidationError(
            "limit",
            f"must be less than or equal to {BULK_OPERATION_MAX_ITEMS}",
        )

    records = repo.search_loops_by_query(query=query, limit=limit, offset=0, conn=conn)
    targets = _enrich_records_batch(records, conn=conn)
    return {
        "query": query,
        "dry_run": True,
        "matched_count": len(records),
        "limited": len(records) >= limit,
        "targets": targets,
    }


@typingx.validate_io()
def orchestrate_loop_enrichment(
    *,
    loop_id: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> LoopEnrichmentResult:
    """Run the canonical explicit enrichment flow for one loop."""
    service.request_enrichment(loop_id=loop_id, conn=conn)
    enrichment_result = loop_enrichment.enrich_loop(loop_id=loop_id, conn=conn, settings=settings)
    loop_payload = read_service.get_loop(loop_id=loop_id, conn=conn)
    return LoopEnrichmentResult(
        loop=loop_payload,
        suggestion_id=int(enrichment_result["suggestion_id"]),
        applied_fields=list(enrichment_result.get("applied_fields") or []),
        needs_clarification=list(enrichment_result.get("needs_clarification") or []),
    )


@typingx.validate_io()
def orchestrate_bulk_loop_enrichment(
    *,
    loop_ids: list[int],
    conn: sqlite3.Connection,
    settings: Settings,
) -> BulkLoopEnrichmentResult:
    """Run explicit enrichment for a selected set of loop IDs."""
    if not loop_ids:
        raise ValidationError("loop_ids", "at least one loop_id is required")
    if len(loop_ids) > BULK_OPERATION_MAX_ITEMS:
        raise ValidationError(
            "loop_ids",
            f"maximum {BULK_OPERATION_MAX_ITEMS} loop_ids are allowed",
        )

    seen_ids: set[int] = set()
    results: list[BulkLoopEnrichmentItemResult] = []

    for index, loop_id in enumerate(loop_ids):
        if loop_id in seen_ids:
            results.append(
                BulkLoopEnrichmentItemResult(
                    index=index,
                    loop_id=loop_id,
                    ok=False,
                    error={
                        "code": "validation_error",
                        "message": f"duplicate loop_id in request: {loop_id}",
                    },
                )
            )
            continue
        seen_ids.add(loop_id)

        try:
            result = orchestrate_loop_enrichment(loop_id=loop_id, conn=conn, settings=settings)
        except Exception as exc:  # noqa: BLE001
            results.append(
                BulkLoopEnrichmentItemResult(
                    index=index,
                    loop_id=loop_id,
                    ok=False,
                    error={
                        "code": _classify_bulk_enrichment_error(exc),
                        "message": str(exc),
                    },
                )
            )
            continue

        results.append(
            BulkLoopEnrichmentItemResult(
                index=index,
                loop_id=loop_id,
                ok=True,
                loop=result.loop,
                suggestion_id=result.suggestion_id,
                applied_fields=result.applied_fields,
                needs_clarification=result.needs_clarification,
            )
        )

    failed = sum(1 for result in results if not result.ok)
    return BulkLoopEnrichmentResult(
        ok=failed == 0,
        results=results,
        succeeded=len(results) - failed,
        failed=failed,
    )


@typingx.validate_io()
def orchestrate_query_bulk_loop_enrichment(
    *,
    query: str,
    limit: int,
    dry_run: bool,
    conn: sqlite3.Connection,
    settings: Settings,
) -> dict[str, Any]:
    """Preview or execute bulk enrichment for loops selected by DSL query."""
    preview = preview_query_loop_enrichment_targets(query=query, limit=limit, conn=conn)
    if dry_run:
        return preview

    loop_ids = [int(target["id"]) for target in preview["targets"]]
    if not loop_ids:
        return {
            "query": query,
            "dry_run": False,
            "ok": True,
            "matched_count": 0,
            "limited": False,
            "results": [],
            "succeeded": 0,
            "failed": 0,
        }

    result = orchestrate_bulk_loop_enrichment(loop_ids=loop_ids, conn=conn, settings=settings)
    payload = result.to_payload()
    payload["query"] = query
    payload["dry_run"] = False
    payload["matched_count"] = len(loop_ids)
    payload["limited"] = bool(preview.get("limited", False))
    return payload
