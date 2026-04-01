"""Recall-result follow-through builders.

Purpose:
    Author backend-owned landed follow-through contracts for grounded chat and
    document recall results so every transport can expose the same receipt-ready
    reopen metadata.

Responsibilities:
    - Build landed recall follow-through payloads for grounded chat answers.
    - Build landed recall follow-through payloads for document-backed answers.
    - Keep recall workflow-thread and receipt-card wording consistent.

Non-scope:
    - Executing reruns or persisting continuity outcomes.
    - Frontend receipt rendering or browser-local working-set overlays.

Usage:
    Imported by chat_execution.py and rag_execution.py when shaping successful
    recall responses.

Invariants/Assumptions:
    - Follow-through always reopens the landed recall result, never the generic
      launch surface.
    - Working-set scope may still be overlaid later by the frontend when the
      browser owns that local context.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from .schemas._loops.continuity import (
    ContinuityDisplayCardResponse,
    ContinuityDisplayHandoffResponse,
    ContinuityDisplayPreviewItemResponse,
    ContinuityDisplayTrustResponse,
    ContinuityRerunAction,
    ReviewFollowThroughResponse,
    WorkflowThreadRefResponse,
)


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).strip()


def _truncate(value: str, limit: int) -> str:
    normalized = _normalize_text(value)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _source_labels(sources: Iterable[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for source in sources:
        path = _normalize_text(str(source.get("document_path") or ""))
        if not path:
            continue
        if path in seen:
            continue
        labels.append(path)
        seen.add(path)
        if len(labels) >= 3:
            break
    return labels


def _workflow_thread(
    *,
    recall_tool: Literal["chat", "rag"],
    query: str,
    title: str,
    summary: str,
) -> WorkflowThreadRefResponse:
    normalized_query = _normalize_text(query).lower()
    return WorkflowThreadRefResponse(
        id=f"recall:{recall_tool}:{normalized_query}",
        kind="recall",
        title=title,
        summary=summary,
        parent_outcome_id=None,
    )


def _receipt_card(
    *,
    eyebrow: str,
    title: str,
    summary: str,
    rationale: str,
    preview: list[ContinuityDisplayPreviewItemResponse],
    context_sources: list[str],
    confidence_label: str,
    rollback_label: str,
    next_step: str,
    breadcrumbs: list[str],
    tone: Literal["progress", "attention"],
) -> ContinuityDisplayCardResponse:
    return ContinuityDisplayCardResponse(
        kind="receipt",
        tone=tone,
        eyebrow=eyebrow,
        title=title,
        summary=summary,
        rationale=rationale,
        preview=preview,
        trust=ContinuityDisplayTrustResponse(
            generation_label=eyebrow,
            generation_tone=tone,
            context_sources=context_sources,
            assumptions=[
                "This receipt reopens the landed recall result instead of a generic launch surface."
            ],
            confidence_label=confidence_label,
            confidence_tone=tone,
            freshness_label="Saved just now",
            freshness_tone="progress",
            rollback_label=rollback_label,
            rollback_tone="progress",
            impact_summary=summary,
            impact_tone=tone,
        ),
        handoff=ContinuityDisplayHandoffResponse(
            change_summary=(
                "This keeps the landed recall result resumable from continuity, the receipt rail, "
                "and Recent commands."
            ),
            created_resources=[],
            next_step=next_step,
            breadcrumbs=breadcrumbs,
            working_set=None,
        ),
        action_context_label="Continue from here",
        action_warning=None,
    )


def build_chat_follow_through(
    *,
    query: str,
    answer: str,
    rerun_action: ContinuityRerunAction | None,
    include_loop_context: bool,
    include_memory_context: bool,
    include_rag_context: bool,
    memory_entries_used: int,
    rag_chunks_used: int,
    sources: list[dict[str, Any]],
) -> ReviewFollowThroughResponse | None:
    """Build one landed follow-through contract for a grounded chat answer."""
    normalized_query = _normalize_text(query)
    normalized_answer = _truncate(answer, 160)
    if not normalized_query or not normalized_answer or rerun_action is None:
        return None

    source_labels = _source_labels(sources)
    grounding_parts: list[str] = []
    context_sources: list[str] = []
    if include_loop_context:
        grounding_parts.append("loops")
        context_sources.append("Loop context")
    if include_memory_context:
        grounding_parts.append(
            f"memory ({memory_entries_used})" if memory_entries_used > 0 else "memory"
        )
        context_sources.append("Direct memory")
    if include_rag_context or rag_chunks_used > 0 or source_labels:
        grounding_parts.append(
            f"documents ({rag_chunks_used})" if rag_chunks_used > 0 else "documents"
        )
        context_sources.append("Indexed local documents")
    context_sources.extend(f"Source: {label}" for label in source_labels)
    tone: Literal["progress", "attention"] = (
        "attention" if source_labels or include_rag_context or include_loop_context else "progress"
    )
    title = f"Grounded answer · {_truncate(normalized_query, 56)}"
    summary = normalized_answer
    return ReviewFollowThroughResponse(
        display_card=_receipt_card(
            eyebrow="Recall receipt",
            title=title,
            summary=summary,
            rationale=(
                "Grounded chat answers should land as resumable outcomes so continuity reopens "
                "the answer you got, not just the entry question."
            ),
            preview=[
                ContinuityDisplayPreviewItemResponse(
                    label="Question", value=_truncate(normalized_query, 72)
                ),
                ContinuityDisplayPreviewItemResponse(
                    label="Grounding",
                    value=" · ".join(grounding_parts) if grounding_parts else "Grounded recall",
                ),
                *(
                    [
                        ContinuityDisplayPreviewItemResponse(
                            label="Sources",
                            value=" · ".join(source_labels),
                        )
                    ]
                    if source_labels
                    else []
                ),
            ],
            context_sources=context_sources or ["Grounded recall"],
            confidence_label=(
                f"{len(source_labels)} supporting source{'s' if len(source_labels) != 1 else ''}"
                if source_labels
                else ("Grounded answer saved" if grounding_parts else "Answer saved")
            ),
            rollback_label="Rerun the same grounded question to refresh this answer.",
            next_step=(
                "Reopen the answer, rerun it, or carry it into the next recall or execution step."
            ),
            breadcrumbs=["Home", "Recall", "Grounded chat"],
            tone=tone,
        ),
        undo_action=None,
        rerun_action=rerun_action,
        resume_location=rerun_action.contract.post_run.location,
        grounded_chat_location=None,
        workflow_thread=_workflow_thread(
            recall_tool="chat",
            query=normalized_query,
            title=title,
            summary=summary,
        ),
        working_set_id=None,
    )


def build_rag_follow_through(
    *,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    rerun_action: ContinuityRerunAction | None,
) -> ReviewFollowThroughResponse | None:
    """Build one landed follow-through contract for a document-backed answer."""
    normalized_question = _normalize_text(question)
    normalized_answer = _truncate(answer, 160)
    if not normalized_question or not normalized_answer or rerun_action is None:
        return None

    source_labels = _source_labels(sources)
    title = f"Evidence answer · {_truncate(normalized_question, 56)}"
    summary = normalized_answer
    source_count = len(sources)
    tone: Literal["progress", "attention"] = "attention" if source_count > 0 else "progress"
    return ReviewFollowThroughResponse(
        display_card=_receipt_card(
            eyebrow="Recall receipt",
            title=title,
            summary=summary,
            rationale=(
                "Document answers should land as resumable outcomes so continuity reopens the "
                "evidence-backed result instead of a blank recall surface."
            ),
            preview=[
                ContinuityDisplayPreviewItemResponse(
                    label="Question", value=_truncate(normalized_question, 72)
                ),
                ContinuityDisplayPreviewItemResponse(
                    label="Evidence",
                    value=(
                        " · ".join(source_labels)
                        if source_labels
                        else f"{source_count} retrieved source{'s' if source_count != 1 else ''}"
                    ),
                ),
            ],
            context_sources=(
                ["Indexed local documents", *[f"Source: {label}" for label in source_labels]]
                if source_labels
                else ["Indexed local documents"]
            ),
            confidence_label=(
                f"{source_count} retrieved source{'s' if source_count != 1 else ''}"
                if source_count > 0
                else "Evidence-backed answer saved"
            ),
            rollback_label="Rerun the same document question to refresh this answer.",
            next_step=(
                "Reopen the evidence-backed answer, rerun it, or turn it into the next action."
            ),
            breadcrumbs=["Home", "Recall", "Documents"],
            tone=tone,
        ),
        undo_action=None,
        rerun_action=rerun_action,
        resume_location=rerun_action.contract.post_run.location,
        grounded_chat_location=None,
        workflow_thread=_workflow_thread(
            recall_tool="rag",
            query=normalized_question,
            title=title,
            summary=summary,
        ),
        working_set_id=None,
    )


__all__ = ["build_chat_follow_through", "build_rag_follow_through"]
