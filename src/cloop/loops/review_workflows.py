"""Shared saved review actions and session-preserving review workflows.

Purpose:
    Re-export the feature-owned review workflow modules behind the canonical
    `cloop.loops.review_workflows` import surface.

Responsibilities:
    - Preserve one stable review workflow namespace for transports and tests
    - Keep shared review helpers discoverable without a monolithic implementation file
    - Re-export the `_UNSET` sentinel used by CLI, HTTP, and MCP update flows

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Public review workflow facade only
    - No inline queue materialization or review action execution logic

Usage:
    Import from `cloop.loops.review_workflows` for shared review action,
    session, and queued follow-up orchestration.

Invariants/Assumptions:
    - External callers keep using this module instead of the internal package
    - `_UNSET` remains the canonical sentinel for optional current-loop updates
"""

from __future__ import annotations

from ._review_workflows.actions import (
    create_enrichment_review_action,
    create_relationship_review_action,
    delete_enrichment_review_action,
    delete_relationship_review_action,
    get_enrichment_review_action,
    get_relationship_review_action,
    list_enrichment_review_actions,
    list_relationship_review_actions,
    update_enrichment_review_action,
    update_relationship_review_action,
)
from ._review_workflows.execution import (
    answer_enrichment_review_session_clarifications,
    execute_enrichment_review_session_action,
    execute_relationship_review_session_action,
)
from ._review_workflows.sessions import (
    create_enrichment_review_session,
    create_relationship_review_session,
    delete_enrichment_review_session,
    delete_relationship_review_session,
    get_enrichment_review_session,
    get_relationship_review_session,
    list_enrichment_review_sessions,
    list_relationship_review_sessions,
    move_enrichment_review_session,
    move_relationship_review_session,
    update_enrichment_review_session,
    update_relationship_review_session,
)
from ._review_workflows.shared import (
    _DEFAULT_ENRICHMENT_SESSION_OPTIONS,
    _DEFAULT_RELATIONSHIP_SESSION_OPTIONS,
    _UNSET,
    EnrichmentActionType,
    EnrichmentPendingKind,
    RelationshipActionType,
    RelationshipReviewKind,
    RelationshipTargetType,
    ReviewSessionMoveDirection,
    _enrichment_action_payload,
    _enrichment_session_payload,
    _ensure_loop_exists,
    _normalize_enrichment_fields,
    _normalize_name,
    _relationship_action_payload,
    _relationship_session_payload,
    _require_enrichment_action_row,
    _require_enrichment_session_row,
    _require_relationship_action_row,
    _require_relationship_session_row,
    _resolved_optional_loop_id,
    _validate_enrichment_action,
    _validate_enrichment_session_options,
    _validate_move_direction,
    _validate_query,
    _validate_relationship_action,
    _validate_relationship_session_options,
)
from ._review_workflows.snapshots import (
    _build_enrichment_session_snapshot,
    _build_relationship_session_snapshot,
    _candidate_loop_ids,
    _choose_current_loop_id,
    _move_session_loop_id,
    _persist_session_cursor,
)

__all__ = [
    "RelationshipActionType",
    "RelationshipTargetType",
    "EnrichmentActionType",
    "RelationshipReviewKind",
    "EnrichmentPendingKind",
    "ReviewSessionMoveDirection",
    "_UNSET",
    "_DEFAULT_RELATIONSHIP_SESSION_OPTIONS",
    "_DEFAULT_ENRICHMENT_SESSION_OPTIONS",
    "_normalize_name",
    "_validate_query",
    "_ensure_loop_exists",
    "_resolved_optional_loop_id",
    "_validate_move_direction",
    "_relationship_action_payload",
    "_enrichment_action_payload",
    "_relationship_session_payload",
    "_enrichment_session_payload",
    "_validate_relationship_action",
    "_normalize_enrichment_fields",
    "_validate_enrichment_action",
    "_validate_relationship_session_options",
    "_validate_enrichment_session_options",
    "_require_relationship_action_row",
    "_require_enrichment_action_row",
    "_require_relationship_session_row",
    "_require_enrichment_session_row",
    "_candidate_loop_ids",
    "_choose_current_loop_id",
    "_persist_session_cursor",
    "_build_relationship_session_snapshot",
    "_build_enrichment_session_snapshot",
    "_move_session_loop_id",
    "create_relationship_review_action",
    "list_relationship_review_actions",
    "get_relationship_review_action",
    "update_relationship_review_action",
    "delete_relationship_review_action",
    "create_enrichment_review_action",
    "list_enrichment_review_actions",
    "get_enrichment_review_action",
    "update_enrichment_review_action",
    "delete_enrichment_review_action",
    "create_relationship_review_session",
    "list_relationship_review_sessions",
    "get_relationship_review_session",
    "move_relationship_review_session",
    "update_relationship_review_session",
    "delete_relationship_review_session",
    "create_enrichment_review_session",
    "list_enrichment_review_sessions",
    "get_enrichment_review_session",
    "move_enrichment_review_session",
    "update_enrichment_review_session",
    "delete_enrichment_review_session",
    "execute_relationship_review_session_action",
    "execute_enrichment_review_session_action",
    "answer_enrichment_review_session_clarifications",
]
