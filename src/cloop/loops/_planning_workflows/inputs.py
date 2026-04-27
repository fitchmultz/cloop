"""Planning workflow input normalization helpers.

Purpose:
    Normalize operator-provided planning inputs and planner payloads before
    generation, persistence, or execution.

Responsibilities:
    - Validate human-facing planning names and prompts
    - Merge and validate persisted planning option payloads
    - Extract planner JSON objects from raw model output

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Input and payload validation for planning workflows
    - No persistence, LLM invocation, or checkpoint execution

Usage:
    Imported by planning generation, snapshot, execution, and facade modules.

Invariants/Assumptions:
    - Empty prompt/name values are rejected eagerly
    - Planner responses must eventually yield one top-level JSON object
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import ValidationError
from ..json_extraction import extract_first_json_object
from .models import _DEFAULT_PLANNING_OPTIONS, PlanningMoveDirection, PlanningSessionOptionsModel


def _normalize_name(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError(field, f"{field.replace('_', ' ')} must not be empty")
    return normalized


def _normalize_prompt(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError("prompt", "prompt must not be empty")
    return normalized


def _normalize_optional_query(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _validate_move_direction(value: str) -> PlanningMoveDirection:
    if value == "next":
        return "next"
    if value == "previous":
        return "previous"
    raise ValidationError("direction", "must be next or previous")


def _validate_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = {**_DEFAULT_PLANNING_OPTIONS, **(dict(options) if options else {})}
    return PlanningSessionOptionsModel.model_validate(merged).model_dump(mode="json")


def _extract_json_object(payload: str) -> dict[str, Any]:
    parsed = extract_first_json_object(payload)
    if parsed is None:
        raise ValidationError("response", "invalid JSON from planner")
    return parsed


__all__ = [
    "_normalize_name",
    "_normalize_prompt",
    "_normalize_optional_query",
    "_validate_move_direction",
    "_validate_options",
    "_extract_json_object",
]
