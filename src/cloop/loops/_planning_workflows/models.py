"""Planning workflow models and constants.

Purpose:
    Define validated planning session options, operation shapes, and
    generated workflow payloads for shared planning orchestration.

Responsibilities:
    - Declare planning option defaults and bounds
    - Validate generated operations through discriminated unions
    - Expose reusable planning type aliases and adapters

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Planning workflow data modeling only
    - No persistence, LLM calls, or deterministic execution

Usage:
    Imported by `_planning_workflows` modules and re-exported via
    `cloop.loops.planning_workflows`.

Invariants/Assumptions:
    - Planning operations are discriminated by `kind`
    - Bounds stay aligned with planner prompting and execution limits
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator

from ...schemas.loops import LoopUpdateRequest

PlanningSessionStatus = Literal["draft", "in_progress", "completed"]


PlanningMoveDirection = Literal["next", "previous"]


_MAX_PLANNING_TARGETS = 25


_MAX_PLANNING_CHECKPOINTS = 6


_MAX_PLANNING_OPERATIONS_PER_CHECKPOINT = 10


_DEFAULT_PLANNING_OPTIONS = {
    "loop_limit": 10,
    "include_memory_context": True,
    "include_rag_context": False,
    "rag_k": 5,
    "rag_scope": None,
}


class PlanningSessionOptionsModel(BaseModel):
    """Validated persisted options for one planning session."""

    loop_limit: int = Field(default=10, ge=1, le=_MAX_PLANNING_TARGETS)
    include_memory_context: bool = True
    include_rag_context: bool = False
    rag_k: int = Field(default=5, ge=1, le=20)
    rag_scope: str | None = None


class BasePlanningOperationModel(BaseModel):
    """Shared human-facing metadata for one generated operation."""

    kind: str
    summary: str = Field(..., min_length=1, max_length=500)


class CreateLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["create_loop"] = "create_loop"
    raw_text: str = Field(..., min_length=1, max_length=4000)
    status: Literal["inbox", "actionable", "blocked", "scheduled"] = "inbox"
    capture_fields: LoopUpdateRequest | None = None


class UpdateLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["update_loop"] = "update_loop"
    loop_id: int
    fields: LoopUpdateRequest


class TransitionLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["transition_loop"] = "transition_loop"
    loop_id: int
    status: Literal["inbox", "actionable", "blocked", "scheduled"]
    note: str | None = None


class CloseLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["close_loop"] = "close_loop"
    loop_id: int
    status: Literal["completed", "dropped"] = "completed"
    note: str | None = None


class EnrichLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["enrich_loop"] = "enrich_loop"
    loop_id: int


class BulkEnrichQueryOperationModel(BasePlanningOperationModel):
    kind: Literal["bulk_enrich_query"] = "bulk_enrich_query"
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=100)


class QueryBulkUpdateOperationModel(BasePlanningOperationModel):
    kind: Literal["query_bulk_update"] = "query_bulk_update"
    query: str = Field(..., min_length=1, max_length=500)
    fields: LoopUpdateRequest
    limit: int = Field(default=25, ge=1, le=100)


class QueryBulkCloseOperationModel(BasePlanningOperationModel):
    kind: Literal["query_bulk_close"] = "query_bulk_close"
    query: str = Field(..., min_length=1, max_length=500)
    status: Literal["completed", "dropped"] = "completed"
    note: str | None = None
    limit: int = Field(default=25, ge=1, le=100)


class QueryBulkSnoozeOperationModel(BasePlanningOperationModel):
    kind: Literal["query_bulk_snooze"] = "query_bulk_snooze"
    query: str = Field(..., min_length=1, max_length=500)
    snooze_until_utc: str
    limit: int = Field(default=25, ge=1, le=100)


class CreateRelationshipReviewSessionOperationModel(BasePlanningOperationModel):
    kind: Literal["create_relationship_review_session"] = "create_relationship_review_session"
    name: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=500)
    relationship_kind: Literal["all", "duplicate", "related"] = "all"
    candidate_limit: int = Field(default=3, ge=1, le=20)
    item_limit: int = Field(default=25, ge=1, le=100)


class CreateEnrichmentReviewSessionOperationModel(BasePlanningOperationModel):
    kind: Literal["create_enrichment_review_session"] = "create_enrichment_review_session"
    name: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=500)
    pending_kind: Literal["all", "suggestions", "clarifications"] = "all"
    suggestion_limit: int = Field(default=3, ge=1, le=20)
    clarification_limit: int = Field(default=3, ge=1, le=20)
    item_limit: int = Field(default=25, ge=1, le=100)


class CreateLoopViewOperationModel(BasePlanningOperationModel):
    kind: Literal["create_loop_view"] = "create_loop_view"
    name: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=500)


class UpdateLoopViewOperationModel(BasePlanningOperationModel):
    kind: Literal["update_loop_view"] = "update_loop_view"
    view_id: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_has_changes(self) -> UpdateLoopViewOperationModel:
        if self.name is None and self.query is None and self.description is None:
            raise ValueError("update_loop_view requires at least one changed field")
        return self


class CreateLoopTemplateFromLoopOperationModel(BasePlanningOperationModel):
    kind: Literal["create_loop_template_from_loop"] = "create_loop_template_from_loop"
    loop_id: int
    template_name: str = Field(..., min_length=1, max_length=120)


class UpdateLoopTemplateOperationModel(BasePlanningOperationModel):
    kind: Literal["update_loop_template"] = "update_loop_template"
    template_id: int
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    raw_text_pattern: str | None = Field(default=None, max_length=4000)
    defaults_json: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_has_changes(self) -> UpdateLoopTemplateOperationModel:
        if (
            self.name is None
            and self.description is None
            and self.raw_text_pattern is None
            and self.defaults_json is None
        ):
            raise ValueError("update_loop_template requires at least one changed field")
        return self


PlanningOperationModel = Annotated[
    CreateLoopOperationModel
    | UpdateLoopOperationModel
    | TransitionLoopOperationModel
    | CloseLoopOperationModel
    | EnrichLoopOperationModel
    | BulkEnrichQueryOperationModel
    | QueryBulkUpdateOperationModel
    | QueryBulkCloseOperationModel
    | QueryBulkSnoozeOperationModel
    | CreateRelationshipReviewSessionOperationModel
    | CreateEnrichmentReviewSessionOperationModel
    | CreateLoopViewOperationModel
    | UpdateLoopViewOperationModel
    | CreateLoopTemplateFromLoopOperationModel
    | UpdateLoopTemplateOperationModel,
    Field(discriminator="kind"),
]


class PlanningCheckpointModel(BaseModel):
    """One checkpoint inside a generated planning workflow."""

    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=1000)
    success_criteria: str = Field(..., min_length=1, max_length=1000)
    operations: list[PlanningOperationModel] = Field(
        ...,
        min_length=1,
        max_length=_MAX_PLANNING_OPERATIONS_PER_CHECKPOINT,
    )


class GeneratedPlanningWorkflowModel(BaseModel):
    """Validated AI-generated workflow structure."""

    title: str = Field(..., min_length=1, max_length=200)
    summary: str = Field(..., min_length=1, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    checkpoints: list[PlanningCheckpointModel] = Field(
        ...,
        min_length=1,
        max_length=_MAX_PLANNING_CHECKPOINTS,
    )


_OPERATION_ADAPTER = TypeAdapter(PlanningOperationModel)


__all__ = [
    "PlanningSessionStatus",
    "PlanningMoveDirection",
    "_MAX_PLANNING_TARGETS",
    "_MAX_PLANNING_CHECKPOINTS",
    "_MAX_PLANNING_OPERATIONS_PER_CHECKPOINT",
    "_DEFAULT_PLANNING_OPTIONS",
    "PlanningSessionOptionsModel",
    "BasePlanningOperationModel",
    "CreateLoopOperationModel",
    "UpdateLoopOperationModel",
    "TransitionLoopOperationModel",
    "CloseLoopOperationModel",
    "EnrichLoopOperationModel",
    "BulkEnrichQueryOperationModel",
    "QueryBulkUpdateOperationModel",
    "QueryBulkCloseOperationModel",
    "QueryBulkSnoozeOperationModel",
    "CreateRelationshipReviewSessionOperationModel",
    "CreateEnrichmentReviewSessionOperationModel",
    "CreateLoopViewOperationModel",
    "UpdateLoopViewOperationModel",
    "CreateLoopTemplateFromLoopOperationModel",
    "UpdateLoopTemplateOperationModel",
    "PlanningOperationModel",
    "PlanningCheckpointModel",
    "GeneratedPlanningWorkflowModel",
    "_OPERATION_ADAPTER",
]
