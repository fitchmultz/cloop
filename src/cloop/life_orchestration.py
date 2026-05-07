"""AI-orchestrated Cloop Life product layer.

Purpose:
    Run the Life feed through the pi organizer as a structured loop-closing
    agent, then apply validated loop and memory mutations through canonical
    services.

Responsibilities:
    - Build grounded Life context from current loops and durable memory
    - Ask the organizer model to classify the message and return a JSON plan
    - Validate the agent plan before mutating local state
    - Persist agent-planned captures, duplicate-aware updates, preference memory,
      cleanup, resurfacing groups, and undo handles through shared service boundaries

Non-scope:
    - Direct provider SDK calls outside the existing pi bridge
    - UI rendering or transport exception mapping
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic import ValidationError as PydanticValidationError

from . import memory_management
from .chat_orchestration import build_memory_context
from .llm import chat_completion
from .loops import duplicates as loop_duplicates
from .loops import read_service, repo, service
from .loops.capture_orchestration import (
    CaptureFieldInputs,
    CaptureOrchestrationInput,
    CaptureStatusFlags,
    orchestrate_capture,
)
from .loops.errors import ValidationError
from .loops.json_extraction import extract_first_json_object
from .loops.models import (
    LoopStatus,
    format_utc_datetime,
    parse_client_datetime,
    parse_utc_datetime,
    utc_now,
)
from .schemas.life import (
    LifeClarification,
    LifeClarificationAnswer,
    LifeCleanupBucket,
    LifeCleanupPlan,
    LifeExternalInput,
    LifeGroupName,
    LifeLoopGroup,
    LifeLoopItem,
    LifeMessageResponse,
    LifePreparedAction,
    LifeState,
    LifeUndoHandle,
)
from .schemas.loops import LoopResponse
from .schemas.memory import MemoryCategory, MemoryResponse, MemorySource
from .settings import PiToolBudgetSurface, Settings

_AgentActionRisk = Literal[
    "safe_internal",
    "reversible_internal",
    "external_low",
    "consequential",
]
_AgentApprovalBasis = Literal[
    "low_risk_reversible",
    "explicit_user_request",
    "remembered_preference",
    "review_only",
]
_LifeInteractionSource = Literal["user", "background"]
_OPEN_STATUSES = (
    LoopStatus.INBOX,
    LoopStatus.ACTIONABLE,
    LoopStatus.BLOCKED,
    LoopStatus.SCHEDULED,
)
_HISTORY_STATUSES = (LoopStatus.COMPLETED, LoopStatus.DROPPED)
_STATUS_CHANGING_CLEANUP_ACTIONS = {
    "complete",
    "archive",
    "abandon",
    "reschedule",
    "mark_waiting",
    "mark_active",
    "delegate",
    "update_priority",
}
_MUTABLE_LOOP_FIELDS = {
    "title",
    "summary",
    "definition_of_done",
    "next_action",
    "due_date",
    "due_at_utc",
    "snooze_until_utc",
    "time_minutes",
    "activation_energy",
    "urgency",
    "importance",
    "emotional_weight",
    "confidence",
    "project",
    "blocked_reason",
    "completion_note",
    "parent_loop_id",
    "tags",
}


class _AgentCapture(BaseModel):
    raw_text: str = Field(..., min_length=1)
    title: str | None = None
    summary: str | None = None
    life_state: LifeState
    loop_status: LoopStatus
    next_action: str | None = None
    prepared_actions: list[LifePreparedAction] = Field(default_factory=list)
    due_date: str | None = None
    due_at_utc: str | None = None
    time_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    activation_energy: int | None = Field(default=None, ge=0, le=3)
    urgency: float | None = Field(default=None, ge=0, le=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    emotional_weight: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    blocked_reason: str | None = None
    project: str | None = None
    tags: list[str] = Field(default_factory=list)
    duplicate_of_loop_id: int | None = Field(default=None, ge=1)
    parent_loop_id: int | None = Field(default=None, ge=1)
    related_loop_ids: list[int] = Field(default_factory=list)
    relationship_type: Literal["related", "duplicate"] = "related"
    relationship_confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: str | None = None
    group_names: list[LifeGroupName] = Field(default_factory=list)
    source_evidence: list[str] = Field(default_factory=list)


class _AgentUpdate(BaseModel):
    loop_id: int = Field(..., ge=1)
    fields: dict[str, Any] = Field(default_factory=dict)
    life_state: LifeState
    loop_status: LoopStatus
    rationale: str | None = None
    prepared_next_action: str | None = None
    prepared_actions: list[LifePreparedAction] = Field(default_factory=list)
    related_loop_ids: list[int] = Field(default_factory=list)
    relationship_type: Literal["related", "duplicate"] = "related"
    relationship_confidence: float | None = Field(default=None, ge=0, le=1)
    group_names: list[LifeGroupName] = Field(default_factory=list)
    source_evidence: list[str] = Field(default_factory=list)


class _AgentMemory(BaseModel):
    content: str = Field(..., min_length=1)
    key: str | None = None
    category: Literal["preference", "pattern", "context", "person", "event"] = "preference"
    memory_layer: Literal["active", "warm", "cold"] = "warm"
    priority: int = Field(default=80, ge=1, le=100)
    source: Literal["user_stated", "inferred"] = "user_stated"


class _AgentMemoryUpdate(BaseModel):
    memory_id: int = Field(..., ge=1)
    action: Literal["promote_active", "demote_warm", "archive_cold", "compress", "update", "delete"]
    rationale: str
    apply_now: bool = False
    risk_level: _AgentActionRisk = "safe_internal"
    approval_basis: _AgentApprovalBasis = "low_risk_reversible"
    content: str | None = None
    key: str | None = None
    category: Literal["preference", "pattern", "context", "person", "event"] | None = None
    priority: int | None = Field(default=None, ge=1, le=100)
    memory_layer: Literal["active", "warm", "cold"] | None = None

    @model_validator(mode="after")
    def require_agent_chosen_layer_for_layer_moves(self) -> "_AgentMemoryUpdate":
        if (
            self.action in {"promote_active", "demote_warm", "archive_cold"}
            and self.memory_layer is None
        ):
            raise ValueError(
                "memory_layer is required when the Life agent moves memory between layers"
            )
        return self


class _AgentClarification(BaseModel):
    question: str = Field(..., min_length=1)
    loop_id: int | None = Field(default=None, ge=1)
    capture_index: int | None = Field(default=None, ge=0)
    assumption: str | None = None
    rationale: str | None = None
    improves: list[
        Literal[
            "urgency",
            "effort",
            "related_context",
            "location",
            "deadline",
            "next_action",
            "autonomy_policy",
            "risk",
        ]
    ] = Field(default_factory=list)


class _AgentClarificationAnswer(BaseModel):
    clarification_id: int = Field(..., ge=1)
    loop_id: int = Field(..., ge=1)
    answer: str = Field(..., min_length=1)
    rationale: str | None = None


class _AgentCleanupAction(BaseModel):
    loop_id: int = Field(..., ge=1)
    action: Literal[
        "complete",
        "archive",
        "abandon",
        "delete",
        "keep",
        "review",
        "reschedule",
        "mark_waiting",
        "mark_active",
        "update_priority",
        "merge",
        "delegate",
        "add_dependency",
        "remove_dependency",
    ]
    rationale: str
    cleanup_bucket: LifeCleanupBucket | None = None
    result_life_state: LifeState
    target_loop_status: LoopStatus | None = None
    apply_now: bool = False
    risk_level: _AgentActionRisk = "reversible_internal"
    approval_basis: _AgentApprovalBasis = "low_risk_reversible"
    target_loop_id: int | None = Field(default=None, ge=1)
    field_overrides: dict[str, str | None] = Field(default_factory=dict)
    note: str | None = None
    snooze_until_utc: str | None = None
    due_date: str | None = None
    due_at_utc: str | None = None
    blocked_reason: str | None = None
    delegated_to: str | None = None
    urgency: float | None = Field(default=None, ge=0, le=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    emotional_weight: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    next_action: str | None = None


class _AgentGroupItem(BaseModel):
    loop_id: int = Field(..., ge=1)
    life_state: LifeState
    rationale: str | None = None
    prepared_next_action: str | None = None
    prepared_actions: list[LifePreparedAction] = Field(default_factory=list)


class _AgentGroup(BaseModel):
    name: LifeGroupName
    title: str
    summary: str
    items: list[_AgentGroupItem] = Field(default_factory=list)


class _LifeAgentDecision(BaseModel):
    mode: Literal["capture", "cleanup", "resurface", "preference"]
    reply: str
    notify_user: bool = False
    notification_title: str | None = None
    notification_body: str | None = None
    captures: list[_AgentCapture] = Field(default_factory=list)
    updates: list[_AgentUpdate] = Field(default_factory=list)
    memories: list[_AgentMemory] = Field(default_factory=list)
    memory_updates: list[_AgentMemoryUpdate] = Field(default_factory=list)
    clarifications: list[_AgentClarification] = Field(default_factory=list)
    clarification_answers: list[_AgentClarificationAnswer] = Field(default_factory=list)
    cleanup_actions: list[_AgentCleanupAction] = Field(default_factory=list)
    groups: list[_AgentGroup] = Field(default_factory=list)


def _parse_optional_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return parse_utc_datetime(value)
    return None


def _age_days(*, now: datetime, value: Any) -> float | None:
    parsed = _parse_optional_utc(value)
    if parsed is None:
        return None
    return round(max((now - parsed).total_seconds(), 0) / 86400, 1)


def _life_signals(
    *,
    loop: Mapping[str, Any],
    now: datetime,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    events = repo.list_loop_events_paginated(loop_id=int(loop["id"]), limit=25, conn=conn)
    update_events = [event for event in events if event.get("event_type") == "update"]
    resurface_events = [event for event in events if event.get("event_type") == "life_resurfaced"]
    life_touch_events = [event for event in events if event.get("event_type") == "life_touched"]
    user_touch_events = [
        event for event in events if event.get("event_type") == "life_user_touched"
    ]
    deferral_events = []
    for event in update_events:
        try:
            payload = json.loads(str(event.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            payload = {}
        fields = payload.get("fields") if isinstance(payload, dict) else None
        if isinstance(fields, dict) and fields.get("snooze_until_utc"):
            deferral_events.append(event)

    updated_age_days = _age_days(now=now, value=loop.get("updated_at_utc"))
    captured_age_days = _age_days(now=now, value=loop.get("captured_at_utc"))
    status = str(loop.get("status") or "")
    snooze_until = _parse_optional_utc(loop.get("snooze_until_utc"))
    snooze_seconds_remaining = (
        round(max((snooze_until - now).total_seconds(), 0)) if snooze_until is not None else None
    )
    dependency_loop_ids = repo.list_dependencies(loop_id=int(loop["id"]), conn=conn)
    blocking_loop_ids = repo.list_dependents(loop_id=int(loop["id"]), conn=conn)

    return {
        "age_days": captured_age_days,
        "days_since_update": updated_age_days,
        "stored_confidence": loop.get("confidence"),
        "has_next_action": bool(str(loop.get("next_action") or "").strip()),
        "status": status,
        "snooze_until_utc": loop.get("snooze_until_utc"),
        "snooze_seconds_remaining": snooze_seconds_remaining,
        "deferral_count": len(deferral_events),
        "update_count": len(update_events),
        "resurfaced_count": len(resurface_events),
        "last_event_utc": events[0].get("created_at") if events else None,
        "last_agent_touch_utc": (
            life_touch_events[0].get("created_at") if life_touch_events else None
        ),
        "last_user_touch_utc": (
            user_touch_events[0].get("created_at") if user_touch_events else None
        ),
        "days_since_user_touch": (
            _age_days(now=now, value=user_touch_events[0].get("created_at"))
            if user_touch_events
            else None
        ),
        "last_resurfaced_utc": resurface_events[0].get("created_at") if resurface_events else None,
        "last_deferred_utc": deferral_events[0].get("created_at") if deferral_events else None,
        "days_since_resurfaced": (
            _age_days(now=now, value=resurface_events[0].get("created_at"))
            if resurface_events
            else None
        ),
        "recent_event_types": [str(event.get("event_type")) for event in events[:5]],
        "dependency_loop_ids": dependency_loop_ids,
        "blocking_loop_ids": blocking_loop_ids,
        "has_open_dependencies": repo.has_open_dependencies(loop_id=int(loop["id"]), conn=conn),
    }


def _loop_signals_for(
    *,
    loops: Sequence[Mapping[str, Any]],
    now: datetime,
    conn: sqlite3.Connection,
) -> dict[int, dict[str, Any]]:
    return {int(loop["id"]): _life_signals(loop=loop, now=now, conn=conn) for loop in loops}


def _clarifications_for_loops(
    *,
    loop_ids: Sequence[int],
    conn: sqlite3.Connection,
) -> dict[int, list[dict[str, Any]]]:
    clarifications = repo.list_loop_clarifications_for_loops(loop_ids=loop_ids, conn=conn)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for clarification in clarifications:
        grouped.setdefault(int(clarification["loop_id"]), []).append(dict(clarification))
    return grouped


def _life_memory_entries(
    *,
    settings: Settings,
    conn: sqlite3.Connection,
    limit: int = 24,
) -> list[dict[str, Any]]:
    result = memory_management.list_memory_entries(
        limit=limit,
        settings=settings,
        conn=conn,
    )
    entries = result.get("items", [])
    compact: list[dict[str, Any]] = []
    for entry in entries:
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), Mapping) else {}
        compact.append(
            {
                "id": int(entry["id"]),
                "key": entry.get("key"),
                "content": str(entry.get("content") or "")[:400],
                "category": entry.get("category"),
                "priority": entry.get("priority"),
                "source": entry.get("source"),
                "life_layer": str(metadata.get("life_layer") or "warm"),
                "metadata": {
                    key: value
                    for key, value in dict(metadata).items()
                    if key in {"life_layer", "surface", "created_by", "updated_by"}
                },
            }
        )
    return compact


def _compact_loop(
    loop: Mapping[str, Any],
    *,
    life_signals: Mapping[str, Any] | None = None,
    clarifications: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "id": int(loop["id"]),
        "title": loop.get("title"),
        "raw_text": loop.get("raw_text"),
        "summary": loop.get("summary"),
        "next_action": loop.get("next_action"),
        "status": loop.get("status"),
        "due_date": loop.get("due_date"),
        "due_at_utc": loop.get("due_at_utc"),
        "snooze_until_utc": loop.get("snooze_until_utc"),
        "time_minutes": loop.get("time_minutes"),
        "activation_energy": loop.get("activation_energy"),
        "urgency": loop.get("urgency"),
        "importance": loop.get("importance"),
        "emotional_weight": loop.get("emotional_weight"),
        "confidence": loop.get("confidence"),
        "project": loop.get("project"),
        "tags": list(loop.get("tags") or []),
        "blocked_reason": loop.get("blocked_reason"),
        "captured_at_utc": loop.get("captured_at_utc"),
        "updated_at_utc": loop.get("updated_at_utc"),
        "life_signals": dict(life_signals or {}),
        "pending_clarifications": [
            {
                "id": int(clarification["id"]),
                "question": clarification.get("question"),
                "created_at": clarification.get("created_at"),
            }
            for clarification in clarifications
            if clarification.get("answer") is None
        ],
        "answered_clarifications": [
            {
                "id": int(clarification["id"]),
                "question": clarification.get("question"),
                "answer": clarification.get("answer"),
                "answered_at": clarification.get("answered_at"),
            }
            for clarification in clarifications
            if clarification.get("answer") is not None
        ][:3],
    }


def _life_state(loop: Mapping[str, Any]) -> LifeState:
    status = str(loop.get("status") or "")
    if status == LoopStatus.INBOX.value:
        return "captured"
    if status == LoopStatus.ACTIONABLE.value:
        return "active"
    if status == LoopStatus.BLOCKED.value:
        return "waiting"
    if status == LoopStatus.SCHEDULED.value:
        return "scheduled"
    if status == LoopStatus.COMPLETED.value:
        return "completed"
    if status == LoopStatus.DROPPED.value:
        completion_note = str(loop.get("completion_note") or "").lower()
        if "abandon" in completion_note or "no longer matters" in completion_note:
            return "abandoned"
        return "archived"
    return "captured"


def _loop_item(
    loop: Mapping[str, Any],
    *,
    rationale: str | None = None,
    prepared_next_action: str | None = None,
    prepared_actions: Sequence[LifePreparedAction] = (),
    life_state: LifeState | None = None,
) -> LifeLoopItem:
    return LifeLoopItem(
        loop=LoopResponse(**loop),
        life_state=life_state or _life_state(loop),
        rationale=rationale,
        prepared_next_action=prepared_next_action or loop.get("next_action"),
        prepared_actions=list(prepared_actions),
    )


def _open_loops(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return read_service.list_loops_by_statuses(
        statuses=list(_OPEN_STATUSES),
        limit=200,
        offset=0,
        conn=conn,
    )


def _history_loops(*, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return read_service.list_loops_by_statuses(
        statuses=list(_HISTORY_STATUSES),
        limit=50,
        offset=0,
        conn=conn,
    )


def _agent_schema_description() -> dict[str, Any]:
    return {
        "mode": "capture | cleanup | resurface | preference",
        "reply": "direct, plain-language user reply; no generic AI phrasing",
        "notify_user": ("true only when a background pass should interrupt the user with a digest"),
        "notification_title": "short push title when notify_user is true",
        "notification_body": "short push body when notify_user is true",
        "captures": [
            {
                "raw_text": "one unresolved intent extracted from the user message",
                "title": "short user-facing title",
                "summary": "useful context to preserve",
                "life_state": (
                    "captured | active | needs_clarification | prepared | scheduled | "
                    "waiting | blocked | stale"
                ),
                "loop_status": (
                    "canonical persisted loop status you choose: inbox | actionable | "
                    "blocked | scheduled | completed | dropped"
                ),
                "next_action": "small prepared next action when useful",
                "prepared_actions": [
                    {
                        "kind": (
                            "email_draft | text_draft | call_script | checklist | "
                            "application_checklist | decision_brief | "
                            "decision_recommendation | errand_plan | appointment_prep | "
                            "product_shortlist | route_suggestion | first_10_minutes | summary"
                        ),
                        "title": "plain title for the prepared artifact",
                        "body": "draft/script/checklist/brief text ready for review",
                        "risk_level": "internal | external_low | consequential",
                        "requires_approval": "true for drafts that leave the app",
                    }
                ],
                "time_minutes": "estimated effort in minutes, optional",
                "activation_energy": "0-3, optional",
                "urgency": "0-1, optional",
                "importance": "0-1, optional",
                "emotional_weight": "0-1 emotional load estimate, optional",
                "confidence": "0-1 confidence in extracted loop meaning, optional",
                "tags": ["life", "optional-category"],
                "duplicate_of_loop_id": "existing open loop id when this updates a current loop",
                "parent_loop_id": "existing loop id when this is a smaller split step",
                "related_loop_ids": "existing loop ids this new/updated loop should be linked to",
                "relationship_type": "related | duplicate",
                "relationship_confidence": "0-1 confidence, optional",
                "rationale": "why this is a loop or update",
                "group_names": "names of groups this new capture should appear in",
                "source_evidence": (
                    "labels or URLs from external_inputs that materially support this loop"
                ),
            }
        ],
        "updates": [
            {
                "loop_id": "existing loop id",
                "fields": {
                    "title": "optional",
                    "summary": "optional",
                    "next_action": "optional",
                    "parent_loop_id": "optional existing parent loop id for split steps",
                    "time_minutes": "optional",
                    "activation_energy": "optional",
                    "urgency": "optional",
                    "importance": "optional",
                    "emotional_weight": "optional",
                    "confidence": "optional",
                    "tags": "optional list",
                },
                "life_state": (
                    "captured | active | needs_clarification | prepared | scheduled | "
                    "waiting | blocked | stale, optional"
                ),
                "loop_status": (
                    "canonical persisted loop status you choose: inbox | actionable | "
                    "blocked | scheduled | completed | dropped"
                ),
                "rationale": "why this updates that loop",
                "prepared_next_action": "optional display action",
                "prepared_actions": "optional list of drafted scripts, checklists, or briefs",
                "related_loop_ids": "existing loop ids this loop should be linked to",
                "relationship_type": "related | duplicate",
                "relationship_confidence": "0-1 confidence, optional",
                "group_names": "names of groups this update should appear in",
                "source_evidence": (
                    "labels or URLs from external_inputs that materially support this update"
                ),
            }
        ],
        "memories": [
            {
                "content": "durable stated preference or observed pattern",
                "key": "life.preference.optional",
                "category": "preference | pattern | context | person | event",
                "memory_layer": "active | warm | cold",
                "priority": 80,
                "source": "user_stated | inferred",
            }
        ],
        "memory_updates": [
            {
                "memory_id": "existing memory id from memory_entries",
                "action": (
                    "promote_active | demote_warm | archive_cold | compress | update | delete"
                ),
                "rationale": "why this memory should move, compress, update, or be removed",
                "apply_now": "true only when delegated authority allows it",
                "risk_level": "safe_internal | reversible_internal | external_low | consequential",
                "approval_basis": (
                    "low_risk_reversible | explicit_user_request | "
                    "remembered_preference | review_only"
                ),
                "content": "new compressed or corrected memory content",
                "key": "optional updated key",
                "category": "preference | pattern | context | person | event, optional",
                "priority": "1-100 optional",
                "memory_layer": (
                    "active | warm | cold; required for promote_active, demote_warm, "
                    "or archive_cold because you choose the target layer"
                ),
            }
        ],
        "clarifications": [
            {
                "question": "short optional question only when it materially improves the loop",
                "loop_id": "existing known loop id when asking about an existing loop",
                "capture_index": (
                    "0-based index into captures when asking about a loop you just captured"
                ),
                "assumption": "optional default assumption you will use unless corrected",
                "rationale": "why this question is worth asking",
                "improves": [
                    (
                        "urgency | effort | related_context | location | deadline | "
                        "next_action | autonomy_policy | risk"
                    )
                ],
            }
        ],
        "clarification_answers": [
            {
                "clarification_id": "existing pending clarification id from open_loops",
                "loop_id": "loop id that owns the clarification",
                "answer": "the user's answer to record",
                "rationale": "why this message answers that clarification",
            }
        ],
        "cleanup_actions": [
            {
                "loop_id": "existing loop id",
                "action": (
                    "complete | archive | abandon | delete | keep | review | "
                    "reschedule | mark_waiting | mark_active | update_priority | merge | "
                    "delegate | add_dependency | remove_dependency"
                ),
                "rationale": "why",
                "cleanup_bucket": (
                    "close_candidate | archive_candidate | keep_active | review_needed; "
                    "you choose the user-facing cleanup bucket, do not rely on the action name"
                ),
                "result_life_state": (
                    "captured | active | needs_clarification | prepared | scheduled | "
                    "waiting | blocked | stale | completed | archived | abandoned | deleted"
                ),
                "target_loop_status": (
                    "canonical persisted loop status after this cleanup action when status "
                    "should change: inbox | actionable | blocked | scheduled | completed | dropped"
                ),
                "apply_now": "true only when delegated authority allows it",
                "risk_level": "safe_internal | reversible_internal | external_low | consequential",
                "approval_basis": (
                    "low_risk_reversible | explicit_user_request | "
                    "remembered_preference | review_only"
                ),
                "target_loop_id": (
                    "required for merge or dependency actions; merge target is survivor, "
                    "dependency target is the blocker loop"
                ),
                "field_overrides": "optional merge conflict values for title/summary/next_action",
                "note": "optional status note",
                "snooze_until_utc": "optional for reschedule",
                "due_date": "optional for reschedule",
                "due_at_utc": "optional for reschedule",
                "blocked_reason": "optional for mark_waiting",
                "delegated_to": "optional person/context for delegate",
                "urgency": "optional for update_priority",
                "importance": "optional for update_priority",
                "emotional_weight": "optional for update_priority",
                "confidence": "optional confidence update",
                "next_action": "optional prepared next action update",
            }
        ],
        "groups": [
            {
                "name": (
                    "needs_attention_today | quick_wins | waiting_on_someone | "
                    "prepared_for_review | stale_needs_decision | upcoming | "
                    "ideas_not_tasks | history"
                ),
                "title": "plain title",
                "summary": "plain summary",
                "items": [
                    {
                        "loop_id": "known loop id from context",
                        "life_state": "your display state for this loop",
                        "rationale": "why this loop is in this group",
                        "prepared_next_action": "optional display action",
                        "prepared_actions": "optional prepared drafts/checklists/briefs",
                    }
                ],
            }
        ],
    }


def _build_agent_messages(
    *,
    message: str,
    captured_at_iso: str,
    client_tz_offset_min: int,
    open_loops: Sequence[Mapping[str, Any]],
    history_loops: Sequence[Mapping[str, Any]],
    open_loop_signals: Mapping[int, Mapping[str, Any]],
    history_loop_signals: Mapping[int, Mapping[str, Any]],
    loop_clarifications: Mapping[int, Sequence[Mapping[str, Any]]],
    memory_context: str,
    memory_entries: Sequence[Mapping[str, Any]],
    memory_entries_used: int,
    interaction_source: _LifeInteractionSource,
    external_inputs: Sequence[LifeExternalInput] = (),
) -> list[dict[str, str]]:
    payload = {
        "user_message": message,
        "captured_at": captured_at_iso,
        "client_tz_offset_min": client_tz_offset_min,
        "interaction_source": interaction_source,
        "external_inputs": [
            item.model_dump(mode="json", exclude_none=True) for item in external_inputs
        ],
        "open_loops": [
            _compact_loop(
                loop,
                life_signals=open_loop_signals.get(int(loop["id"])),
                clarifications=loop_clarifications.get(int(loop["id"]), ()),
            )
            for loop in open_loops
        ],
        "recent_history": [
            _compact_loop(
                loop,
                life_signals=history_loop_signals.get(int(loop["id"])),
                clarifications=loop_clarifications.get(int(loop["id"]), ()),
            )
            for loop in history_loops[:20]
        ],
        "memory_entries_used": memory_entries_used,
        "memory_context": memory_context,
        "memory_entries": [dict(entry) for entry in memory_entries],
    }
    return [
        {
            "role": "system",
            "content": (
                "You are Cloop Life, a local-first loop-closing agent. "
                "Your job is to reduce mental load by interpreting messy human input into "
                "structured loops, updates, cleanup recommendations, preference memory, and "
                "resurfacing groups. Return only JSON. Do the human judgment here: split "
                "messy dumps, detect likely duplicates from open_loops, prepare smallest "
                "next actions, decide what is stale or low-risk, and preserve useful context. "
                "Treat external_inputs as raw source evidence for this turn: screenshots, "
                "photos, links, audio, files, or pasted snippets may support captures or "
                "updates, but you decide what they mean. Preserve useful source labels in "
                "source_evidence on captures and updates. "
                "Use life_signals only as raw factual evidence: timestamps, counts, current "
                "fields, snooze timing, dependency IDs, and recent loop history. You decide "
                "whether those facts mean stale, avoided, low-risk, emotionally heavy, "
                "duplicated, unclear, or worth surfacing. The Python layer must not make "
                "that judgment for you. "
                "When a background pass should notify the user, set notify_user true and "
                "write notification_title and notification_body yourself; otherwise leave "
                "notify_user false even if you changed memory or loops. "
                "When grouping loops, put every visible group in groups with your own "
                "title, summary, and item-level life_state/rationale. "
                "For captures and updates, choose both life_state and loop_status yourself. "
                "For cleanup actions that change status, choose target_loop_status yourself. "
                "Python validates and persists those choices; it must not infer lifecycle "
                "meaning from hardcoded mappings. "
                "Use preference and pattern memory to adapt tone, reminder style, cleanup "
                "aggressiveness, and autonomy policy without exposing memory mechanics. "
                "For every cleanup_actions or memory_updates entry, include risk_level and "
                "approval_basis. For memory layer changes, choose memory_layer explicitly. "
                "Set review_only when the action should be shown but not applied. "
                "Ask clarifications only when the answer would materially improve urgency, "
                "effort, related context, location, deadline, next action, autonomy policy, "
                "or risk. Clarifications are optional; never turn Life into a blocking wizard. "
                "If the user answers a pending_clarifications item, record it in "
                "clarification_answers and update the loop or memory with the new context. "
                "Do not expose agent architecture. Do not invent loop IDs. Do not mark "
                "consequential actions apply_now unless the message or memory clearly delegates "
                "that exact class of cleanup and the action is reversible or reviewable. "
                "For delete, set apply_now true only when the user explicitly asks to delete "
                "a specific known loop; never infer deletion from staleness. Prefer direct wording."
            ),
        },
        {"role": "user", "content": json.dumps(payload)},
        {"role": "system", "content": json.dumps(_agent_schema_description())},
    ]


def _run_life_agent(
    *,
    message: str,
    captured_at_iso: str,
    client_tz_offset_min: int,
    conn: sqlite3.Connection,
    settings: Settings,
    interaction_source: _LifeInteractionSource,
    external_inputs: Sequence[LifeExternalInput] = (),
) -> tuple[_LifeAgentDecision, dict[str, Any]]:
    open_items = _open_loops(conn=conn)
    history_items = _history_loops(conn=conn)
    now = parse_utc_datetime(captured_at_iso)
    open_loop_signals = _loop_signals_for(
        loops=open_items,
        now=now,
        conn=conn,
    )
    history_loop_signals = _loop_signals_for(
        loops=history_items,
        now=now,
        conn=conn,
    )
    loop_clarifications = _clarifications_for_loops(
        loop_ids=[int(loop["id"]) for loop in [*open_items, *history_items]],
        conn=conn,
    )
    memory_result = build_memory_context(settings, limit=12)
    memory_entries = _life_memory_entries(settings=settings, conn=conn)
    messages = _build_agent_messages(
        message=message,
        captured_at_iso=captured_at_iso,
        client_tz_offset_min=client_tz_offset_min,
        open_loops=open_items,
        history_loops=history_items,
        open_loop_signals=open_loop_signals,
        history_loop_signals=history_loop_signals,
        loop_clarifications=loop_clarifications,
        memory_context=memory_result.content,
        memory_entries=memory_entries,
        memory_entries_used=memory_result.entry_count,
        interaction_source=interaction_source,
        external_inputs=external_inputs,
    )
    content, metadata = chat_completion(
        messages,
        surface=PiToolBudgetSurface.ENRICHMENT,
        settings=settings,
        selector_role="organizer",
        thinking_level=settings.pi_organizer_thinking_level,
        timeout_s=settings.pi_organizer_timeout,
    )
    raw_json = extract_first_json_object(content, allow_markdown_fence=True)
    if raw_json is None:
        raise ValidationError("life_agent_response", "organizer returned no JSON object")
    try:
        decision = _LifeAgentDecision.model_validate(raw_json)
    except PydanticValidationError as exc:
        raise ValidationError("life_agent_response", f"invalid organizer response: {exc}") from exc
    return decision, {
        "agent_metadata": metadata,
        "agent_context": {
            "open_loop_count": len(open_items),
            "history_loop_count": len(history_items),
            "memory_entries_used": memory_result.entry_count,
            "memory_entries_available": len(memory_entries),
            "external_input_count": len(external_inputs),
        },
    }


def _status_flags(loop_status: LoopStatus) -> CaptureStatusFlags:
    return CaptureStatusFlags(
        actionable=loop_status is LoopStatus.ACTIONABLE,
        blocked=loop_status is LoopStatus.BLOCKED,
        scheduled=loop_status is LoopStatus.SCHEDULED,
    )


def _source_evidence_items(
    *,
    labels_or_urls: Sequence[str],
    external_inputs: Sequence[LifeExternalInput],
) -> list[dict[str, Any]]:
    requested = {item.strip() for item in labels_or_urls if item.strip()}
    if not requested:
        return []
    matched: list[dict[str, Any]] = []
    for item in external_inputs:
        label = item.label.strip()
        source_url = item.source_url.strip() if item.source_url else ""
        if label not in requested and (not source_url or source_url not in requested):
            continue
        matched.append(item.model_dump(mode="json", exclude_none=True))
    return matched


def _attach_source_evidence(
    *,
    loop: Mapping[str, Any],
    labels_or_urls: Sequence[str],
    external_inputs: Sequence[LifeExternalInput],
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    source_evidence = _source_evidence_items(
        labels_or_urls=labels_or_urls,
        external_inputs=external_inputs,
    )
    if not source_evidence:
        return dict(loop)

    provenance = dict(loop.get("provenance") or {})
    existing = provenance.get("life_source_evidence")
    evidence_list = list(existing) if isinstance(existing, list) else []
    seen = {json.dumps(item, sort_keys=True) for item in evidence_list if isinstance(item, Mapping)}
    for item in source_evidence:
        key = json.dumps(item, sort_keys=True)
        if key in seen:
            continue
        evidence_list.append(item)
        seen.add(key)
    provenance["life_source_evidence"] = evidence_list[-20:]
    updated = service.update_loop(
        loop_id=int(loop["id"]),
        fields={"provenance_json": json.dumps(provenance)},
        conn=conn,
    )
    repo.insert_loop_event(
        loop_id=int(loop["id"]),
        event_type="life_source_evidence_attached",
        payload={"source_evidence": source_evidence},
        conn=conn,
    )
    return updated


def _sanitize_update_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in _MUTABLE_LOOP_FIELDS or value is None:
            continue
        if key == "tags":
            sanitized[key] = [str(tag) for tag in value if str(tag).strip()]
        else:
            sanitized[key] = value
    return sanitized


def _transition_if_needed(
    *,
    loop: Mapping[str, Any],
    loop_status: LoopStatus | None,
    conn: sqlite3.Connection,
    note: str | None = None,
) -> dict[str, Any]:
    if loop_status is None:
        return dict(loop)
    if str(loop.get("status")) == loop_status.value:
        return dict(loop)
    return service.transition_status(
        loop_id=int(loop["id"]),
        to_status=loop_status,
        note=note or "Updated by Life agent.",
        conn=conn,
    )


def _apply_update(
    *,
    loop_id: int,
    fields: Mapping[str, Any],
    loop_status: LoopStatus | None,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    updated: dict[str, Any]
    sanitized = _sanitize_update_fields(fields)
    if sanitized:
        updated = service.update_loop(loop_id=loop_id, fields=sanitized, conn=conn)
    else:
        loop = read_service.get_loop(loop_id=loop_id, conn=conn)
        updated = dict(loop)
    return _transition_if_needed(loop=updated, loop_status=loop_status, conn=conn)


def _capture_or_update(
    *,
    capture: _AgentCapture,
    captured_at_iso: str,
    client_tz_offset_min: int,
    known_loop_ids: set[int],
    conn: sqlite3.Connection,
    settings: Settings,
    external_inputs: Sequence[LifeExternalInput],
) -> tuple[LifeLoopItem, int]:
    if capture.parent_loop_id is not None and capture.parent_loop_id not in known_loop_ids:
        raise ValidationError(
            "parent_loop_id",
            f"unknown parent loop id from Life agent: {capture.parent_loop_id}",
        )
    if capture.duplicate_of_loop_id is not None:
        if capture.duplicate_of_loop_id not in known_loop_ids:
            raise ValidationError(
                "duplicate_of_loop_id",
                f"unknown loop id from Life agent: {capture.duplicate_of_loop_id}",
            )
        fields: dict[str, Any] = {
            "title": capture.title,
            "summary": capture.summary,
            "next_action": capture.next_action,
            "due_date": capture.due_date,
            "due_at_utc": capture.due_at_utc,
            "time_minutes": capture.time_minutes,
            "activation_energy": capture.activation_energy,
            "urgency": capture.urgency,
            "importance": capture.importance,
            "emotional_weight": capture.emotional_weight,
            "confidence": capture.confidence,
            "blocked_reason": capture.blocked_reason,
            "parent_loop_id": capture.parent_loop_id,
            "project": capture.project,
            "tags": capture.tags,
        }
        loop = _apply_update(
            loop_id=capture.duplicate_of_loop_id,
            fields=fields,
            loop_status=capture.loop_status,
            conn=conn,
        )
        loop = _attach_source_evidence(
            loop=loop,
            labels_or_urls=capture.source_evidence,
            external_inputs=external_inputs,
            conn=conn,
        )
        return (
            _loop_item(
                loop,
                rationale=capture.rationale or "Updated an existing loop.",
                prepared_next_action=capture.next_action,
                prepared_actions=capture.prepared_actions,
                life_state=capture.life_state,
            ),
            int(loop["id"]),
        )

    result = orchestrate_capture(
        input_data=CaptureOrchestrationInput(
            raw_text=capture.raw_text,
            captured_at_iso=captured_at_iso,
            client_tz_offset_min=client_tz_offset_min,
            status_flags=_status_flags(capture.loop_status),
            field_inputs=CaptureFieldInputs(
                activation_energy=capture.activation_energy,
                blocked_reason=capture.blocked_reason,
                confidence=capture.confidence,
                due_date=capture.due_date,
                due_at_utc=capture.due_at_utc,
                emotional_weight=capture.emotional_weight,
                urgency=capture.urgency,
                importance=capture.importance,
                next_action=capture.next_action,
                project=capture.project,
                tags=capture.tags or ["life"],
                time_minutes=capture.time_minutes,
            ),
        ),
        settings=settings,
        conn=conn,
    ).loop
    update_fields = _sanitize_update_fields(
        {
            "title": capture.title,
            "summary": capture.summary,
            "urgency": capture.urgency,
            "importance": capture.importance,
            "emotional_weight": capture.emotional_weight,
            "confidence": capture.confidence,
            "parent_loop_id": capture.parent_loop_id,
        }
    )
    loop = (
        service.update_loop(loop_id=int(result["id"]), fields=update_fields, conn=conn)
        if update_fields
        else result
    )
    loop = _attach_source_evidence(
        loop=loop,
        labels_or_urls=capture.source_evidence,
        external_inputs=external_inputs,
        conn=conn,
    )
    return (
        _loop_item(
            loop,
            rationale=capture.rationale or "Captured from your message.",
            prepared_next_action=capture.next_action,
            prepared_actions=capture.prepared_actions,
            life_state=capture.life_state,
        ),
        int(loop["id"]),
    )


def _apply_loop_links(
    *,
    loop_id: int,
    related_loop_ids: Sequence[int],
    relationship_type: Literal["related", "duplicate"],
    confidence: float | None,
    known_loop_ids: set[int],
    conn: sqlite3.Connection,
) -> int:
    linked_count = 0
    for related_loop_id in related_loop_ids:
        if related_loop_id == loop_id or related_loop_id not in known_loop_ids:
            continue
        repo.insert_loop_link(
            loop_id=loop_id,
            related_loop_id=related_loop_id,
            relationship_type=relationship_type,
            confidence=confidence,
            source="life_agent",
            conn=conn,
        )
        repo.insert_loop_link(
            loop_id=related_loop_id,
            related_loop_id=loop_id,
            relationship_type=relationship_type,
            confidence=confidence,
            source="life_agent",
            conn=conn,
        )
        linked_count += 1
    return linked_count


def _store_memory(
    *,
    memory: _AgentMemory,
    conn: sqlite3.Connection,
    settings: Settings,
) -> MemoryResponse:
    created = memory_management.create_memory_entry(
        payload={
            "key": memory.key or f"life.{memory.category}",
            "content": memory.content.strip(),
            "category": MemoryCategory(memory.category).value,
            "priority": memory.priority,
            "source": MemorySource(memory.source).value,
            "metadata": {
                "surface": "life",
                "created_by": "life_agent",
                "life_layer": memory.memory_layer,
            },
        },
        settings=settings,
        conn=conn,
    )
    return MemoryResponse(**created)


def _assert_agent_action_authority(
    *,
    field: str,
    risk_level: _AgentActionRisk,
    approval_basis: _AgentApprovalBasis,
) -> None:
    if risk_level == "consequential" and approval_basis not in {
        "explicit_user_request",
        "remembered_preference",
    }:
        raise ValidationError(
            field,
            "consequential Life agent actions require explicit or remembered delegated authority",
        )
    if risk_level == "external_low" and approval_basis == "review_only":
        raise ValidationError(
            field,
            "review-only Life agent actions may not be applied automatically",
        )


def _apply_memory_updates(
    *,
    decision: _LifeAgentDecision,
    known_memory_ids: set[int],
    message: str,
    conn: sqlite3.Connection,
    settings: Settings,
) -> tuple[list[MemoryResponse], int]:
    updated: list[MemoryResponse] = []
    deleted_count = 0
    for action in decision.memory_updates:
        if not action.apply_now:
            continue
        _assert_agent_action_authority(
            field="memory_updates.approval_basis",
            risk_level=action.risk_level,
            approval_basis=action.approval_basis,
        )
        if action.memory_id not in known_memory_ids:
            raise ValidationError(
                "memory_updates.memory_id",
                f"unknown memory id from Life agent: {action.memory_id}",
            )
        if action.action == "delete":
            if not any(token in message.lower() for token in ("delete", "forget", "remove")):
                raise ValidationError(
                    "memory_updates.delete",
                    "Life agent may only delete memory when the user explicitly asks",
                )
            memory_management.delete_memory_entry(
                entry_id=action.memory_id,
                settings=settings,
                conn=conn,
            )
            deleted_count += 1
            continue

        current = memory_management.get_memory_entry(
            entry_id=action.memory_id,
            settings=settings,
            conn=conn,
        )
        metadata = dict(current.get("metadata") or {})
        if action.memory_layer is not None:
            metadata["life_layer"] = action.memory_layer
        metadata.update(
            {
                "surface": "life",
                "updated_by": "life_agent",
                "life_update_action": action.action,
                "life_update_rationale": action.rationale,
            }
        )
        fields: dict[str, Any] = {"metadata": metadata}
        if action.content is not None:
            fields["content"] = action.content
        if action.key is not None:
            fields["key"] = action.key
        if action.category is not None:
            fields["category"] = MemoryCategory(action.category).value
        if action.priority is not None:
            fields["priority"] = action.priority
        changed = memory_management.update_memory_entry(
            entry_id=action.memory_id,
            fields=fields,
            settings=settings,
            conn=conn,
        )
        updated.append(MemoryResponse(**changed))
    return updated, deleted_count


def _apply_clarifications(
    *,
    decision: _LifeAgentDecision,
    known_loop_ids: set[int],
    capture_index_to_loop_id: Mapping[int, int],
    conn: sqlite3.Connection,
) -> list[LifeClarification]:
    clarifications: list[LifeClarification] = []
    for clarification in decision.clarifications:
        target_loop_id = clarification.loop_id
        if target_loop_id is None and clarification.capture_index is not None:
            target_loop_id = capture_index_to_loop_id.get(clarification.capture_index)
            if target_loop_id is None:
                raise ValidationError(
                    "clarifications.capture_index",
                    f"unknown capture index from Life agent: {clarification.capture_index}",
                )
        if target_loop_id is not None and target_loop_id not in known_loop_ids:
            raise ValidationError(
                "clarifications.loop_id",
                f"unknown loop id from Life agent: {target_loop_id}",
            )

        clarification_id = None
        if target_loop_id is not None:
            clarification_id = repo.insert_loop_clarification(
                loop_id=target_loop_id,
                question=clarification.question,
                conn=conn,
            )
            repo.insert_loop_event(
                loop_id=target_loop_id,
                event_type="life_clarification_requested",
                payload={
                    "clarification_id": clarification_id,
                    "question": clarification.question,
                    "assumption": clarification.assumption,
                    "rationale": clarification.rationale,
                    "improves": list(clarification.improves),
                },
                conn=conn,
            )

        clarifications.append(
            LifeClarification(
                question=clarification.question,
                loop_id=target_loop_id,
                clarification_id=clarification_id,
                assumption=clarification.assumption,
                rationale=clarification.rationale,
                improves=list(clarification.improves),
            )
        )
    return clarifications


def _apply_clarification_answers(
    *,
    decision: _LifeAgentDecision,
    known_loop_ids: set[int],
    conn: sqlite3.Connection,
) -> list[LifeClarificationAnswer]:
    answers: list[LifeClarificationAnswer] = []
    seen_ids: set[int] = set()
    for answer in decision.clarification_answers:
        if answer.loop_id not in known_loop_ids:
            raise ValidationError(
                "clarification_answers.loop_id",
                f"unknown loop id from Life agent: {answer.loop_id}",
            )
        if answer.clarification_id in seen_ids:
            raise ValidationError(
                "clarification_answers.clarification_id",
                f"duplicate clarification id from Life agent: {answer.clarification_id}",
            )
        seen_ids.add(answer.clarification_id)
        clarification = repo.read_loop_clarification(
            clarification_id=answer.clarification_id,
            conn=conn,
        )
        if clarification is None:
            raise ValidationError(
                "clarification_answers.clarification_id",
                f"unknown clarification id from Life agent: {answer.clarification_id}",
            )
        if int(clarification["loop_id"]) != answer.loop_id:
            raise ValidationError(
                "clarification_answers.loop_id",
                f"clarification {answer.clarification_id} does not belong to loop {answer.loop_id}",
            )
        if clarification.get("answer") is not None:
            raise ValidationError(
                "clarification_answers.clarification_id",
                f"clarification already answered: {answer.clarification_id}",
            )
        if not repo.answer_loop_clarification(
            clarification_id=answer.clarification_id,
            answer=answer.answer.strip(),
            conn=conn,
        ):
            raise ValidationError(
                "clarification_answers.clarification_id",
                f"clarification changed before answer could be recorded: {answer.clarification_id}",
            )
        updated = repo.read_loop_clarification(
            clarification_id=answer.clarification_id,
            conn=conn,
        )
        if updated is None:
            raise ValidationError(
                "clarification_answers.clarification_id",
                f"clarification disappeared after answer: {answer.clarification_id}",
            )
        repo.insert_loop_event(
            loop_id=answer.loop_id,
            event_type="life_clarification_answered",
            payload={
                "clarification_id": answer.clarification_id,
                "question": updated.get("question"),
                "answer": updated.get("answer"),
                "rationale": answer.rationale,
            },
            conn=conn,
        )
        answers.append(
            LifeClarificationAnswer(
                clarification_id=int(updated["id"]),
                loop_id=int(updated["loop_id"]),
                question=str(updated["question"]),
                answer=str(updated["answer"]),
                rationale=answer.rationale,
            )
        )
    return answers


def _cleanup_plan_from_agent(
    *,
    decision: _LifeAgentDecision,
    loop_lookup: Mapping[int, Mapping[str, Any]],
    applied: Sequence[LifeLoopItem],
    undo: Sequence[LifeUndoHandle],
) -> LifeCleanupPlan:
    close_candidates: list[LifeLoopItem] = []
    archive_candidates: list[LifeLoopItem] = []
    keep_active: list[LifeLoopItem] = []
    review_needed: list[LifeLoopItem] = []
    for action in decision.cleanup_actions:
        loop = loop_lookup.get(action.loop_id)
        if loop is None:
            continue
        item = _loop_item(
            loop,
            rationale=action.rationale,
            prepared_next_action=action.next_action,
            life_state=action.result_life_state,
        )
        if action.cleanup_bucket == "close_candidate":
            close_candidates.append(item)
        elif action.cleanup_bucket == "archive_candidate":
            archive_candidates.append(item)
        elif action.cleanup_bucket == "keep_active":
            keep_active.append(item)
        else:
            review_needed.append(item)

    return LifeCleanupPlan(
        open_count=sum(
            1
            for loop in loop_lookup.values()
            if str(loop.get("status")) in {s.value for s in _OPEN_STATUSES}
        ),
        recommendation=decision.reply,
        close_candidates=close_candidates,
        archive_candidates=archive_candidates,
        keep_active=keep_active,
        review_needed=review_needed,
        applied_automatic_cleanup=list(applied),
        undo=list(undo),
    )


def _apply_cleanup_actions(
    *,
    decision: _LifeAgentDecision,
    message: str,
    loop_lookup: dict[int, dict[str, Any]],
    conn: sqlite3.Connection,
) -> tuple[list[LifeLoopItem], list[LifeUndoHandle]]:
    applied: list[LifeLoopItem] = []
    undo: list[LifeUndoHandle] = []
    for action in decision.cleanup_actions:
        if not action.apply_now:
            continue
        _assert_agent_action_authority(
            field="cleanup.approval_basis",
            risk_level=action.risk_level,
            approval_basis=action.approval_basis,
        )
        if action.loop_id not in loop_lookup:
            raise ValidationError(
                "cleanup.loop_id", f"unknown loop id from Life agent: {action.loop_id}"
            )
        if action.action == "delete":
            if "delete" not in message.lower():
                raise ValidationError(
                    "cleanup.delete",
                    "Life agent may only delete when the user explicitly says delete",
                )
            snapshot = dict(loop_lookup[action.loop_id])
            deleted = repo.delete_loop(loop_id=action.loop_id, conn=conn)
            if not deleted:
                raise ValidationError("cleanup.loop_id", f"loop not found: {action.loop_id}")
            applied.append(
                _loop_item(
                    snapshot,
                    rationale=action.rationale,
                    life_state=action.result_life_state,
                )
            )
            del loop_lookup[action.loop_id]
            continue
        if action.action == "merge":
            if action.target_loop_id is None:
                raise ValidationError("cleanup.target_loop_id", "merge requires target_loop_id")
            if action.target_loop_id == action.loop_id:
                raise ValidationError("cleanup.target_loop_id", "cannot merge a loop into itself")
            if action.target_loop_id not in loop_lookup:
                raise ValidationError(
                    "cleanup.target_loop_id",
                    f"unknown merge target from Life agent: {action.target_loop_id}",
                )
            result = loop_duplicates.merge_loops(
                surviving_loop_id=action.target_loop_id,
                duplicate_loop_id=action.loop_id,
                field_overrides=action.field_overrides,
                conn=conn,
            )
            surviving = read_service.get_loop(loop_id=result.surviving_loop.id, conn=conn)
            closed = read_service.get_loop(loop_id=result.closed_loop_id, conn=conn)
            loop_lookup[int(surviving["id"])] = surviving
            loop_lookup[int(closed["id"])] = closed
            applied.append(
                _loop_item(
                    surviving,
                    rationale=action.rationale,
                    life_state=action.result_life_state,
                )
            )
            continue
        if action.action in {"add_dependency", "remove_dependency"}:
            if action.target_loop_id is None:
                raise ValidationError(
                    "cleanup.target_loop_id", "dependency action requires target_loop_id"
                )
            if action.target_loop_id == action.loop_id:
                raise ValidationError("cleanup.target_loop_id", "loop cannot depend on itself")
            if action.target_loop_id not in loop_lookup:
                raise ValidationError(
                    "cleanup.target_loop_id",
                    f"unknown dependency target from Life agent: {action.target_loop_id}",
                )
            if action.action == "add_dependency":
                updated = service.add_loop_dependency(
                    loop_id=action.loop_id,
                    depends_on_loop_id=action.target_loop_id,
                    conn=conn,
                )
            else:
                updated = service.remove_loop_dependency(
                    loop_id=action.loop_id,
                    depends_on_loop_id=action.target_loop_id,
                    conn=conn,
                )
            updated = _transition_if_needed(
                loop=updated,
                loop_status=action.target_loop_status,
                conn=conn,
                note=action.note or f"Life cleanup: {action.rationale}",
            )
            loop_lookup[action.loop_id] = updated
            item = _loop_item(
                updated,
                rationale=action.rationale,
                life_state=action.result_life_state,
            )
            applied.append(item)
            continue
        if action.action in {"keep", "review"}:
            continue
        if action.action in _STATUS_CHANGING_CLEANUP_ACTIONS and action.target_loop_status is None:
            raise ValidationError(
                "cleanup.target_loop_status",
                f"{action.action} requires target_loop_status from the Life agent",
            )
        fields = _sanitize_update_fields(
            {
                "snooze_until_utc": action.snooze_until_utc,
                "due_date": action.due_date,
                "due_at_utc": action.due_at_utc,
                "blocked_reason": (
                    action.blocked_reason
                    or (
                        f"Delegated to {action.delegated_to}."
                        if action.action == "delegate" and action.delegated_to
                        else None
                    )
                ),
                "urgency": action.urgency,
                "importance": action.importance,
                "emotional_weight": action.emotional_weight,
                "confidence": action.confidence,
                "next_action": action.next_action,
            }
        )
        if fields:
            updated = service.update_loop(loop_id=action.loop_id, fields=fields, conn=conn)
        else:
            updated = dict(loop_lookup[action.loop_id])
        if action.target_loop_status is not None:
            updated = _transition_if_needed(
                loop=updated,
                loop_status=action.target_loop_status,
                conn=conn,
                note=action.note or f"Life cleanup: {action.rationale}",
            )
        loop_lookup[action.loop_id] = updated
        item = _loop_item(
            updated,
            rationale=action.rationale,
            prepared_next_action=action.next_action,
            life_state=action.result_life_state,
        )
        applied.append(item)
        event_id = updated.get("latest_reversible_event_id")
        event_type = updated.get("latest_reversible_event_type")
        if event_id is not None and event_type is not None:
            undo.append(
                LifeUndoHandle(
                    loop_id=int(updated["id"]),
                    expected_event_id=int(event_id),
                    event_type=str(event_type),
                    label=(
                        f"Undo {action.action}: {updated.get('title') or updated.get('raw_text')}"
                    ),
                )
            )
    return applied, undo


def _groups_from_agent(
    *,
    decision: _LifeAgentDecision,
    loop_lookup: Mapping[int, Mapping[str, Any]],
    captured_group_memberships: Mapping[int, Sequence[LifeGroupName]],
    updated_group_memberships: Mapping[int, Sequence[LifeGroupName]],
    existing_items: Mapping[int, LifeLoopItem],
) -> list[LifeLoopGroup]:
    groups: dict[LifeGroupName, LifeLoopGroup] = {}
    for group in decision.groups:
        items = [
            _loop_item(
                loop_lookup[item.loop_id],
                rationale=item.rationale,
                prepared_next_action=item.prepared_next_action,
                prepared_actions=item.prepared_actions,
                life_state=item.life_state,
            )
            for item in group.items
            if item.loop_id in loop_lookup
        ]
        groups[group.name] = LifeLoopGroup(
            name=group.name,
            title=group.title,
            summary=group.summary,
            items=items,
        )
    for loop_id, names in {
        **dict(captured_group_memberships),
        **dict(updated_group_memberships),
    }.items():
        loop = loop_lookup.get(loop_id)
        if loop is None:
            continue
        for name in names:
            group = groups.get(name)
            if group is None:
                continue
            group.items.append(existing_items.get(loop_id) or _loop_item(loop, rationale=None))
    return list(groups.values())


def _record_resurfacing_events(
    *,
    decision: _LifeAgentDecision,
    known_loop_ids: set[int],
    conn: sqlite3.Connection,
) -> None:
    if decision.mode not in {"resurface", "cleanup"}:
        return
    seen: set[tuple[int, LifeGroupName]] = set()
    for group in decision.groups:
        for item in group.items:
            loop_id = item.loop_id
            if loop_id not in known_loop_ids:
                continue
            key = (loop_id, group.name)
            if key in seen:
                continue
            seen.add(key)
            repo.insert_loop_event(
                loop_id=loop_id,
                event_type="life_resurfaced",
                payload={
                    "group": group.name,
                    "group_title": group.title,
                    "mode": decision.mode,
                    "reply": decision.reply,
                },
                conn=conn,
            )


def _record_life_touch_events(
    *,
    loop_ids: set[int],
    mode: str,
    reply: str,
    conn: sqlite3.Connection,
) -> None:
    for loop_id in sorted(loop_ids):
        repo.insert_loop_event(
            loop_id=loop_id,
            event_type="life_touched",
            payload={
                "actor": "agent",
                "mode": mode,
                "reply": reply,
            },
            conn=conn,
        )


def _record_life_user_touch_events(
    *,
    loop_ids: set[int],
    message: str,
    mode: str,
    conn: sqlite3.Connection,
) -> None:
    for loop_id in sorted(loop_ids):
        repo.insert_loop_event(
            loop_id=loop_id,
            event_type="life_user_touched",
            payload={
                "actor": "user",
                "mode": mode,
                "message_preview": message.strip()[:240],
            },
            conn=conn,
        )


def handle_life_message(
    *,
    message: str,
    settings: Settings,
    conn: sqlite3.Connection,
    captured_at: str | None = None,
    client_tz_offset_min: int = 0,
    interaction_source: _LifeInteractionSource = "user",
    external_inputs: Sequence[LifeExternalInput] = (),
) -> LifeMessageResponse:
    """Handle one Life-feed message through the organizer-backed Life agent."""
    captured_dt = (
        parse_client_datetime(captured_at, tz_offset_min=client_tz_offset_min)
        if captured_at
        else utc_now()
    )
    captured_at_iso = format_utc_datetime(captured_dt)
    before_open = _open_loops(conn=conn)
    before_history = _history_loops(conn=conn)
    known_loop_ids = {int(loop["id"]) for loop in before_open + before_history}
    known_memory_ids = {
        int(entry["id"]) for entry in _life_memory_entries(settings=settings, conn=conn)
    }

    decision, evidence = _run_life_agent(
        message=message,
        captured_at_iso=captured_at_iso,
        client_tz_offset_min=client_tz_offset_min,
        conn=conn,
        settings=settings,
        interaction_source=interaction_source,
        external_inputs=external_inputs,
    )

    captured: list[LifeLoopItem] = []
    updated: list[LifeLoopItem] = []
    captured_group_memberships: dict[int, list[LifeGroupName]] = {}
    updated_group_memberships: dict[int, list[LifeGroupName]] = {}
    clarifications: list[LifeClarification] = []
    answered_clarifications: list[LifeClarificationAnswer] = []
    with conn:
        context_link_count = 0
        capture_index_to_loop_id: dict[int, int] = {}
        for capture_index, capture in enumerate(decision.captures):
            item, loop_id = _capture_or_update(
                capture=capture,
                captured_at_iso=captured_at_iso,
                client_tz_offset_min=client_tz_offset_min,
                known_loop_ids=known_loop_ids,
                conn=conn,
                settings=settings,
                external_inputs=external_inputs,
            )
            capture_index_to_loop_id[capture_index] = loop_id
            if capture.duplicate_of_loop_id is None:
                captured.append(item)
                captured_group_memberships[loop_id] = list(capture.group_names)
            else:
                updated.append(item)
                updated_group_memberships[loop_id] = list(capture.group_names)
            context_link_count += _apply_loop_links(
                loop_id=loop_id,
                related_loop_ids=capture.related_loop_ids,
                relationship_type=capture.relationship_type,
                confidence=capture.relationship_confidence,
                known_loop_ids=known_loop_ids,
                conn=conn,
            )
            known_loop_ids.add(loop_id)

        for update in decision.updates:
            if update.loop_id not in known_loop_ids:
                raise ValidationError(
                    "updates.loop_id", f"unknown loop id from Life agent: {update.loop_id}"
                )
            loop = _apply_update(
                loop_id=update.loop_id,
                fields=update.fields,
                loop_status=update.loop_status,
                conn=conn,
            )
            loop = _attach_source_evidence(
                loop=loop,
                labels_or_urls=update.source_evidence,
                external_inputs=external_inputs,
                conn=conn,
            )
            updated.append(
                _loop_item(
                    loop,
                    rationale=update.rationale or "Updated by the Life agent.",
                    prepared_next_action=update.prepared_next_action,
                    prepared_actions=update.prepared_actions,
                    life_state=update.life_state,
                )
            )
            context_link_count += _apply_loop_links(
                loop_id=int(loop["id"]),
                related_loop_ids=update.related_loop_ids,
                relationship_type=update.relationship_type,
                confidence=update.relationship_confidence,
                known_loop_ids=known_loop_ids,
                conn=conn,
            )
            updated_group_memberships[int(loop["id"])] = list(update.group_names)

        created_memories = [
            _store_memory(memory=memory, conn=conn, settings=settings)
            for memory in decision.memories
        ]
        updated_memories, deleted_memory_count = _apply_memory_updates(
            decision=decision,
            known_memory_ids=known_memory_ids,
            message=message,
            conn=conn,
            settings=settings,
        )
        memories = created_memories + updated_memories

        clarifications = _apply_clarifications(
            decision=decision,
            known_loop_ids=known_loop_ids,
            capture_index_to_loop_id=capture_index_to_loop_id,
            conn=conn,
        )
        answered_clarifications = _apply_clarification_answers(
            decision=decision,
            known_loop_ids=known_loop_ids,
            conn=conn,
        )

        loop_lookup = {
            int(loop["id"]): loop for loop in _open_loops(conn=conn) + _history_loops(conn=conn)
        }
        applied, undo = _apply_cleanup_actions(
            decision=decision,
            message=message,
            loop_lookup=loop_lookup,
            conn=conn,
        )
        _record_resurfacing_events(
            decision=decision,
            known_loop_ids=set(loop_lookup),
            conn=conn,
        )
        touched_loop_ids = {
            int(item.loop.id)
            for item in [*captured, *updated, *applied]
            if item.life_state != "deleted"
        } | {answer.loop_id for answer in answered_clarifications}
        _record_life_touch_events(
            loop_ids=touched_loop_ids,
            mode=decision.mode,
            reply=decision.reply,
            conn=conn,
        )
        if interaction_source == "user":
            _record_life_user_touch_events(
                loop_ids=touched_loop_ids,
                message=message,
                mode=decision.mode,
                conn=conn,
            )

    loop_lookup = {
        int(loop["id"]): loop for loop in _open_loops(conn=conn) + _history_loops(conn=conn)
    }
    for item in captured + updated + applied:
        loop_lookup[int(item.loop.id)] = item.loop.model_dump(mode="json")

    groups = _groups_from_agent(
        decision=decision,
        loop_lookup=loop_lookup,
        captured_group_memberships=captured_group_memberships,
        updated_group_memberships=updated_group_memberships,
        existing_items={int(item.loop.id): item for item in [*captured, *updated, *applied]},
    )
    cleanup = None
    if decision.mode == "cleanup" or decision.cleanup_actions:
        cleanup = _cleanup_plan_from_agent(
            decision=decision,
            loop_lookup=loop_lookup,
            applied=applied,
            undo=undo,
        )

    response = LifeMessageResponse(
        mode=decision.mode,
        reply=decision.reply,
        notify_user=decision.notify_user,
        notification_title=decision.notification_title,
        notification_body=decision.notification_body,
        captured=captured,
        updated=updated + list(applied),
        clarifications=clarifications,
        answered_clarifications=answered_clarifications,
        memories=memories,
        groups=groups,
        cleanup=cleanup,
        evidence=evidence,
    )
    response.evidence["context_links_created"] = context_link_count
    response.evidence["memory_updates_deleted"] = deleted_memory_count
    return response
