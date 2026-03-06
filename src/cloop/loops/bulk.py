"""Bulk operation functions for loop management.

Purpose:
    Provide batch operations for updating, closing, and snoozing multiple loops
    in a single operation, with support for transactional semantics.

Responsibilities:
    - Bulk update loop fields (tags, project, metadata)
    - Bulk close loops to completed/dropped states
    - Bulk snooze loops with snooze_until_utc timestamps
    - Transactional mode: rollback all changes if any item fails
    - Non-transactional mode: process items independently, report per-item success/failure
    - Error classification and result formatting for batch operations
    - Template creation from existing loops

Non-scope:
    - Individual loop CRUD (see service.py)
    - Status transitions other than closing (see service.py)
    - Direct database access (delegates to repo.py)
    - Webhook delivery orchestration (delegates to webhooks.service)
    - Claim management (delegates to service.py helpers)

Invariants/Assumptions:
    - All bulk operations require an active database connection
    - Claim validation is performed per-item when claim_token is provided
    - Transactional mode uses SQLite savepoints for atomicity
    - Error codes are stable strings for client consumption
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from .. import typingx
from ..webhooks.service import queue_deliveries
from . import repo
from .errors import (
    ClaimExpiredError,
    ClaimNotFoundError,
    DependencyCycleError,
    DependencyNotMetError,
    LoopClaimedError,
    LoopNotFoundError,
    MergeConflictError,
    SuggestionNotFoundError,
    TransitionError,
    ValidationError,
)
from .metrics import record_transition, record_update
from .models import LoopEventType, LoopStatus, format_utc_datetime, is_terminal_status, utc_now
from .query import compile_loop_query, parse_loop_query
from .service_helpers import (
    _ALLOWED_TRANSITIONS,
    _LOCKABLE_FIELDS,
    _handle_recurrence_on_completion,
    _record_to_dict,
    _validate_claim_for_update,
)
from .utils import normalize_tags


@typingx.validate_io()
def bulk_update_loops(
    *,
    updates: list[Mapping[str, Any]],
    transactional: bool,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk update multiple loops.

    Args:
        updates: List of updates, each with loop_id and fields
        transactional: If True, rollback all on any failure
        conn: Database connection

    Returns:
        Dict with ok, transactional, results (per-item), succeeded, failed
    """

    class _Rollback(Exception):
        pass

    def _update_single(
        loop_id: int, fields: Mapping[str, Any], claim_token: str | None = None
    ) -> dict[str, Any]:
        if "status" in fields:
            raise ValidationError("status", "use /loops/{id}/status or /loops/{id}/close endpoints")
        # Validate claim if loop is claimed
        _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)
        record = repo.read_loop(loop_id=loop_id, conn=conn)
        if record is None:
            raise LoopNotFoundError(loop_id)
        locked_fields = set(record.user_locks)
        mutable_fields = dict(fields)
        tags = None
        if "tags" in mutable_fields:
            tags = mutable_fields.pop("tags")
            if tags is not None and not isinstance(tags, list):
                tags = [tags]
        project_name = None
        if "project" in mutable_fields:
            project_name = mutable_fields.pop("project")
            project_name = str(project_name).strip() if project_name else ""
            if project_name:
                mutable_fields["project_id"] = "pending"
            else:
                mutable_fields["project_id"] = None

        for field_name in {**mutable_fields, **({"tags": tags} if tags is not None else {})}.keys():
            if field_name in _LOCKABLE_FIELDS:
                locked_fields.add(field_name)
        updated_fields = dict(mutable_fields)
        updated_fields["user_locks_json"] = json.dumps(sorted(locked_fields))
        if project_name:
            project_id = repo.upsert_project(name=project_name, conn=conn)
            updated_fields["project_id"] = project_id
        updated = repo.update_loop_fields(loop_id=loop_id, fields=updated_fields, conn=conn)
        record_update()
        if tags is not None:
            normalized_tags = normalize_tags(tags)
            repo.replace_loop_tags(loop_id=loop_id, tag_names=normalized_tags, conn=conn)
        event_payload = {"fields": dict(fields)}
        event_id = repo.insert_loop_event(
            loop_id=updated.id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        project = repo.read_project_name(project_id=updated.project_id, conn=conn)
        tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
        return _record_to_dict(updated, project=project, tags=tags)

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    if transactional:
        try:
            with conn:
                for idx, item in enumerate(updates):
                    loop_id = item.get("loop_id")
                    fields = item.get("fields", {})

                    if not isinstance(loop_id, int):
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {
                                    "code": "validation_error",
                                    "message": "loop_id must be an integer",
                                },
                            }
                        )
                        failed += 1
                        continue

                    try:
                        claim_token = item.get("claim_token")
                        record = _update_single(loop_id, fields, claim_token)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": True,
                                "loop": record,
                            }
                        )
                        succeeded += 1
                    except Exception as exc:
                        error_code = _classify_error(exc)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {"code": error_code, "message": str(exc)},
                            }
                        )
                        failed += 1

                if failed > 0:
                    raise _Rollback()
        except _Rollback:
            return {
                "ok": False,
                "transactional": True,
                "results": _rollback_transaction_results(results),
                "succeeded": 0,
                "failed": len(updates),
            }
    else:
        for idx, item in enumerate(updates):
            loop_id = item.get("loop_id")
            fields = item.get("fields", {})

            if not isinstance(loop_id, int):
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {
                            "code": "validation_error",
                            "message": "loop_id must be an integer",
                        },
                    }
                )
                failed += 1
                continue

            try:
                with conn:
                    claim_token = item.get("claim_token")
                    record = _update_single(loop_id, fields, claim_token)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": True,
                        "loop": record,
                    }
                )
                succeeded += 1
            except Exception as exc:
                error_code = _classify_error(exc)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {"code": error_code, "message": str(exc)},
                    }
                )
                failed += 1

    return {
        "ok": failed == 0,
        "transactional": transactional,
        "results": results,
        "succeeded": succeeded,
        "failed": failed,
    }


@typingx.validate_io()
def bulk_close_loops(
    *,
    items: list[Mapping[str, Any]],
    transactional: bool,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk close multiple loops.

    Args:
        items: List of items with loop_id, optional status (default completed), optional note
        transactional: If True, rollback all on any failure
        conn: Database connection

    Returns:
        Dict with ok, transactional, results (per-item), succeeded, failed
    """

    class _Rollback(Exception):
        pass

    def _close_single(
        loop_id: int, to_status: LoopStatus, note: str | None, claim_token: str | None = None
    ) -> dict[str, Any]:
        # Validate claim if loop is claimed
        _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)
        record = repo.read_loop(loop_id=loop_id, conn=conn)
        if record is None:
            raise LoopNotFoundError(loop_id)
        if record.status == to_status:
            project = repo.read_project_name(project_id=record.project_id, conn=conn)
            tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
            return _record_to_dict(record, project=project, tags=tags)

        allowed = _ALLOWED_TRANSITIONS.get(record.status, set())
        if to_status not in allowed:
            raise TransitionError(record.status.value, to_status.value)

        # Check for open dependencies when transitioning to actionable
        if to_status == LoopStatus.ACTIONABLE:
            open_deps = repo.list_open_dependencies(loop_id=loop_id, conn=conn)
            if open_deps:
                raise DependencyNotMetError(loop_id, open_deps)

        closed_at = None
        if is_terminal_status(to_status):
            closed_at = format_utc_datetime(utc_now())

        # Handle recurring loop completion - create next occurrence
        next_loop_id: int | None = None
        if to_status == LoopStatus.COMPLETED:
            next_loop_id = _handle_recurrence_on_completion(record=record, conn=conn)

        updates: dict[str, Any] = {"status": to_status.value, "closed_at": closed_at}
        if to_status is LoopStatus.COMPLETED and note and note.strip():
            updates["completion_note"] = note.strip()
        # Disable recurrence on completed loop so it doesn't generate more
        if to_status == LoopStatus.COMPLETED and record.is_recurring():
            updates["recurrence_enabled"] = 0
        updated = repo.update_loop_fields(
            loop_id=loop_id,
            fields=updates,
            conn=conn,
        )
        record_transition(record.status.value, to_status.value)
        event_type = (
            LoopEventType.CLOSE.value
            if is_terminal_status(to_status)
            else LoopEventType.STATUS_CHANGE.value
        )
        payload: dict[str, Any] = {"from": record.status.value, "to": to_status.value}
        if note:
            payload["note"] = note
        if closed_at:
            payload["closed_at_utc"] = closed_at
        if next_loop_id is not None:
            payload["next_occurrence_loop_id"] = next_loop_id
        event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type=event_type,
            payload=payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            conn=conn,
        )
        project = repo.read_project_name(project_id=updated.project_id, conn=conn)
        tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
        return _record_to_dict(updated, project=project, tags=tags)

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    if transactional:
        try:
            with conn:
                for idx, item in enumerate(items):
                    loop_id = item.get("loop_id")
                    status_str = item.get("status", "completed")
                    note = item.get("note")

                    if not isinstance(loop_id, int):
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {
                                    "code": "validation_error",
                                    "message": "loop_id must be an integer",
                                },
                            }
                        )
                        failed += 1
                        continue

                    try:
                        loop_status = LoopStatus(status_str)
                        if not is_terminal_status(loop_status):
                            raise ValidationError("status", "must be completed or dropped")
                        claim_token = item.get("claim_token")
                        record = _close_single(loop_id, loop_status, note, claim_token)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": True,
                                "loop": record,
                            }
                        )
                        succeeded += 1
                    except Exception as exc:
                        error_code = _classify_error(exc)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {"code": error_code, "message": str(exc)},
                            }
                        )
                        failed += 1

                if failed > 0:
                    raise _Rollback()
        except _Rollback:
            return {
                "ok": False,
                "transactional": True,
                "results": _rollback_transaction_results(results),
                "succeeded": 0,
                "failed": len(items),
            }
    else:
        for idx, item in enumerate(items):
            loop_id = item.get("loop_id")
            status_str = item.get("status", "completed")
            note = item.get("note")

            if not isinstance(loop_id, int):
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {
                            "code": "validation_error",
                            "message": "loop_id must be an integer",
                        },
                    }
                )
                failed += 1
                continue

            try:
                with conn:
                    loop_status = LoopStatus(status_str)
                    if not is_terminal_status(loop_status):
                        raise ValidationError("status", "must be completed or dropped")
                    claim_token = item.get("claim_token")
                    record = _close_single(loop_id, loop_status, note, claim_token)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": True,
                        "loop": record,
                    }
                )
                succeeded += 1
            except Exception as exc:
                error_code = _classify_error(exc)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {"code": error_code, "message": str(exc)},
                    }
                )
                failed += 1

    return {
        "ok": failed == 0,
        "transactional": transactional,
        "results": results,
        "succeeded": succeeded,
        "failed": failed,
    }


def create_template_from_loop(
    *,
    loop_id: int,
    template_name: str,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Create a template from an existing loop.

    Args:
        loop_id: ID of loop to use as template source
        template_name: Name for the new template
        conn: Database connection

    Returns:
        Created template record

    Raises:
        LoopNotFoundError: If loop doesn't exist
        ValidationError: If template name is invalid or already exists
    """
    from .repo import create_loop_template, list_loop_tags, read_loop

    loop = read_loop(loop_id=loop_id, conn=conn)
    if not loop:
        raise LoopNotFoundError(loop_id)

    tags = list_loop_tags(loop_id=loop_id, conn=conn)

    # Build defaults from loop fields
    defaults: dict[str, Any] = {}
    if loop.title:
        defaults["title"] = loop.title
    if tags:
        defaults["tags"] = tags
    if loop.time_minutes is not None:
        defaults["time_minutes"] = loop.time_minutes
    if loop.activation_energy is not None:
        defaults["activation_energy"] = loop.activation_energy
    if loop.urgency is not None:
        defaults["urgency"] = loop.urgency
    if loop.importance is not None:
        defaults["importance"] = loop.importance
    if loop.status == LoopStatus.ACTIONABLE:
        defaults["actionable"] = True
    elif loop.status == LoopStatus.SCHEDULED:
        defaults["scheduled"] = True
    elif loop.status == LoopStatus.BLOCKED:
        defaults["blocked"] = True

    return create_loop_template(
        name=template_name,
        description=f"Created from loop #{loop_id}",
        raw_text_pattern=loop.raw_text,
        defaults_json=defaults,
        is_system=False,
        conn=conn,
    )


@typingx.validate_io()
def bulk_snooze_loops(
    *,
    items: list[Mapping[str, Any]],
    transactional: bool,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk snooze multiple loops.

    Args:
        items: List of items with loop_id and snooze_until_utc
        transactional: If True, rollback all on any failure
        conn: Database connection

    Returns:
        Dict with ok, transactional, results (per-item), succeeded, failed
    """

    class _Rollback(Exception):
        pass

    def _snooze_single(
        loop_id: int, snooze_until_utc: str, claim_token: str | None = None
    ) -> dict[str, Any]:
        # Validate claim if loop is claimed
        _validate_claim_for_update(loop_id=loop_id, claim_token=claim_token, conn=conn)
        record = repo.read_loop(loop_id=loop_id, conn=conn)
        if record is None:
            raise LoopNotFoundError(loop_id)
        locked_fields = set(record.user_locks)
        if "snooze_until_utc" in _LOCKABLE_FIELDS:
            locked_fields.add("snooze_until_utc")
        updated_fields = {
            "snooze_until_utc": snooze_until_utc,
            "user_locks_json": json.dumps(sorted(locked_fields)),
        }
        updated = repo.update_loop_fields(loop_id=loop_id, fields=updated_fields, conn=conn)
        event_payload = {"fields": {"snooze_until_utc": snooze_until_utc}}
        event_id = repo.insert_loop_event(
            loop_id=updated.id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.UPDATE.value,
            payload=event_payload,
            conn=conn,
        )
        project = repo.read_project_name(project_id=updated.project_id, conn=conn)
        tags = repo.list_loop_tags(loop_id=updated.id, conn=conn)
        return _record_to_dict(updated, project=project, tags=tags)

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    if transactional:
        try:
            with conn:
                for idx, item in enumerate(items):
                    loop_id = item.get("loop_id")
                    snooze_until_utc = item.get("snooze_until_utc")

                    if not isinstance(loop_id, int):
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {
                                    "code": "validation_error",
                                    "message": "loop_id must be an integer",
                                },
                            }
                        )
                        failed += 1
                        continue

                    if not snooze_until_utc:
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {
                                    "code": "validation_error",
                                    "message": "snooze_until_utc is required",
                                },
                            }
                        )
                        failed += 1
                        continue

                    try:
                        claim_token = item.get("claim_token")
                        record = _snooze_single(loop_id, snooze_until_utc, claim_token)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": True,
                                "loop": record,
                            }
                        )
                        succeeded += 1
                    except Exception as exc:
                        error_code = _classify_error(exc)
                        results.append(
                            {
                                "index": idx,
                                "loop_id": loop_id,
                                "ok": False,
                                "error": {"code": error_code, "message": str(exc)},
                            }
                        )
                        failed += 1

                if failed > 0:
                    raise _Rollback()
        except _Rollback:
            return {
                "ok": False,
                "transactional": True,
                "results": _rollback_transaction_results(results),
                "succeeded": 0,
                "failed": len(items),
            }
    else:
        for idx, item in enumerate(items):
            loop_id = item.get("loop_id")
            snooze_until_utc = item.get("snooze_until_utc")

            if not isinstance(loop_id, int):
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {
                            "code": "validation_error",
                            "message": "loop_id must be an integer",
                        },
                    }
                )
                failed += 1
                continue

            if not snooze_until_utc:
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {
                            "code": "validation_error",
                            "message": "snooze_until_utc is required",
                        },
                    }
                )
                failed += 1
                continue

            try:
                with conn:
                    claim_token = item.get("claim_token")
                    record = _snooze_single(loop_id, snooze_until_utc, claim_token)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": True,
                        "loop": record,
                    }
                )
                succeeded += 1
            except Exception as exc:
                error_code = _classify_error(exc)
                results.append(
                    {
                        "index": idx,
                        "loop_id": loop_id,
                        "ok": False,
                        "error": {"code": error_code, "message": str(exc)},
                    }
                )
                failed += 1

    return {
        "ok": failed == 0,
        "transactional": transactional,
        "results": results,
        "succeeded": succeeded,
        "failed": failed,
    }


def _classify_error(exc: Exception) -> str:
    """Classify exception into a stable error code."""
    if isinstance(exc, LoopNotFoundError):
        return "not_found"
    if isinstance(exc, TransitionError):
        return "transition_error"
    if isinstance(exc, ValidationError):
        return "validation_error"
    if isinstance(exc, LoopClaimedError):
        return "loop_claimed"
    if isinstance(exc, ClaimNotFoundError):
        return "claim_not_found"
    if isinstance(exc, ClaimExpiredError):
        return "claim_expired"
    if isinstance(exc, DependencyCycleError):
        return "dependency_cycle"
    if isinstance(exc, DependencyNotMetError):
        return "dependency_not_met"
    if isinstance(exc, MergeConflictError):
        return "merge_conflict"
    if isinstance(exc, SuggestionNotFoundError):
        return "suggestion_not_found"
    return "internal_error"


def _rollback_transaction_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark transactional results as rolled back while preserving root-cause failures."""
    rolled_back: list[dict[str, Any]] = []
    for result in results:
        if result.get("ok", False):
            rolled_back.append(
                {
                    "index": result["index"],
                    "loop_id": result["loop_id"],
                    "ok": False,
                    "error": {
                        "code": "transaction_rollback",
                        "message": "rolled back due to other failures",
                        "rolled_back": True,
                    },
                }
            )
            continue

        error = result.get("error")
        merged_error: dict[str, Any]
        if isinstance(error, Mapping):
            merged_error = dict(error)
        else:
            merged_error = {
                "code": "internal_error",
                "message": "operation failed and transaction was rolled back",
            }
        merged_error["rolled_back"] = True
        rolled_back.append(
            {
                "index": result["index"],
                "loop_id": result["loop_id"],
                "ok": False,
                "error": merged_error,
            }
        )
    return rolled_back


def _resolve_loop_ids_by_query(
    *,
    query: str,
    limit: int,
    conn: sqlite3.Connection,
) -> list[int]:
    """Resolve a DSL query to a list of loop IDs.

    Args:
        query: DSL query string
        limit: Maximum number of IDs to return
        conn: Database connection

    Returns:
        List of loop IDs matching the query

    Raises:
        ValidationError: If query syntax is invalid
    """
    parsed = parse_loop_query(query)
    now = utc_now()
    where_sql, params = compile_loop_query(parsed, now_utc=now)

    sql = (
        f"SELECT loops.id FROM loops LEFT JOIN projects ON loops.project_id = projects.id "
        f"{where_sql} LIMIT ?"
    )
    params_with_limit = params + [limit]

    cursor = conn.execute(sql, params_with_limit)
    return [row[0] for row in cursor.fetchall()]


@typingx.validate_io()
def query_bulk_update_loops(
    *,
    query: str,
    fields: Mapping[str, Any],
    transactional: bool,
    dry_run: bool,
    limit: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk update loops selected by DSL query.

    Args:
        query: DSL query to select targets
        fields: Fields to update
        transactional: If True, rollback all on any failure
        dry_run: If True, return preview without applying changes
        limit: Max loops to affect
        conn: Database connection

    Returns:
        Dict with query, dry_run, ok, matched_count, results, succeeded, failed
    """
    loop_ids = _resolve_loop_ids_by_query(query=query, limit=limit, conn=conn)

    if dry_run:
        targets = []
        for lid in loop_ids:
            record = repo.read_loop(loop_id=lid, conn=conn)
            if record:
                project = repo.read_project_name(project_id=record.project_id, conn=conn)
                tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
                targets.append(_record_to_dict(record, project=project, tags=tags))
        return {
            "query": query,
            "dry_run": True,
            "ok": True,
            "transactional": transactional,
            "matched_count": len(loop_ids),
            "results": [],
            "succeeded": 0,
            "failed": 0,
            "targets": targets,
            "limited": len(loop_ids) >= limit,
        }

    updates = [{"loop_id": lid, "fields": dict(fields)} for lid in loop_ids]
    if not updates:
        return {
            "query": query,
            "dry_run": False,
            "ok": True,
            "transactional": transactional,
            "matched_count": 0,
            "limited": False,
            "results": [],
            "succeeded": 0,
            "failed": 0,
        }

    result = bulk_update_loops(updates=updates, transactional=transactional, conn=conn)
    result["query"] = query
    result["dry_run"] = False
    result["matched_count"] = len(loop_ids)
    result["limited"] = len(loop_ids) >= limit
    return result


@typingx.validate_io()
def query_bulk_close_loops(
    *,
    query: str,
    status: str,
    note: str | None,
    transactional: bool,
    dry_run: bool,
    limit: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk close loops selected by DSL query."""
    loop_ids = _resolve_loop_ids_by_query(query=query, limit=limit, conn=conn)

    if dry_run:
        targets = []
        for lid in loop_ids:
            record = repo.read_loop(loop_id=lid, conn=conn)
            if record:
                project = repo.read_project_name(project_id=record.project_id, conn=conn)
                tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
                targets.append(_record_to_dict(record, project=project, tags=tags))
        return {
            "query": query,
            "dry_run": True,
            "ok": True,
            "transactional": transactional,
            "matched_count": len(loop_ids),
            "results": [],
            "succeeded": 0,
            "failed": 0,
            "targets": targets,
            "limited": len(loop_ids) >= limit,
        }

    items = [{"loop_id": lid, "status": status} for lid in loop_ids]
    if note:
        for item in items:
            item["note"] = note
    if not items:
        return {
            "query": query,
            "dry_run": False,
            "ok": True,
            "transactional": transactional,
            "matched_count": 0,
            "limited": False,
            "results": [],
            "succeeded": 0,
            "failed": 0,
        }

    result = bulk_close_loops(items=items, transactional=transactional, conn=conn)
    result["query"] = query
    result["dry_run"] = False
    result["matched_count"] = len(loop_ids)
    result["limited"] = len(loop_ids) >= limit
    return result


@typingx.validate_io()
def query_bulk_snooze_loops(
    *,
    query: str,
    snooze_until_utc: str,
    transactional: bool,
    dry_run: bool,
    limit: int,
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    """Bulk snooze loops selected by DSL query."""
    loop_ids = _resolve_loop_ids_by_query(query=query, limit=limit, conn=conn)

    if dry_run:
        targets = []
        for lid in loop_ids:
            record = repo.read_loop(loop_id=lid, conn=conn)
            if record:
                project = repo.read_project_name(project_id=record.project_id, conn=conn)
                tags = repo.list_loop_tags(loop_id=record.id, conn=conn)
                targets.append(_record_to_dict(record, project=project, tags=tags))
        return {
            "query": query,
            "dry_run": True,
            "ok": True,
            "transactional": transactional,
            "matched_count": len(loop_ids),
            "results": [],
            "succeeded": 0,
            "failed": 0,
            "targets": targets,
            "limited": len(loop_ids) >= limit,
        }

    items = [{"loop_id": lid, "snooze_until_utc": snooze_until_utc} for lid in loop_ids]
    if not items:
        return {
            "query": query,
            "dry_run": False,
            "ok": True,
            "transactional": transactional,
            "matched_count": 0,
            "limited": False,
            "results": [],
            "succeeded": 0,
            "failed": 0,
        }

    result = bulk_snooze_loops(items=items, transactional=transactional, conn=conn)
    result["query"] = query
    result["dry_run"] = False
    result["matched_count"] = len(loop_ids)
    result["limited"] = len(loop_ids) >= limit
    return result
