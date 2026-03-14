"""Shared orchestration for explicit loop enrichment flows.

Purpose:
    Centralize the request + execute + readback sequence for explicit enrichment
    so HTTP routes, CLI commands, MCP tools, and manual tool calls all expose
    the same contract.

Responsibilities:
    - Mark a loop as pending enrichment before execution
    - Run the synchronous enrichment worker
    - Return the canonical updated loop snapshot plus enrichment metadata

Non-scope:
    - Prompt construction or LLM parsing (see enrichment.py)
    - Transport-specific response modeling or error mapping
    - Background enrichment for capture/autopilot flows
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from ..settings import Settings
from . import enrichment as loop_enrichment
from . import read_service, service


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
