"""Shared continuity rerun builders.

Purpose:
    Build backend-authored rerun contracts shared by workflow responses and
    durable continuity consumers.

Responsibilities:
    - Author typed recall-query rerun contracts for grounded chat and RAG.
    - Keep rerun landing semantics consistent across backend emitters.
    - Centralize recall rerun wording so frontend consumers stay mapper-only.

Non-scope:
    - Executing reruns or persisting continuity records.
    - Planning or review rerun contract construction.

Scope:
    - Backend contract construction only.

Usage:
    - Imported by chat_execution.py and rag_execution.py when shaping recall
      result payloads.

Invariants/Assumptions:
    - Reruns preserve recall tool, query, and landing surface identity.
    - Explicit working-set scope stays attached whenever the caller provides it.
"""

from __future__ import annotations

from typing import Literal

from .schemas._loops.continuity import (
    ContinuityLocationResponse,
    ContinuityRecallQueryRerunHandle,
    ContinuityRerunAction,
    ContinuityRerunAttemptContract,
    ContinuityRerunPostRunBehavior,
)


def build_recall_query_rerun_action(
    *,
    recall_tool: Literal["chat", "rag"],
    query: str,
    label: str,
    description: str,
    provenance_label: str,
    freshness_label: str | None,
    strategy_summary: str,
    strict_invariants: list[str],
    may_vary: list[str],
    include_loop_context: bool | None = None,
    include_memory_context: bool | None = None,
    include_rag_context: bool | None = None,
    working_set_id: int | None = None,
) -> ContinuityRerunAction:
    """Build one backend-authored recall-query rerun contract."""
    return ContinuityRerunAction(
        label=label,
        description=description,
        rerun=ContinuityRecallQueryRerunHandle(
            recall_tool=recall_tool,
            query=query,
            working_set_id=working_set_id,
            include_loop_context=include_loop_context,
            include_memory_context=include_memory_context,
            include_rag_context=include_rag_context,
        ),
        contract=ContinuityRerunAttemptContract(
            mode="rerun",
            provenance_label=provenance_label,
            freshness_label=freshness_label,
            strategy_summary=strategy_summary,
            strict_invariants=strict_invariants,
            may_vary=may_vary,
            post_run=ContinuityRerunPostRunBehavior(
                summary=description,
                location=ContinuityLocationResponse(
                    state="recall",
                    recall_tool=recall_tool,
                    query=query,
                    working_set_id=working_set_id,
                ),
            ),
        ),
    )


__all__ = ["build_recall_query_rerun_action"]
