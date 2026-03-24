"""CLI handlers for continuity diagnostics.

Purpose:
    Execute `cloop continuity *` commands by delegating to the shared
    continuity diagnostics storage contract.

Responsibilities:
    - Route continuity diagnostics CLI reads to the shared delivery inspection path.
    - Render delivery diagnostics in JSON or a compact operator-friendly table.
    - Reuse the shared CLI runtime for stable error mapping and exit codes.

Non-scope:
    - Continuity mutation workflows.
    - Re-implementing delivery diagnostics policy outside the shared storage path.

Scope:
    - CLI execution for continuity diagnostics only.

Usage:
    - Imported by `cloop.cli_package.dispatch` for parsed-command routing.

Invariants/Assumptions:
    - Delivery diagnostics pagination uses an opaque `cursor` token.
    - JSON output mirrors the shared HTTP/MCP data contract.
    - Table output stays minimal and downstream of the shared data model.
"""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from ..loops.errors import ValidationError
from ..settings import Settings
from ..storage.continuity_store import read_continuity_delivery_inspection
from ._runtime import cli_error, error_handler, run_cli_action
from .output import emit_output, render_table, stringify_cell


def _common_error_handlers() -> list:
    return [error_handler(ValidationError, lambda exc: cli_error(exc.message))]


def _delivery_decision_row(decision: dict[str, Any]) -> list[str]:
    record = decision.get("record") or {}
    latest_push = decision.get("latest_push_delivery") or {}
    workflow_thread = record.get("workflow_thread") or {}
    return [
        stringify_cell(record.get("id")),
        stringify_cell(decision.get("reason")),
        stringify_cell(record.get("severity")),
        stringify_cell(workflow_thread.get("id")),
        stringify_cell(decision.get("resend_ready_at_utc")),
        stringify_cell(latest_push.get("delivery_status")),
        stringify_cell(latest_push.get("delivery_reason")),
    ]


def _render_delivery_inspection(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        emit_output(payload, output_format)
        return

    continuation = payload.get("continuation") or {}
    summary = {
        "inspected_at_utc": payload.get("inspected_at_utc"),
        "channel": payload.get("channel"),
        "limit": payload.get("limit"),
        "truncated": payload.get("truncated"),
        "continuation_cursor": continuation.get("cursor"),
    }
    emit_output(summary, "table")
    print()

    decisions = payload.get("decisions") or []
    print(
        render_table(
            headers=[
                "notification_id",
                "reason",
                "severity",
                "workflow_thread_id",
                "resend_ready_at_utc",
                "latest_push_status",
                "latest_push_reason",
            ],
            rows=[_delivery_decision_row(decision) for decision in decisions],
        )
    )


def continuity_delivery_decisions_command(args: Namespace, settings: Settings) -> int:
    """Handle `cloop continuity delivery-decisions`."""
    return run_cli_action(
        action=lambda: read_continuity_delivery_inspection(
            limit=args.limit,
            settings=settings,
            channel=args.channel,
            cursor=args.cursor,
        ).model_dump(mode="python"),
        render=lambda payload: _render_delivery_inspection(payload, args.format),
        error_handlers=_common_error_handlers(),
    )
