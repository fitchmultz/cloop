"""Recall-result follow-through builders.

Purpose:
    Author backend-owned landed follow-through contracts for grounded chat,
    document recall, and recall-side mutations so every transport can expose
    the same receipt-ready reopen metadata.

Responsibilities:
    - Build landed recall follow-through payloads for grounded chat answers.
    - Build landed recall follow-through payloads for document-backed answers.
    - Build landed recall follow-through payloads for direct memory mutations.
    - Build landed recall follow-through payloads for knowledge-ingest mutations.
    - Keep recall workflow-thread and receipt-card wording consistent.

Non-scope:
    - Executing reruns or persisting continuity outcomes.
    - Frontend receipt rendering or browser-local working-set overlays.

Usage:
    Imported by chat_execution.py, rag_execution.py, and direct recall mutation
    transports when shaping successful recall responses.

Invariants/Assumptions:
    - Follow-through always reopens the landed recall result, never the generic
      launch surface.
    - Explicit working-set scope stays attached whenever the caller provides it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from .schemas._loops.continuity import (
    ContinuityDisplayCardResponse,
    ContinuityDisplayHandoffResponse,
    ContinuityDisplayPreviewItemResponse,
    ContinuityDisplayTrustResponse,
    ContinuityDisplayWorkingSetResponse,
    ContinuityLocationResponse,
    ContinuityRerunAction,
    ReviewFollowThroughResponse,
    WorkflowThreadRefResponse,
)
from .schemas.memory import MemoryResponse
from .schemas.rag import IngestResponse


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


def _working_set_id(working_set: dict[str, Any] | None) -> int | None:
    return int(working_set["working_set_id"]) if isinstance(working_set, dict) else None


def _mapping(value: MemoryResponse | IngestResponse | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return value.model_dump(mode="python")


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


def _mutation_workflow_thread(
    *,
    thread_id: str,
    title: str,
    summary: str,
) -> WorkflowThreadRefResponse:
    return WorkflowThreadRefResponse(
        id=thread_id,
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
    working_set: dict[str, Any] | None,
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
            working_set=(
                ContinuityDisplayWorkingSetResponse(**working_set)
                if working_set is not None
                else None
            ),
        ),
        action_context_label="Continue from here",
        action_warning=None,
    )


def _memory_label(entry: MemoryResponse | dict[str, Any]) -> str:
    payload = _mapping(entry)
    key = _normalize_text(str(payload.get("key") or ""))
    if key:
        return key
    content = _normalize_text(str(payload.get("content") or ""))
    if content:
        return _truncate(content, 56)
    return f"Memory #{int(payload['id'])}"


def _knowledge_label(paths: list[str]) -> str:
    normalized_paths = [path.strip() for path in paths if path and path.strip()]
    if not normalized_paths:
        return "Knowledge"
    if len(normalized_paths) == 1:
        leaf = normalized_paths[0].replace("\\", "/").rstrip("/").split("/")[-1]
        return leaf or normalized_paths[0]
    return f"{len(normalized_paths)} paths"


def _knowledge_preview_label(paths: list[str]) -> str:
    return "Path" if len([path for path in paths if path.strip()]) == 1 else "Paths"


def _recall_location(
    *,
    recall_tool: Literal["memory", "rag"],
    query: str | None,
    working_set_id: int | None,
    memory_id: int | None = None,
) -> ContinuityLocationResponse:
    return ContinuityLocationResponse(
        state="recall",
        recall_tool=recall_tool,
        review_focus=None,
        session_id=None,
        loop_id=None,
        view_id=None,
        memory_id=memory_id,
        working_set_id=working_set_id,
        query=_normalize_text(query or "") or None,
        include_loop_context=None,
        include_memory_context=None,
        include_rag_context=None,
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
    working_set: dict[str, Any] | None,
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
            working_set=working_set,
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
        working_set_id=_working_set_id(working_set),
    )


def build_rag_follow_through(
    *,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    rerun_action: ContinuityRerunAction | None,
    working_set: dict[str, Any] | None,
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
            working_set=working_set,
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
        working_set_id=_working_set_id(working_set),
    )


def build_memory_follow_through(
    *,
    action: Literal["created", "updated", "deleted"],
    entry: MemoryResponse | dict[str, Any],
    query: str | None,
    working_set: dict[str, Any] | None,
) -> ReviewFollowThroughResponse:
    """Build one landed follow-through contract for a direct-memory mutation."""
    payload = _mapping(entry)
    label = _memory_label(payload)
    title_prefix = (
        "Deleted" if action == "deleted" else "Updated" if action == "updated" else "Created"
    )
    title = f"{title_prefix} memory · {label}"
    summary = (
        f"{label} was removed from durable memory."
        if action == "deleted"
        else (
            f"{label} now reflects the latest durable context."
            if action == "updated"
            else f"{label} is now available as durable memory."
        )
    )
    tone: Literal["progress", "attention"] = "attention" if action == "deleted" else "progress"
    working_set_id = _working_set_id(working_set)
    resume_location = _recall_location(
        recall_tool="memory",
        query=query if action == "deleted" else None,
        working_set_id=working_set_id,
        memory_id=None if action == "deleted" else int(payload["id"]),
    )
    return ReviewFollowThroughResponse(
        display_card=_receipt_card(
            eyebrow="Recall receipt",
            title=title,
            summary=summary,
            rationale=(
                "Direct-memory mutations should land as resumable outcomes so continuity and "
                "recent history reopen the durable memory result instead of relying on status "
                "text."
            ),
            preview=[
                ContinuityDisplayPreviewItemResponse(label="Memory", value=label),
                ContinuityDisplayPreviewItemResponse(
                    label="Category",
                    value=str(payload.get("category") or "fact"),
                ),
            ],
            context_sources=["Direct memory"],
            confidence_label=(
                "Mutation applied with follow-up required"
                if action == "deleted"
                else "Mutation applied"
            ),
            rollback_label=(
                "Create a replacement memory entry if this durable context still matters."
                if action == "deleted"
                else "Edit or delete the memory entry if this durable context is no longer correct."
            ),
            next_step=(
                "Continue from Memory search or create a replacement entry if needed."
                if action == "deleted"
                else "Open the landed memory entry or keep working from Memory."
            ),
            breadcrumbs=["Home", "Recall", "Memory"],
            tone=tone,
            working_set=working_set,
        ),
        undo_action=None,
        rerun_action=None,
        resume_location=resume_location,
        grounded_chat_location=None,
        workflow_thread=_mutation_workflow_thread(
            thread_id=f"recall:memory:{action}:{int(payload['id'])}",
            title=title,
            summary=summary,
        ),
        working_set_id=working_set_id,
    )


def build_ingest_follow_through(
    *,
    paths: list[str],
    mode: str,
    recursive: bool,
    result: IngestResponse | dict[str, Any],
    query: str | None,
    working_set: dict[str, Any] | None,
) -> ReviewFollowThroughResponse:
    """Build one landed follow-through contract for a knowledge-ingest mutation."""
    payload = _mapping(result)
    files = int(payload.get("files") or 0)
    chunks = int(payload.get("chunks") or 0)
    failed_files = payload.get("failed_files") or []
    failed_count = len(failed_files) if isinstance(failed_files, list) else 0
    knowledge_label = _knowledge_label(paths)
    title_prefix = (
        "Rebuilt"
        if mode == "reindex"
        else "Purged"
        if mode == "purge"
        else "Synced"
        if mode == "sync"
        else "Indexed"
    )
    title = f"{title_prefix} knowledge · {knowledge_label}"
    summary = (
        f"Indexed {files} files into {chunks} chunks with {failed_count} failures."
        if failed_count > 0
        else f"Indexed {files} files into {chunks} chunks."
    )
    working_set_id = _working_set_id(working_set)
    preview_value = " · ".join(_truncate(path.strip(), 48) for path in paths[:2] if path.strip())
    if len([path for path in paths if path.strip()]) > 2:
        preview_value = f"{preview_value} · +{len(paths) - 2} more"
    if not preview_value:
        preview_value = knowledge_label
    return ReviewFollowThroughResponse(
        display_card=_receipt_card(
            eyebrow="Recall receipt",
            title=title,
            summary=summary,
            rationale=(
                "Knowledge ingestion should land as a resumable outcome so the operator can "
                "reopen Documents from the indexed result instead of reconstructing the next "
                "step from a toast."
            ),
            preview=[
                ContinuityDisplayPreviewItemResponse(
                    label=_knowledge_preview_label(paths),
                    value=preview_value,
                ),
                ContinuityDisplayPreviewItemResponse(label="Files", value=str(files)),
                ContinuityDisplayPreviewItemResponse(label="Chunks", value=str(chunks)),
            ],
            context_sources=["Indexed local documents"],
            confidence_label=(
                "Mutation applied with follow-up required"
                if failed_count > 0
                else "Mutation applied"
            ),
            rollback_label=(
                "Reindex with a corrected path or ingestion mode if this document set is not "
                "the one you intended."
            ),
            next_step=(
                "Ask a document-backed question or refine the ingest path if the indexed set "
                "is incomplete."
            ),
            breadcrumbs=["Home", "Recall", "Documents"],
            tone="attention" if failed_count > 0 else "progress",
            working_set=working_set,
        ),
        undo_action=None,
        rerun_action=None,
        resume_location=_recall_location(
            recall_tool="rag",
            query=query,
            working_set_id=working_set_id,
        ),
        grounded_chat_location=None,
        workflow_thread=_mutation_workflow_thread(
            thread_id="recall:rag:ingest:"
            + "|".join(path.strip().lower() for path in paths if path.strip()),
            title=title,
            summary=summary,
        ),
        working_set_id=working_set_id,
    )


__all__ = [
    "build_chat_follow_through",
    "build_ingest_follow_through",
    "build_memory_follow_through",
    "build_rag_follow_through",
]
