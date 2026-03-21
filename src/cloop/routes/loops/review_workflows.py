"""Saved review action and session endpoints.

Purpose:
    Re-export feature-owned HTTP review workflow route modules behind the
    canonical `cloop.routes.loops.review_workflows` router surface.

Responsibilities:
    - Preserve one stable router for relationship and enrichment review endpoints
    - Keep the review-workflow route namespace organized by domain

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Public HTTP route facade only
    - No inline endpoint business logic

Usage:
    Imported by `cloop.routes.loops` when assembling the `/loops` router tree.

Invariants/Assumptions:
    - Relationship and enrichment routes remain registered on one shared router
    - Endpoint paths and response contracts stay unchanged
"""

from __future__ import annotations

from fastapi import APIRouter

from ._review_workflows.enrichment import (
    answer_enrichment_review_session_clarifications_endpoint,
    create_enrichment_review_action_endpoint,
    create_enrichment_review_session_endpoint,
    delete_enrichment_review_action_endpoint,
    delete_enrichment_review_session_endpoint,
    execute_enrichment_review_session_action_endpoint,
    get_enrichment_review_action_endpoint,
    get_enrichment_review_session_endpoint,
    list_enrichment_review_actions_endpoint,
    list_enrichment_review_sessions_endpoint,
    move_enrichment_review_session_endpoint,
    refresh_enrichment_review_session_endpoint,
    update_enrichment_review_action_endpoint,
    update_enrichment_review_session_endpoint,
)
from ._review_workflows.enrichment import (
    router as enrichment_router,
)
from ._review_workflows.relationship import (
    create_relationship_review_action_endpoint,
    create_relationship_review_session_endpoint,
    delete_relationship_review_action_endpoint,
    delete_relationship_review_session_endpoint,
    execute_relationship_review_session_action_endpoint,
    get_relationship_review_action_endpoint,
    get_relationship_review_session_endpoint,
    list_relationship_review_actions_endpoint,
    list_relationship_review_sessions_endpoint,
    move_relationship_review_session_endpoint,
    refresh_relationship_review_session_endpoint,
    update_relationship_review_action_endpoint,
    update_relationship_review_session_endpoint,
)
from ._review_workflows.relationship import (
    router as relationship_router,
)

router = APIRouter()
router.include_router(relationship_router)
router.include_router(enrichment_router)

__all__ = [
    "router",
    "list_relationship_review_actions_endpoint",
    "create_relationship_review_action_endpoint",
    "get_relationship_review_action_endpoint",
    "update_relationship_review_action_endpoint",
    "delete_relationship_review_action_endpoint",
    "list_relationship_review_sessions_endpoint",
    "create_relationship_review_session_endpoint",
    "get_relationship_review_session_endpoint",
    "move_relationship_review_session_endpoint",
    "refresh_relationship_review_session_endpoint",
    "update_relationship_review_session_endpoint",
    "delete_relationship_review_session_endpoint",
    "execute_relationship_review_session_action_endpoint",
    "list_enrichment_review_actions_endpoint",
    "create_enrichment_review_action_endpoint",
    "get_enrichment_review_action_endpoint",
    "update_enrichment_review_action_endpoint",
    "delete_enrichment_review_action_endpoint",
    "list_enrichment_review_sessions_endpoint",
    "create_enrichment_review_session_endpoint",
    "get_enrichment_review_session_endpoint",
    "move_enrichment_review_session_endpoint",
    "refresh_enrichment_review_session_endpoint",
    "update_enrichment_review_session_endpoint",
    "delete_enrichment_review_session_endpoint",
    "execute_enrichment_review_session_action_endpoint",
    "answer_enrichment_review_session_clarifications_endpoint",
]
