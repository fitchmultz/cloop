"""Durable continuity storage regression tests.

Purpose:
    Verify backend-backed continuity outcomes, anchors, workflow summaries, and
    fallback resolution stay stable as cross-device continuity evolves.

Responsibilities:
    - Assert durable continuity tables exist through the public DB bootstrap.
    - Guard outcome deduplication and backend-authored workflow summaries.
    - Verify explicit degraded fallback behavior for missing working-set scope and targets.
    - Confirm planning/review anchors persist through the snapshot surface.

Non-scope:
    - Frontend ranking or rendering behavior.
    - Browser-local continuity baseline snapshots.

Usage:
    Run with `uv run --locked pytest tests/test_continuity_store.py`.

Invariants/Assumptions:
    - Tests use isolated SQLite databases via `tmp_data_dir`.
    - Continuity persistence goes through public storage helpers.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from conftest import insert_planning_session

from cloop import db
from cloop.schemas._loops.continuity import (
    ContinuityAnchorUpsertRequest,
    ContinuityLastSeenBatchUpsertRequest,
    ContinuityLastSeenMarkerUpsertRequest,
    ContinuityLocationResponse,
    ContinuityNotificationStateUpsertRequest,
    ContinuityOutcomeWriteRequest,
    ContinuityRecoveryAcknowledgementUpsertRequest,
    WorkflowThreadRefResponse,
)
from cloop.settings import get_settings
from cloop.storage.continuity_store import (
    read_continuity_notification_records,
    read_continuity_snapshot,
    record_continuity_outcome,
    upsert_continuity_anchor,
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


def _outcome_request(
    *,
    label: str = "Created review queue",
    description: str = "The downstream queue is ready.",
    occurred_at_utc: str = "2026-03-21T12:00:00Z",
    launch_location: ContinuityLocationResponse | None = None,
    resume_location: ContinuityLocationResponse | None = None,
    dedupe_key: str = "planning::queue",
    workflow_thread_id: str = "planning:41:checkpoint:0",
) -> ContinuityOutcomeWriteRequest:
    return ContinuityOutcomeWriteRequest(
        kind="planning",
        label=label,
        description=description,
        occurred_at_utc=occurred_at_utc,
        launch_location=launch_location,
        outcome_card={
            "id": f"receipt-{label.lower().replace(' ', '-')}",
            "kind": "receipt",
            "tone": "progress",
            "eyebrow": "Planning receipt",
            "title": label,
            "summary": description,
            "rationale": "Receipt",
            "preview": [],
            "trust": {
                "contextSources": ["Planning session"],
                "assumptions": [],
                "confidenceLabel": "Recorded",
                "freshnessLabel": "Saved just now",
                "rollbackLabel": "Undo remains available.",
            },
            "handoff": None,
            "actions": [],
        },
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


def test_continuity_tables_exist(tmp_data_dir: Path) -> None:
    with closing(sqlite3.connect(get_settings().core_db_path)) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?, ?)",
                (
                    "continuity_outcomes",
                    "continuity_resume_anchors",
                    "continuity_notification_states",
                    "continuity_recovery_acknowledgements",
                ),
            ).fetchall()
        }
    assert table_names == {
        "continuity_outcomes",
        "continuity_resume_anchors",
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


def test_push_notification_reads_skip_inboxed_or_seen_records(tmp_data_dir: Path) -> None:
    record_continuity_outcome(_outcome_request())
    assert read_continuity_notification_records(channel="push")[0].id == "planning:41:checkpoint:0"

    upsert_continuity_notification_state(
        "planning:41:checkpoint:0",
        ContinuityNotificationStateUpsertRequest(
            inboxed_at_utc="2026-03-21T12:01:00Z",
        ),
    )
    assert read_continuity_notification_records(channel="push") == []


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


def test_upsert_continuity_anchor_round_trips(tmp_data_dir: Path) -> None:
    upsert_continuity_anchor(
        ContinuityAnchorUpsertRequest(
            anchor_kind="planning",
            review_focus="planning",
            session_id=41,
            visited_at_utc="2026-03-21T12:00:00Z",
            launch_location=ContinuityLocationResponse(
                state="plan", review_focus="planning", session_id=41
            ),
            resume_location=ContinuityLocationResponse(
                state="plan", review_focus="planning", session_id=41
            ),
            outcome_title="Resume weekly reset",
            outcome_summary="Continue the saved planning session.",
            working_set_id=None,
            workflow_thread_id="planning:41",
            metadata={},
        )
    )
    upsert_continuity_anchor(
        ContinuityAnchorUpsertRequest(
            anchor_kind="review",
            review_focus="enrichment",
            session_id=52,
            visited_at_utc="2026-03-21T12:05:00Z",
            launch_location=ContinuityLocationResponse(
                state="decide", review_focus="enrichment", session_id=52
            ),
            resume_location=ContinuityLocationResponse(
                state="decide", review_focus="enrichment", session_id=52
            ),
            outcome_title="Resume launch queue",
            outcome_summary="Continue the enrichment queue.",
            working_set_id=7,
            workflow_thread_id="review:enrichment:52",
            metadata={},
        )
    )

    snapshot = read_continuity_snapshot()
    assert snapshot.anchors.planning is not None
    assert snapshot.anchors.planning.workflow_thread_id == "planning:41"
    assert snapshot.anchors.review is not None
    assert snapshot.anchors.review.session_id == 52
    assert snapshot.anchors.review.working_set_id == 7


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


def test_anchor_carries_backend_successor_provenance(tmp_data_dir: Path) -> None:
    insert_planning_session(99, name="Replacement plan")

    upsert_continuity_anchor(
        ContinuityAnchorUpsertRequest(
            anchor_kind="planning",
            review_focus="planning",
            session_id=41,
            visited_at_utc="2026-03-21T12:00:00Z",
            launch_location=ContinuityLocationResponse(
                state="plan", review_focus="planning", session_id=41
            ),
            resume_location=ContinuityLocationResponse(
                state="plan", review_focus="planning", session_id=41
            ),
            outcome_title="Old plan",
            outcome_summary="Prior planning path.",
            workflow_thread_id="planning:41",
            metadata={},
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
    assert snapshot.anchors.planning is not None
    assert snapshot.anchors.planning.resolved_resume is not None
    assert snapshot.anchors.planning.resolved_resume.successor is not None
    assert snapshot.anchors.planning.resolved_resume.successor.resolved_location.session_id == 99
    assert snapshot.workflow_summaries[0].prior_state is not None


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
