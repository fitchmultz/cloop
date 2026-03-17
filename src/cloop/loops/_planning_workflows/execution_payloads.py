"""Planning execution payload helpers.

Purpose:
    Normalize planning operation payloads and build consistent execution
    result/resource payload structures.

Responsibilities:
    - Normalize capture and update field payloads
    - Serialize planning operations for durable execution history
    - Build resource references and before/after execution payloads
    - Normalize template rows for JSON-safe snapshots

Non-scope:
    - Re-implementing neighboring modules' responsibilities inline
    - Unrelated workflow concerns outside this module's stated responsibility

Scope:
    - Execution payload shaping only
    - No persistence, rollback execution, or operation dispatch

Usage:
    Imported by planning execution validation, rollback, and operation modules.

Invariants/Assumptions:
    - Payloads remain JSON-serializable for execution history storage
    - Update operations must include at least one changed field
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ...schemas.loops import LoopUpdateRequest
from ..errors import ValidationError
from .models import _OPERATION_ADAPTER, PlanningOperationModel


def _normalize_capture_fields(fields: LoopUpdateRequest | None) -> dict[str, Any] | None:
    if fields is None:
        return None
    payload = fields.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    payload.pop("claim_token", None)
    return payload or None


def _normalize_update_fields(fields: LoopUpdateRequest) -> dict[str, Any]:
    payload = fields.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    payload.pop("claim_token", None)
    if not payload:
        raise ValidationError(
            "fields",
            "planning update_loop operation requires at least one field",
        )
    return payload


def _operation_payload(operation: PlanningOperationModel) -> dict[str, Any]:
    return _OPERATION_ADAPTER.dump_python(operation, mode="json")


def _resource_label(resource: Mapping[str, Any]) -> str | None:
    title = resource.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    raw_text = resource.get("raw_text")
    if isinstance(raw_text, str) and raw_text.strip():
        return raw_text.strip()[:120]
    name = resource.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _resource_ref(
    *,
    resource_type: str,
    resource_id: int,
    role: str,
    label: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "role": role,
    }
    if label is not None:
        payload["label"] = label
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload


def _template_row_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    defaults_json = payload.get("defaults_json")
    if isinstance(defaults_json, str):
        payload["defaults_json"] = json.loads(defaults_json) if defaults_json else {}
    return payload


def _operation_result_payload(
    *,
    index: int,
    operation: PlanningOperationModel,
    result: Mapping[str, Any],
    before_loops: Sequence[Mapping[str, Any]] | None = None,
    after_loops: Sequence[Mapping[str, Any]] | None = None,
    resource_refs: Sequence[Mapping[str, Any]] | None = None,
    rollback_actions: Sequence[Mapping[str, Any]] | None = None,
    provenance: Mapping[str, Any] | None = None,
    undoable: bool | None = None,
) -> dict[str, Any]:
    normalized_rollback_actions = [dict(action) for action in rollback_actions or []]
    payload: dict[str, Any] = {
        "index": index,
        "kind": operation.kind,
        "summary": operation.summary,
        "ok": True,
        "operation": _operation_payload(operation),
        "result": dict(result),
        "undoable": (
            bool(undoable)
            if undoable is not None
            else any(action.get("kind") == "loop.undo" for action in normalized_rollback_actions)
        ),
        "rollback_supported": bool(normalized_rollback_actions),
        "resource_refs": [dict(resource) for resource in resource_refs or []],
        "rollback_actions": normalized_rollback_actions,
        "provenance": dict(provenance or {}),
    }
    if before_loops is not None:
        payload["before_loops"] = [dict(loop) for loop in before_loops]
    if after_loops is not None:
        payload["after_loops"] = [dict(loop) for loop in after_loops]
    return payload


__all__ = [
    "_normalize_capture_fields",
    "_normalize_update_fields",
    "_operation_payload",
    "_resource_label",
    "_resource_ref",
    "_template_row_payload",
    "_operation_result_payload",
]
