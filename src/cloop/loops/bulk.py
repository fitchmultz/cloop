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

import sqlite3
from collections.abc import Callable
from typing import Any, Mapping

from .. import typingx
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
from .models import LoopStatus, is_terminal_status, utc_now
from .query import compile_loop_query, parse_loop_query
from .service_helpers import (
    _apply_loop_update,
    _apply_status_transition,
    _enrich_record,
    _enrich_records_batch,
)

BulkItemValidator = Callable[[Mapping[str, Any]], str | None]
BulkItemExecutor = Callable[[Mapping[str, Any]], dict[str, Any]]


class _Rollback(Exception):
    """Sentinel exception used to rollback transactional bulk operations."""


def _validation_result(*, index: int, loop_id: Any, message: str) -> dict[str, Any]:
    """Build a standard validation-failure result for bulk items."""
    return {
        "index": index,
        "loop_id": loop_id,
        "ok": False,
        "error": {
            "code": "validation_error",
            "message": message,
        },
    }


def _loop_result(*, index: int, loop_id: int, loop: dict[str, Any]) -> dict[str, Any]:
    """Build a standard success result for bulk items."""
    return {
        "index": index,
        "loop_id": loop_id,
        "ok": True,
        "loop": loop,
    }


def _error_result(*, index: int, loop_id: int, exc: Exception) -> dict[str, Any]:
    """Build a standard failure result for bulk items."""
    return {
        "index": index,
        "loop_id": loop_id,
        "ok": False,
        "error": {"code": _classify_error(exc), "message": str(exc)},
    }


def _run_bulk_operation(
    *,
    items: list[Mapping[str, Any]],
    transactional: bool,
    conn: sqlite3.Connection,
    validate_item: BulkItemValidator | None,
    execute_item: BulkItemExecutor,
) -> dict[str, Any]:
    """Run a shared bulk item pipeline for transactional and best-effort modes."""
    results: list[dict[str, Any]] = []

    def _process_item(index: int, item: Mapping[str, Any]) -> None:
        loop_id = item.get("loop_id")
        if not isinstance(loop_id, int):
            results.append(
                _validation_result(
                    index=index,
                    loop_id=loop_id,
                    message="loop_id must be an integer",
                )
            )
            return

        try:
            if validate_item is not None:
                validation_message = validate_item(item)
                if validation_message is not None:
                    results.append(
                        _validation_result(
                            index=index,
                            loop_id=loop_id,
                            message=validation_message,
                        )
                    )
                    return
            results.append(_loop_result(index=index, loop_id=loop_id, loop=execute_item(item)))
        except Exception as exc:
            results.append(_error_result(index=index, loop_id=loop_id, exc=exc))

    if transactional:
        try:
            with conn:
                for index, item in enumerate(items):
                    _process_item(index, item)
                if any(not result["ok"] for result in results):
                    raise _Rollback()
        except _Rollback:
            rolled_back_results = _rollback_transaction_results(results)
            return {
                "ok": False,
                "transactional": True,
                "results": rolled_back_results,
                "succeeded": 0,
                "failed": len(items),
            }
    else:
        for index, item in enumerate(items):
            with conn:
                _process_item(index, item)

    failed = sum(1 for result in results if not result["ok"])
    return {
        "ok": failed == 0,
        "transactional": transactional,
        "results": results,
        "succeeded": len(results) - failed,
        "failed": failed,
    }


def _preview_query_targets(
    *,
    loop_ids: list[int],
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Build dry-run preview payloads using the canonical loop serializer."""
    records = [
        record for loop_id in loop_ids if (record := repo.read_loop(loop_id=loop_id, conn=conn))
    ]
    return _enrich_records_batch(records, conn=conn)


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

    def _update_single(
        loop_id: int, fields: Mapping[str, Any], claim_token: str | None = None
    ) -> dict[str, Any]:
        updated = _apply_loop_update(
            loop_id=loop_id,
            fields=fields,
            claim_token=claim_token,
            conn=conn,
        )
        return _enrich_record(record=updated, conn=conn)

    return _run_bulk_operation(
        items=updates,
        transactional=transactional,
        conn=conn,
        validate_item=None,
        execute_item=lambda item: _update_single(
            item["loop_id"],
            item.get("fields", {}),
            item.get("claim_token"),
        ),
    )


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

    def _close_single(
        loop_id: int, to_status: LoopStatus, note: str | None, claim_token: str | None = None
    ) -> dict[str, Any]:
        updated = _apply_status_transition(
            loop_id=loop_id,
            to_status=to_status,
            note=note,
            claim_token=claim_token,
            conn=conn,
        )
        return _enrich_record(record=updated, conn=conn)

    def _validate_close(item: Mapping[str, Any]) -> str | None:
        status = LoopStatus(item.get("status", "completed"))
        if not is_terminal_status(status):
            return "must be completed or dropped"
        return None

    return _run_bulk_operation(
        items=items,
        transactional=transactional,
        conn=conn,
        validate_item=_validate_close,
        execute_item=lambda item: _close_single(
            item["loop_id"],
            LoopStatus(item.get("status", "completed")),
            item.get("note"),
            item.get("claim_token"),
        ),
    )


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

    with conn:
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

    def _snooze_single(
        loop_id: int, snooze_until_utc: str, claim_token: str | None = None
    ) -> dict[str, Any]:
        updated = _apply_loop_update(
            loop_id=loop_id,
            fields={"snooze_until_utc": snooze_until_utc},
            claim_token=claim_token,
            conn=conn,
        )
        return _enrich_record(record=updated, conn=conn)

    return _run_bulk_operation(
        items=items,
        transactional=transactional,
        conn=conn,
        validate_item=lambda item: (
            None if item.get("snooze_until_utc") else "snooze_until_utc is required"
        ),
        execute_item=lambda item: _snooze_single(
            item["loop_id"],
            item["snooze_until_utc"],
            item.get("claim_token"),
        ),
    )


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
        return {
            "query": query,
            "dry_run": True,
            "ok": True,
            "transactional": transactional,
            "matched_count": len(loop_ids),
            "results": [],
            "succeeded": 0,
            "failed": 0,
            "targets": _preview_query_targets(loop_ids=loop_ids, conn=conn),
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
        return {
            "query": query,
            "dry_run": True,
            "ok": True,
            "transactional": transactional,
            "matched_count": len(loop_ids),
            "results": [],
            "succeeded": 0,
            "failed": 0,
            "targets": _preview_query_targets(loop_ids=loop_ids, conn=conn),
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
        return {
            "query": query,
            "dry_run": True,
            "ok": True,
            "transactional": transactional,
            "matched_count": len(loop_ids),
            "results": [],
            "succeeded": 0,
            "failed": 0,
            "targets": _preview_query_targets(loop_ids=loop_ids, conn=conn),
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
