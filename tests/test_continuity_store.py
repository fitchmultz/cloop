"""Durable continuity storage regression tests.

Purpose:
    Verify backend-backed continuity outcomes, workflow summaries, and
    fallback resolution stay stable as cross-device continuity evolves.

Responsibilities:
    - Assert durable continuity tables exist through the public DB bootstrap.
    - Guard outcome deduplication, backend-authored workflow summaries, and delivery inspection.
    - Verify explicit degraded fallback behavior for missing working-set scope and targets.

Non-scope:
    - Frontend ranking or rendering behavior.
    - Browser-local continuity baseline snapshots.

Usage:
    Run with `uv run --locked --all-groups pytest tests/test_continuity_store.py`.

Invariants/Assumptions:
    - Tests use isolated SQLite databases via `tmp_data_dir`.
    - Continuity persistence goes through public storage helpers.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import insert_planning_session, insert_scheduler_push_delivery

from cloop import db
from cloop.loops import enrichment_review, repo, review_workflows, service
from cloop.loops.errors import ValidationError
from cloop.loops.models import LoopStatus
from cloop.schemas._loops.continuity import (
    ContinuityDisplayCardResponse,
    ContinuityLastSeenBatchUpsertRequest,
    ContinuityLastSeenMarkerUpsertRequest,
    ContinuityLocationResponse,
    ContinuityNotificationStateUpsertRequest,
    ContinuityOutcomeWriteRequest,
    ContinuityRecoveryAcknowledgementUpsertRequest,
    ContinuityRerunAction,
    ContinuityUndoAction,
    WorkflowThreadRefResponse,
)
from cloop.settings import get_settings
from cloop.storage.continuity_store import (
    read_continuity_delivery_inspection,
    read_continuity_notification_records,
    read_continuity_snapshot,
    record_continuity_outcome,
    upsert_continuity_last_seen_markers,
    upsert_continuity_notification_state,
    upsert_continuity_recovery_acknowledgement,
)


def _insert_loop(tmp_data_dir: Path, loop_id: int = 11) -> None:
    with db.core_connection(get_settings()) as conn:
        conn.execute(
            """
            INSERT INTO loops (
                id,
                raw_text,
                status,
                captured_at_utc,
                captured_tz_offset_min
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (loop_id, f"Loop {loop_id}", "actionable", "2026-03-21T12:00:00Z", 0),
        )
        conn.commit()


_RELATIONSHIP_VECTORS = {
    "buy milk and eggs before the weekend": (1.0, 0.0, 0.0),
    "pick up groceries like milk and eggs": (0.99, 0.01, 0.0),
}


def _capture_loop(raw_text: str, *, status: LoopStatus, conn: sqlite3.Connection) -> dict[str, Any]:
    return service.capture_loop(
        raw_text=raw_text,
        captured_at_iso="2026-03-14T12:00:00+00:00",
        client_tz_offset_min=0,
        status=status,
        conn=conn,
    )


def _mock_relationship_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        inputs = kwargs.get("input") or []
        data: list[dict[str, list[float]]] = []
        for text in inputs:
            lowered = str(text).lower()
            vector = [0.1, 0.1, 0.1]
            for key, mapped in _RELATIONSHIP_VECTORS.items():
                if key in lowered:
                    vector = list(mapped)
                    break
            norm = math.sqrt(sum(component * component for component in vector)) or 1.0
            data.append(
                {
                    "embedding": [component / norm for component in vector],
                }
            )
        return {"data": data}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)


def _review_outcome_request(
    follow_through: Mapping[str, Any],
    *,
    dedupe_key: str,
    occurred_at_utc: str,
) -> ContinuityOutcomeWriteRequest:
    resume_location = ContinuityLocationResponse.model_validate(
        dict(follow_through["resume_location"])
    )
    undo_action = follow_through.get("undo_action")
    rerun_action = follow_through.get("rerun_action")
    return ContinuityOutcomeWriteRequest(
        kind="review",
        label=str(follow_through["display_card"]["title"]),
        description=str(follow_through["display_card"]["summary"]),
        occurred_at_utc=occurred_at_utc,
        launch_location=resume_location,
        display_card=ContinuityDisplayCardResponse.model_validate(
            dict(follow_through["display_card"])
        ),
        undo_action=(
            ContinuityUndoAction.model_validate(dict(undo_action))
            if isinstance(undo_action, Mapping)
            else None
        ),
        rerun_action=(
            ContinuityRerunAction.model_validate(dict(rerun_action))
            if isinstance(rerun_action, Mapping)
            else None
        ),
        resume_location=resume_location,
        working_set_id=follow_through.get("working_set_id"),
        workflow_thread=WorkflowThreadRefResponse.model_validate(
            dict(follow_through["workflow_thread"])
        ),
        dedupe_key=dedupe_key,
        source_surface="review-workspace",
        signal_level="high",
        metadata={"source": "review-workspace"},
    )


def _assert_review_round_trip(
    *,
    snapshot: Any,
    review_focus: str,
    session_id: int,
    undo_kind: str | None,
) -> None:
    outcome = snapshot.outcomes[0]
    summary = snapshot.workflow_summaries[0]
    notification = snapshot.notification_records[0]

    assert outcome.kind == "review"
    assert outcome.resume_location is not None
    assert outcome.resume_location.state == "decide"
    assert outcome.resume_location.review_focus == review_focus
    assert outcome.resume_location.session_id == session_id
    assert outcome.resolved_resume.status == "ok"
    assert outcome.resolved_resume.resolved_location.review_focus == review_focus
    assert outcome.resolved_resume.resolved_location.session_id == session_id
    assert outcome.rerun_action is not None
    assert outcome.rerun_action.rerun.kind == "review_session"
    assert outcome.rerun_action.rerun.review_focus == review_focus
    if undo_kind is None:
        assert outcome.undo_action is None
        assert summary.undo_action is None
    else:
        assert outcome.undo_action is not None
        assert outcome.undo_action.undo.kind == undo_kind
        assert summary.undo_action is not None
        assert summary.undo_action.undo.kind == undo_kind

    assert summary.workflow_thread.kind == "review_session"
    assert summary.requested_resume_location is not None
    assert summary.requested_resume_location.review_focus == review_focus
    assert summary.requested_resume_location.session_id == session_id
    assert summary.resolved_resume.resolved_location.review_focus == review_focus
    assert summary.resolved_resume.resolved_location.session_id == session_id
    assert summary.rerun_action is not None
    assert summary.rerun_action.rerun.kind == "review_session"
    assert summary.rerun_action.rerun.review_focus == review_focus
    assert notification.resolved_location.review_focus == review_focus
    assert notification.resolved_location.session_id == session_id


def _planning_undo_action_payload() -> ContinuityUndoAction:
    return ContinuityUndoAction.model_validate(
        {
            "label": "Undo checkpoint",
            "description": "Undo the checkpoint execution.",
            "undo": {
                "kind": "planning_run",
                "session_id": 41,
                "run_id": 8,
                "checkpoint_index": 1,
                "checkpoint_title": "Create queue",
                "action_count": 2,
                "best_effort": False,
            },
            "requires_confirmation": False,
            "confirm_title": None,
            "confirm_description": None,
            "success_location": {
                "state": "plan",
                "recall_tool": "chat",
                "review_focus": "planning",
                "session_id": 41,
                "loop_id": None,
                "view_id": None,
                "memory_id": None,
                "working_set_id": 7,
                "query": None,
            },
        }
    )


def _planning_rerun_action_payload() -> ContinuityRerunAction:
    return ContinuityRerunAction.model_validate(
        {
            "label": "Refresh plan",
            "description": "Refresh the saved planning session.",
            "rerun": {
                "kind": "planning_session",
                "session_id": 41,
                "session_name": "Weekly reset",
            },
            "contract": {
                "mode": "refresh",
                "provenance_label": "Planning session: Weekly reset",
                "freshness_label": "1 target changed",
                "strategy_summary": "Reuse the saved planning session.",
                "strict_invariants": ["Same planning session identity"],
                "may_vary": ["Checkpoint wording"],
                "post_run": {
                    "summary": "Land back in the saved planning session.",
                    "location": {
                        "state": "plan",
                        "recall_tool": "chat",
                        "review_focus": "planning",
                        "session_id": 41,
                        "loop_id": None,
                        "view_id": None,
                        "memory_id": None,
                        "working_set_id": 7,
                        "query": None,
                    },
                },
            },
        }
    )


def _outcome_request(
    *,
    label: str = "Created review queue",
    description: str = "The downstream queue is ready.",
    occurred_at_utc: str = "2026-03-21T12:00:00Z",
    launch_location: ContinuityLocationResponse | None = None,
    resume_location: ContinuityLocationResponse | None = None,
    dedupe_key: str = "planning::queue",
    workflow_thread_id: str = "planning:41:checkpoint:0",
    undo_action: ContinuityUndoAction | None = None,
    rerun_action: ContinuityRerunAction | None = None,
) -> ContinuityOutcomeWriteRequest:
    return ContinuityOutcomeWriteRequest(
        kind="planning",
        label=label,
        description=description,
        occurred_at_utc=occurred_at_utc,
        launch_location=launch_location,
        display_card=ContinuityDisplayCardResponse.model_validate(
            {
                "kind": "receipt",
                "tone": "progress",
                "eyebrow": "Planning receipt",
                "title": label,
                "summary": description,
                "rationale": "Receipt",
                "preview": [],
                "trust": {
                    "context_sources": ["Planning session"],
                    "assumptions": [],
                    "confidence_label": "Recorded",
                    "freshness_label": "Saved just now",
                    "rollback_label": "Undo remains available.",
                },
                "handoff": None,
                "action_context_label": None,
                "action_warning": None,
            }
        ),
        undo_action=undo_action,
        rerun_action=rerun_action,
        resume_location=resume_location,
        working_set_id=resume_location.working_set_id if resume_location else None,
        workflow_thread=WorkflowThreadRefResponse(
            id=workflow_thread_id,
            kind="planning_checkpoint",
            title="Weekly reset",
            summary="Planning checkpoint thread",
            parent_outcome_id=None,
        ),
        dedupe_key=dedupe_key,
        source_surface="review-workspace",
        signal_level="high",
        metadata={"sessionId": 41, "checkpointIndex": 0},
    )


def _push_delivery_reasons(*, limit: int = 3) -> list[str]:
    inspection = read_continuity_delivery_inspection(limit=limit, channel="push")
    return [decision.reason for decision in inspection.decisions]


def test_continuity_tables_exist(tmp_data_dir: Path) -> None:
    with closing(sqlite3.connect(get_settings().core_db_path)) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
                (
                    "continuity_outcomes",
                    "continuity_notification_states",
                    "continuity_recovery_acknowledgements",
                ),
            ).fetchall()
        }
    assert table_names == {
        "continuity_outcomes",
        "continuity_notification_states",
        "continuity_recovery_acknowledgements",
    }


def test_record_continuity_outcome_dedupes_within_window(tmp_data_dir: Path) -> None:
    record_continuity_outcome(_outcome_request())
    record_continuity_outcome(
        _outcome_request(
            label="Created review queue again",
            occurred_at_utc="2026-03-21T12:00:10Z",
        )
    )

    with db.core_connection(get_settings()) as conn:
        count = conn.execute("SELECT COUNT(*) FROM continuity_outcomes").fetchone()[0]

    snapshot = read_continuity_snapshot()
    assert count == 1
    assert snapshot.outcomes[0].label == "Created review queue again"
    assert snapshot.workflow_summaries[0].representative_outcome_id == snapshot.outcomes[0].id


def test_read_continuity_snapshot_builds_workflow_summaries(tmp_data_dir: Path) -> None:
    record_continuity_outcome(_outcome_request())
    record_continuity_outcome(
        _outcome_request(
            label="Refreshed planning thread",
            description="The plan changed again.",
            occurred_at_utc="2026-03-21T12:20:00Z",
            dedupe_key="planning::queue-2",
        )
    )

    snapshot = read_continuity_snapshot()
    assert len(snapshot.outcomes) == 2
    assert snapshot.workflow_summaries[0].workflow_thread.id == "planning:41:checkpoint:0"
    assert snapshot.workflow_summaries[0].outcome_count == 2
    assert snapshot.workflow_summaries[0].outcome_preview_titles[0] == "Refreshed planning thread"
    assert snapshot.notification_records[0].id == "planning:41:checkpoint:0"


def test_continuity_snapshot_round_trips_typed_follow_through_actions(tmp_data_dir: Path) -> None:
    record_continuity_outcome(
        _outcome_request(
            undo_action=_planning_undo_action_payload(),
            rerun_action=_planning_rerun_action_payload(),
            resume_location=ContinuityLocationResponse(
                state="decide",
                recall_tool="chat",
                review_focus="enrichment",
                session_id=52,
                working_set_id=7,
            ),
        )
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.outcomes[0].undo_action is not None
    assert snapshot.outcomes[0].undo_action.undo.kind == "planning_run"
    assert snapshot.outcomes[0].rerun_action is not None
    assert snapshot.outcomes[0].rerun_action.rerun.kind == "planning_session"
    assert snapshot.workflow_summaries[0].undo_action is not None
    assert snapshot.workflow_summaries[0].undo_action.undo.kind == "planning_run"
    assert snapshot.workflow_summaries[0].rerun_action is not None
    assert snapshot.workflow_summaries[0].rerun_action.rerun.kind == "planning_session"


def test_relationship_review_outcome_round_trips_through_continuity_snapshot(
    tmp_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del tmp_data_dir
    settings = get_settings()
    _mock_relationship_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        first_loop = _capture_loop(
            "Buy milk and eggs before the weekend",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        second_loop = _capture_loop(
            "Pick up groceries like milk and eggs",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        conn.commit()

        snapshot = review_workflows.create_relationship_review_session(
            name="duplicate-pass",
            query="status:open",
            relationship_kind="duplicate",
            candidate_limit=3,
            item_limit=25,
            current_loop_id=first_loop["id"],
            conn=conn,
            settings=settings,
        )
        after = review_workflows.execute_relationship_review_session_action(
            session_id=snapshot["session"]["id"],
            loop_id=first_loop["id"],
            candidate_loop_id=second_loop["id"],
            candidate_relationship_type="duplicate",
            action_preset_id=None,
            action_type="dismiss",
            relationship_type="duplicate",
            conn=conn,
            settings=settings,
        )

    record_continuity_outcome(
        _review_outcome_request(
            after["follow_through"],
            dedupe_key=f"review::relationship::{snapshot['session']['id']}",
            occurred_at_utc="2026-03-21T12:00:00Z",
        )
    )

    continuity = read_continuity_snapshot()
    _assert_review_round_trip(
        snapshot=continuity,
        review_focus="relationship",
        session_id=snapshot["session"]["id"],
        undo_kind="relationship_decision",
    )


@pytest.mark.parametrize(
    ("mode", "expected_undo_kind"),
    (("apply", "loop_event"), ("clarify", None)),
)
def test_enrichment_review_outcomes_round_trip_through_continuity_snapshot(
    tmp_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_undo_kind: str | None,
) -> None:
    del tmp_data_dir
    settings = get_settings()
    monkeypatch.setattr(
        "cloop.loops.enrichment.chat_completion",
        lambda *args, **kwargs: (
            json.dumps(
                {
                    "title": "Schedule launch date",
                    "next_action": "Confirm Friday launch plan",
                    "confidence": {"title": 0.99, "next_action": 0.99},
                }
            ),
            {"model": "mock-organizer", "latency_ms": 0.0, "usage": {}},
        ),
    )

    with db.core_connection(settings) as conn:
        first_loop = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)
        repo.insert_loop_suggestion(
            loop_id=first_loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=first_loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        apply_loop = _capture_loop(
            "Prepare launch retrospective",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        apply_suggestion_id = repo.insert_loop_suggestion(
            loop_id=apply_loop["id"],
            suggestion_json={"title": "Plan launch retrospective", "confidence": 0.99},
            model="test-model",
            conn=conn,
        )
        conn.commit()

        snapshot = review_workflows.create_enrichment_review_session(
            name=f"enrichment-{mode}",
            query="status:open",
            pending_kind="all",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=(apply_loop["id"] if mode == "apply" else first_loop["id"]),
            conn=conn,
        )

        if mode == "apply":
            after = review_workflows.execute_enrichment_review_session_action(
                session_id=snapshot["session"]["id"],
                suggestion_id=apply_suggestion_id,
                action_preset_id=None,
                action_type="apply",
                fields=["title"],
                conn=conn,
                settings=settings,
            )
        else:
            after = review_workflows.answer_enrichment_review_session_clarifications(
                session_id=snapshot["session"]["id"],
                loop_id=first_loop["id"],
                answers=[
                    enrichment_review.ClarificationAnswerInput(
                        clarification_id=clarification_id,
                        answer="Friday",
                    )
                ],
                conn=conn,
                settings=settings,
            )

    record_continuity_outcome(
        _review_outcome_request(
            after["follow_through"],
            dedupe_key=f"review::enrichment::{mode}::{snapshot['session']['id']}",
            occurred_at_utc="2026-03-21T12:05:00Z",
        )
    )

    continuity = read_continuity_snapshot()
    _assert_review_round_trip(
        snapshot=continuity,
        review_focus="enrichment",
        session_id=snapshot["session"]["id"],
        undo_kind=expected_undo_kind,
    )


def test_notification_state_round_trips_on_snapshot(tmp_data_dir: Path) -> None:
    record_continuity_outcome(_outcome_request())
    upsert_continuity_notification_state(
        "planning:41:checkpoint:0",
        ContinuityNotificationStateUpsertRequest(
            inboxed_at_utc="2026-03-21T12:01:00Z",
            seen_at_utc="2026-03-21T12:02:00Z",
            suppressed_until_utc="2026-03-21T13:00:00Z",
        ),
    )
    upsert_continuity_notification_state(
        "planning:41:checkpoint:0",
        ContinuityNotificationStateUpsertRequest(
            acknowledged_at_utc="2026-03-21T12:03:00Z",
        ),
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.notification_records[0].state.inboxed_at_utc == "2026-03-21T12:01:00Z"
    assert snapshot.notification_records[0].state.seen_at_utc == "2026-03-21T12:02:00Z"
    assert snapshot.notification_records[0].state.acknowledged_at_utc == "2026-03-21T12:03:00Z"
    assert snapshot.notification_records[0].state.suppressed_until_utc == "2026-03-21T13:00:00Z"


def test_delivery_inspection_returns_record_state_and_reason(tmp_data_dir: Path) -> None:
    record_continuity_outcome(_outcome_request())
    upsert_continuity_notification_state(
        "planning:41:checkpoint:0",
        ContinuityNotificationStateUpsertRequest(
            inboxed_at_utc="2026-03-21T12:01:00Z",
            seen_at_utc="2026-03-21T12:02:00Z",
        ),
    )

    inspection = read_continuity_delivery_inspection(limit=1, channel="all")

    assert inspection.channel == "all"
    assert inspection.limit == 1
    assert inspection.truncated is False
    assert inspection.continuation is None
    assert inspection.decisions[0].reason == "sent"
    assert inspection.decisions[0].record.id == "planning:41:checkpoint:0"
    assert inspection.decisions[0].record.state.inboxed_at_utc == "2026-03-21T12:01:00Z"
    assert inspection.decisions[0].record.state.seen_at_utc == "2026-03-21T12:02:00Z"
    assert inspection.decisions[0].resend_ready_at_utc is None
    assert inspection.decisions[0].latest_push_delivery is None


def test_delivery_inspection_joins_latest_scheduler_push_delivery(tmp_data_dir: Path) -> None:
    notification_id = "planning:41:checkpoint:0"
    record_continuity_outcome(
        _outcome_request(
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
        )
    )
    insert_scheduler_push_delivery(
        notification_id=notification_id,
        workflow_thread_id=notification_id,
        delivery_status="skipped",
        delivery_reason="notification_missing",
        push_count=0,
    )

    inspection = read_continuity_delivery_inspection(limit=1, channel="push")

    assert inspection.decisions[0].reason == "sent"
    assert inspection.decisions[0].latest_push_delivery is not None
    assert inspection.decisions[0].latest_push_delivery.slot_key == "2026-03-21T12:00:00Z"
    assert inspection.decisions[0].latest_push_delivery.delivery_status == "skipped"
    assert inspection.decisions[0].latest_push_delivery.delivery_reason == "notification_missing"
    assert inspection.decisions[0].latest_push_delivery.push_count == 0


def test_delivery_inspection_returns_resend_ready_at_for_push_cooldown(tmp_data_dir: Path) -> None:
    notification_id = "planning:41:checkpoint:0"
    record_continuity_outcome(
        _outcome_request(
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
        )
    )
    inboxed_at = (datetime.now(UTC) - timedelta(hours=2)).replace(microsecond=0)
    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            inboxed_at_utc=inboxed_at.isoformat().replace("+00:00", "Z"),
        ),
    )

    inspection = read_continuity_delivery_inspection(limit=1, channel="push")

    assert inspection.decisions[0].reason == "cooled_down"
    assert inspection.decisions[0].resend_ready_at_utc == (
        inboxed_at + timedelta(hours=6)
    ).isoformat().replace("+00:00", "Z")


def test_snapshot_clears_expired_notification_suppression(tmp_data_dir: Path) -> None:
    record_continuity_outcome(_outcome_request())
    upsert_continuity_notification_state(
        "planning:41:checkpoint:0",
        ContinuityNotificationStateUpsertRequest(
            suppressed_until_utc="2026-03-21T11:00:00Z",
        ),
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.notification_records[0].state.suppressed_until_utc is None

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT suppressed_until_utc "
            "FROM continuity_notification_states WHERE notification_id = ?",
            ("planning:41:checkpoint:0",),
        ).fetchone()

    assert row is not None
    assert row["suppressed_until_utc"] is None


def test_snapshot_drops_retired_terminal_notification_state(tmp_data_dir: Path) -> None:
    notification_id = "planning:41:checkpoint:0"
    record_continuity_outcome(_outcome_request(occurred_at_utc="2026-03-21T12:00:00Z"))
    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            acknowledged_at_utc="2026-03-21T12:03:00Z",
        ),
    )
    record_continuity_outcome(
        _outcome_request(
            label="Refreshed planning thread",
            description="The plan changed again.",
            occurred_at_utc="2026-03-21T12:20:00Z",
            dedupe_key="planning::queue-2",
        )
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.notification_records[0].state.acknowledged_at_utc is None

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT 1 FROM continuity_notification_states WHERE notification_id = ?",
            (notification_id,),
        ).fetchone()

    assert row is None


def test_snapshot_drops_orphaned_notification_state(tmp_data_dir: Path) -> None:
    upsert_continuity_notification_state(
        "planning:999",
        ContinuityNotificationStateUpsertRequest(
            inboxed_at_utc="2026-03-21T12:01:00Z",
        ),
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.notification_records == []

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT 1 FROM continuity_notification_states WHERE notification_id = ?",
            ("planning:999",),
        ).fetchone()

    assert row is None


def test_push_notification_reads_respect_delivery_cooldowns(tmp_data_dir: Path) -> None:
    record_continuity_outcome(
        _outcome_request(
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
        )
    )
    notification_id = "planning:41:checkpoint:0"
    now = datetime.now(UTC).replace(microsecond=0)

    assert read_continuity_notification_records(channel="push")[0].id == notification_id
    assert _push_delivery_reasons() == ["sent"]

    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            inboxed_at_utc=(now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        ),
    )
    assert read_continuity_notification_records(channel="push") == []
    assert _push_delivery_reasons() == ["cooled_down"]

    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            inboxed_at_utc=(now - timedelta(hours=7)).isoformat().replace("+00:00", "Z"),
        ),
    )
    assert read_continuity_notification_records(channel="push")[0].id == notification_id
    assert _push_delivery_reasons() == ["sent"]

    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            seen_at_utc=(now - timedelta(hours=12)).isoformat().replace("+00:00", "Z"),
        ),
    )
    assert read_continuity_notification_records(channel="push") == []
    assert _push_delivery_reasons() == ["cooled_down"]

    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            seen_at_utc=(now - timedelta(hours=25)).isoformat().replace("+00:00", "Z"),
        ),
    )
    assert read_continuity_notification_records(channel="push")[0].id == notification_id
    assert _push_delivery_reasons() == ["sent"]

    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            suppressed_until_utc=(now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        ),
    )
    assert read_continuity_notification_records(channel="push") == []
    assert _push_delivery_reasons() == ["suppressed"]

    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            suppressed_until_utc=(now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        ),
    )
    assert read_continuity_notification_records(channel="push")[0].id == notification_id
    assert _push_delivery_reasons() == ["sent"]

    upsert_continuity_notification_state(
        notification_id,
        ContinuityNotificationStateUpsertRequest(
            acknowledged_at_utc=now.isoformat().replace("+00:00", "Z"),
        ),
    )
    assert read_continuity_notification_records(channel="push") == []
    assert _push_delivery_reasons() == ["acknowledged"]


def test_push_delivery_marks_missing_targets(tmp_data_dir: Path) -> None:
    record_continuity_outcome(
        _outcome_request(
            launch_location=None,
            resume_location=ContinuityLocationResponse(state="do", loop_id=999),
            dedupe_key="missing::target",
            workflow_thread_id="loop:999",
        )
    )

    assert read_continuity_notification_records(channel="push") == []
    assert _push_delivery_reasons() == ["missing_target"]


def test_push_delivery_reasons_cover_deduped_and_skipped_records(tmp_data_dir: Path) -> None:
    shared_location = ContinuityLocationResponse(state="recall", recall_tool="chat")
    record_continuity_outcome(
        _outcome_request(
            label="Newest recall path",
            occurred_at_utc="2026-03-21T12:20:00Z",
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=shared_location,
            dedupe_key="planning::shared-a",
            workflow_thread_id="planning:shared-a",
        )
    )
    record_continuity_outcome(
        _outcome_request(
            label="Duplicate recall path",
            occurred_at_utc="2026-03-21T12:10:00Z",
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=shared_location,
            dedupe_key="planning::shared-b",
            workflow_thread_id="planning:shared-b",
        )
    )
    record_continuity_outcome(
        _outcome_request(
            label="Older distinct path",
            occurred_at_utc="2026-03-21T12:00:00Z",
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=ContinuityLocationResponse(state="recall", recall_tool="memory"),
            dedupe_key="planning::distinct",
            workflow_thread_id="planning:distinct",
        )
    )

    records = read_continuity_notification_records(channel="push", limit=1)

    assert [record.id for record in records] == ["planning:shared-a"]
    assert _push_delivery_reasons(limit=1) == ["sent", "deduped", "skipped"]


def test_push_delivery_scan_walks_to_later_sendable_notification(tmp_data_dir: Path) -> None:
    base_time = datetime(2026, 3, 21, 12, 59, tzinfo=UTC)
    for index in range(25):
        notification_id = f"planning:window-{index:02d}"
        record_continuity_outcome(
            _outcome_request(
                label=f"Window {index:02d}",
                occurred_at_utc=(base_time - timedelta(minutes=index))
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                launch_location=ContinuityLocationResponse(state="operator"),
                resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
                dedupe_key=f"planning::window-{index:02d}",
                workflow_thread_id=notification_id,
            )
        )
        if index < 24:
            upsert_continuity_notification_state(
                notification_id,
                ContinuityNotificationStateUpsertRequest(
                    inboxed_at_utc=(datetime.now(UTC) - timedelta(hours=2))
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                ),
            )

    records = read_continuity_notification_records(channel="push", limit=1)
    inspection = read_continuity_delivery_inspection(limit=1, channel="push")

    assert [record.id for record in records] == ["planning:window-24"]
    assert inspection.truncated is False
    assert inspection.continuation is None
    assert len(inspection.decisions) == 25
    assert [decision.record.id for decision in inspection.decisions[-1:]] == ["planning:window-24"]
    assert inspection.decisions[-1].reason == "sent"
    assert {decision.reason for decision in inspection.decisions[:-1]} == {"cooled_down"}


def test_push_delivery_scan_budget_stays_bounded_when_later_sendable_is_too_deep(
    tmp_data_dir: Path,
) -> None:
    base_time = datetime(2026, 3, 21, 12, 59, tzinfo=UTC)
    for index in range(97):
        notification_id = f"planning:deep-window-{index:02d}"
        record_continuity_outcome(
            _outcome_request(
                label=f"Deep window {index:02d}",
                occurred_at_utc=(base_time - timedelta(minutes=index))
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                launch_location=ContinuityLocationResponse(state="operator"),
                resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
                dedupe_key=f"planning::deep-window-{index:02d}",
                workflow_thread_id=notification_id,
            )
        )
        if index < 96:
            upsert_continuity_notification_state(
                notification_id,
                ContinuityNotificationStateUpsertRequest(
                    inboxed_at_utc=(datetime.now(UTC) - timedelta(hours=2))
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                ),
            )

    records = read_continuity_notification_records(channel="push", limit=1)
    inspection = read_continuity_delivery_inspection(limit=1, channel="push")

    assert records == []
    assert inspection.truncated is True
    assert inspection.continuation is not None
    assert len(inspection.decisions) == 96
    assert {decision.reason for decision in inspection.decisions} == {"cooled_down"}

    resumed = read_continuity_delivery_inspection(
        limit=1,
        channel="push",
        cursor=inspection.continuation.cursor,
    )

    assert resumed.truncated is False
    assert resumed.continuation is None
    assert [decision.record.id for decision in resumed.decisions] == ["planning:deep-window-96"]
    assert {decision.reason for decision in resumed.decisions} == {"sent"}


def test_delivery_inspection_cursor_stays_stable_across_concurrent_inserts(
    tmp_data_dir: Path,
) -> None:
    for label, occurred_at_utc in (
        ("Newest", "2026-03-21T12:03:00Z"),
        ("Middle", "2026-03-21T12:02:00Z"),
        ("Oldest", "2026-03-21T12:01:00Z"),
    ):
        record_continuity_outcome(
            _outcome_request(
                label=label,
                occurred_at_utc=occurred_at_utc,
                launch_location=ContinuityLocationResponse(state="operator"),
                resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
                dedupe_key=f"planning::{label.lower()}",
                workflow_thread_id=f"planning:{label.lower()}",
            )
        )

    first_page = read_continuity_delivery_inspection(limit=2, channel="all")

    assert [decision.record.id for decision in first_page.decisions] == [
        "planning:newest",
        "planning:middle",
    ]
    assert first_page.continuation is not None

    record_continuity_outcome(
        _outcome_request(
            label="New Head",
            occurred_at_utc="2026-03-21T12:04:00Z",
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
            dedupe_key="planning::new-head",
            workflow_thread_id="planning:new-head",
        )
    )
    record_continuity_outcome(
        _outcome_request(
            label="Backfilled",
            occurred_at_utc="2026-03-21T12:01:30Z",
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
            dedupe_key="planning::backfilled",
            workflow_thread_id="planning:backfilled",
        )
    )

    second_page = read_continuity_delivery_inspection(
        limit=2,
        channel="all",
        cursor=first_page.continuation.cursor,
    )

    assert second_page.truncated is False
    assert second_page.continuation is None
    assert [decision.record.id for decision in second_page.decisions] == ["planning:oldest"]


def test_delivery_inspection_cursor_rejects_query_mismatch(tmp_data_dir: Path) -> None:
    for label, occurred_at_utc in (
        ("Newest", "2026-03-21T12:03:00Z"),
        ("Older", "2026-03-21T12:02:00Z"),
    ):
        record_continuity_outcome(
            _outcome_request(
                label=label,
                occurred_at_utc=occurred_at_utc,
                launch_location=ContinuityLocationResponse(state="operator"),
                resume_location=ContinuityLocationResponse(state="recall", recall_tool="chat"),
                dedupe_key=f"planning::{label.lower()}",
                workflow_thread_id=f"planning:{label.lower()}",
            )
        )

    inspection = read_continuity_delivery_inspection(limit=1, channel="all")
    assert inspection.continuation is not None

    with pytest.raises(ValidationError, match="cursor does not match this query"):
        read_continuity_delivery_inspection(
            limit=1,
            channel="push",
            cursor=inspection.continuation.cursor,
        )


def test_snapshot_resolves_missing_working_set_scope_to_unscoped_target(tmp_data_dir: Path) -> None:
    _insert_loop(tmp_data_dir, loop_id=11)
    record_continuity_outcome(
        _outcome_request(
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=ContinuityLocationResponse(
                state="do",
                loop_id=11,
                working_set_id=99,
            ),
            dedupe_key="loop::11",
        )
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.outcomes[0].resolved_resume.status == "working_set_scope_removed"
    assert snapshot.outcomes[0].resolved_resume.resolved_location.loop_id == 11
    assert snapshot.outcomes[0].resolved_resume.resolved_location.working_set_id is None
    assert snapshot.outcomes[0].degraded is True


def test_snapshot_falls_back_to_launch_then_home_when_targets_are_missing(
    tmp_data_dir: Path,
) -> None:
    record_continuity_outcome(
        _outcome_request(
            label="Missing plan target",
            launch_location=ContinuityLocationResponse(state="operator"),
            resume_location=ContinuityLocationResponse(
                state="plan", review_focus="planning", session_id=999
            ),
            dedupe_key="missing::launch",
        )
    )
    record_continuity_outcome(
        _outcome_request(
            label="Missing everything",
            launch_location=ContinuityLocationResponse(state="capture", view_id=999),
            resume_location=ContinuityLocationResponse(
                state="plan", review_focus="planning", session_id=998
            ),
            dedupe_key="missing::home",
            workflow_thread_id="planning:98",
        )
    )

    snapshot = read_continuity_snapshot()
    by_label = {item.label: item for item in snapshot.outcomes}
    assert by_label["Missing plan target"].resolved_resume.status == "launch_fallback"
    assert by_label["Missing plan target"].resolved_resume.resolved_location.state == "operator"
    assert by_label["Missing everything"].resolved_resume.status == "home_fallback"
    assert by_label["Missing everything"].resolved_resume.resolved_location.state == "operator"


def test_upsert_last_seen_markers_round_trips(tmp_data_dir: Path) -> None:
    upsert_continuity_last_seen_markers(
        ContinuityLastSeenBatchUpsertRequest(
            markers=[
                ContinuityLastSeenMarkerUpsertRequest(
                    entity_kind="planning_session",
                    entity_key="planning:41",
                    observed_at_utc="2026-03-21T12:10:00Z",
                    observed_fingerprint='{"status":"in_progress"}',
                    working_set_id=None,
                    workflow_thread_id="planning:41",
                    observed_state={"status": "in_progress", "latestOutcomeId": 5},
                    metadata={},
                )
            ]
        )
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.last_seen_markers[0].entity_key == "planning:41"
    assert snapshot.last_seen_markers[0].workflow_thread_id == "planning:41"
    assert snapshot.last_seen_markers[0].observed_state["latestOutcomeId"] == 5


def test_snapshot_emits_backend_successor_for_superseded_planning_outcome(
    tmp_data_dir: Path,
) -> None:
    insert_planning_session(99, name="Replacement plan")

    record_continuity_outcome(
        _outcome_request(
            label="Old plan",
            description="The prior planning path.",
            occurred_at_utc="2026-03-21T12:00:00Z",
            resume_location=ContinuityLocationResponse(
                state="plan",
                review_focus="planning",
                session_id=41,
            ),
            dedupe_key="planning::41",
            workflow_thread_id="planning:41",
        )
    )
    record_continuity_outcome(
        _outcome_request(
            label="Replacement plan",
            description="The refreshed planning path.",
            occurred_at_utc="2026-03-21T12:05:00Z",
            resume_location=ContinuityLocationResponse(
                state="plan",
                review_focus="planning",
                session_id=99,
            ),
            dedupe_key="planning::99",
            workflow_thread_id="planning:99",
        )
    )

    snapshot = read_continuity_snapshot()
    by_label = {item.label: item for item in snapshot.outcomes}

    successor = by_label["Old plan"].resolved_resume.successor
    assert successor is not None
    assert successor.kind == "replacement"
    assert successor.title == "Replacement plan"
    assert successor.resolved_location.session_id == 99
    assert snapshot.workflow_summaries[0].workflow_thread.id == "planning:99"
    assert snapshot.workflow_summaries[0].why_now
    assert snapshot.workflow_summaries[0].changed_since_last_seen
    assert snapshot.notification_records[0].id == "planning:99"


def test_recovery_acknowledgement_round_trips(tmp_data_dir: Path) -> None:
    upsert_continuity_recovery_acknowledgement(
        ContinuityRecoveryAcknowledgementUpsertRequest(
            recovery_key="replacement::planning:41::location:null::plan|chat|planning|99|-|-|-|-|-",
            acknowledged_at_utc="2026-03-21T12:06:00Z",
            metadata={},
        )
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.recovery_acknowledgements[0].recovery_key.startswith("replacement::")
