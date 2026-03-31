"""Tests for shared saved review actions and review sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.loops import enrichment_review, repo, review_workflows, service, working_sets
from cloop.loops.errors import ValidationError
from cloop.loops.models import LoopStatus
from cloop.settings import Settings, get_settings

VECTORS = {
    "buy milk and eggs before the weekend": np.array([1.0, 0.0, 0.0], dtype=np.float32),
    "pick up groceries like milk and eggs": np.array([0.99, 0.01, 0.0], dtype=np.float32),
    "draft launch email for beta users": np.array([0.0, 1.0, 0.0], dtype=np.float32),
    "write beta launch email draft": np.array([0.0, 0.99, 0.01], dtype=np.float32),
}


def _setup_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _mock_relationship_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        inputs = kwargs.get("input") or []
        data: list[dict[str, list[float]]] = []
        for text in inputs:
            lowered = str(text).lower()
            vector = np.array([0.1, 0.1, 0.1], dtype=np.float32)
            for key, mapped in VECTORS.items():
                if key in lowered:
                    vector = mapped.copy()
                    break
            vector /= np.linalg.norm(vector)
            data.append({"embedding": vector.tolist()})
        return {"data": data}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)


def _capture_loop(raw_text: str, *, status: LoopStatus, conn: Any) -> dict[str, Any]:
    return service.capture_loop(
        raw_text=raw_text,
        captured_at_iso="2026-03-14T12:00:00+00:00",
        client_tz_offset_min=0,
        status=status,
        conn=conn,
    )


def _assert_review_follow_through_contract(
    follow_through: dict[str, Any],
    *,
    review_focus: str,
    session_id: int,
) -> None:
    assert follow_through["resume_location"]["state"] == "decide"
    assert follow_through["resume_location"]["review_focus"] == review_focus
    assert follow_through["resume_location"]["session_id"] == session_id
    assert follow_through["workflow_thread"]["kind"] == "review_session"
    assert follow_through["workflow_thread"]["id"] == f"review:{review_focus}:session:{session_id}"
    assert follow_through["grounded_chat_location"]["state"] == "recall"
    assert follow_through["grounded_chat_location"]["recall_tool"] == "chat"
    assert follow_through["grounded_chat_location"]["query"]
    assert follow_through["grounded_chat_location"]["include_loop_context"] is True
    assert follow_through["rerun_action"]["rerun"]["kind"] == "review_session"
    assert follow_through["rerun_action"]["rerun"]["review_focus"] == review_focus
    assert follow_through["rerun_action"]["rerun"]["session_id"] == session_id


def test_relationship_review_session_advances_after_resolving_current_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
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
        third_loop = _capture_loop(
            "Draft launch email for beta users",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        fourth_loop = _capture_loop(
            "Write beta launch email draft",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        conn.commit()

        action = review_workflows.create_relationship_review_action(
            name="dismiss-current-match",
            action_type="dismiss",
            relationship_type="suggested",
            description="Dismiss the current suggested relationship",
            conn=conn,
        )
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

        assert snapshot["session"]["current_loop_id"] == first_loop["id"]
        assert snapshot["current_item"]["loop"]["id"] == first_loop["id"]
        assert snapshot["rerun_action"]["rerun"]["kind"] == "review_session"
        assert snapshot["rerun_action"]["rerun"]["review_focus"] == "relationship"

        after = review_workflows.execute_relationship_review_session_action(
            session_id=snapshot["session"]["id"],
            loop_id=first_loop["id"],
            candidate_loop_id=second_loop["id"],
            candidate_relationship_type="duplicate",
            action_preset_id=action["id"],
            action_type=None,
            relationship_type=None,
            conn=conn,
            settings=settings,
        )

    assert after["result"]["link_state"] == "dismissed"
    _assert_review_follow_through_contract(
        after["follow_through"],
        review_focus="relationship",
        session_id=snapshot["session"]["id"],
    )
    assert after["follow_through"]["display_card"]["eyebrow"] == "Relationship receipt"
    assert after["follow_through"]["undo_action"]["undo"]["kind"] == "relationship_decision"
    remaining_loop_ids = {item["loop"]["id"] for item in after["snapshot"]["items"]}
    assert third_loop["id"] in remaining_loop_ids or fourth_loop["id"] in remaining_loop_ids
    assert after["snapshot"]["session"]["current_loop_id"] in remaining_loop_ids
    assert first_loop["id"] not in remaining_loop_ids
    assert second_loop["id"] not in remaining_loop_ids


def test_relationship_review_session_action_can_be_undone_with_exact_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
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
        undo_handle = after["follow_through"]["undo_action"]["undo"]

        restored = review_workflows.undo_relationship_review_session_action(
            session_id=snapshot["session"]["id"],
            loop_id=undo_handle["loop_id"],
            candidate_loop_id=undo_handle["candidate_loop_id"],
            expected_pair_state=undo_handle["expected_pair_state"],
            restore_pair_state=undo_handle["restore_pair_state"],
            conn=conn,
            settings=settings,
        )

    assert restored["result"]["summary"]
    assert restored["follow_through"]["undo_action"] is None
    restored_items = {
        item["loop"]["id"]: {candidate["id"] for candidate in item["duplicate_candidates"]}
        for item in restored["snapshot"]["items"]
    }
    assert first_loop["id"] in restored_items
    assert second_loop["id"] in restored_items
    assert second_loop["id"] in restored_items[first_loop["id"]]
    assert first_loop["id"] in restored_items[second_loop["id"]]


def test_review_session_move_helpers_step_through_saved_cursors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_relationship_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        rel_first = _capture_loop(
            "Buy milk and eggs before the weekend",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        _capture_loop(
            "Pick up groceries like milk and eggs",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        _capture_loop(
            "Draft launch email for beta users",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        _capture_loop(
            "Write beta launch email draft",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )

        enrich_first = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)
        enrich_second = _capture_loop(
            "Clarify owner for launch", status=LoopStatus.INBOX, conn=conn
        )
        repo.insert_loop_suggestion(
            loop_id=enrich_first["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=enrich_first["id"],
            question="When should this happen?",
            conn=conn,
        )
        repo.insert_loop_suggestion(
            loop_id=enrich_second["id"],
            suggestion_json={"needs_clarification": ["Who owns this?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=enrich_second["id"],
            question="Who owns this?",
            conn=conn,
        )
        conn.commit()

        relationship_session = review_workflows.create_relationship_review_session(
            name="move-rel",
            query="status:open",
            relationship_kind="duplicate",
            candidate_limit=3,
            item_limit=25,
            current_loop_id=rel_first["id"],
            conn=conn,
            settings=settings,
        )
        enrichment_session = review_workflows.create_enrichment_review_session(
            name="move-enrich",
            query="status:open",
            pending_kind="clarifications",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=enrich_first["id"],
            conn=conn,
        )
        assert enrichment_session["rerun_action"]["rerun"]["kind"] == "review_session"
        assert enrichment_session["rerun_action"]["rerun"]["review_focus"] == "enrichment"

        relationship_direction = (
            "next" if relationship_session["current_index"] == 0 else "previous"
        )
        relationship_step = 1 if relationship_direction == "next" else -1
        relationship_target = relationship_session["items"][
            relationship_session["current_index"] + relationship_step
        ]["loop"]["id"]
        moved_relationship = review_workflows.move_relationship_review_session(
            session_id=relationship_session["session"]["id"],
            direction=relationship_direction,
            conn=conn,
            settings=settings,
        )
        enrichment_direction = "next" if enrichment_session["current_index"] == 0 else "previous"
        enrichment_step = 1 if enrichment_direction == "next" else -1
        enrichment_target = enrichment_session["items"][
            enrichment_session["current_index"] + enrichment_step
        ]["loop"]["id"]
        moved_enrichment = review_workflows.move_enrichment_review_session(
            session_id=enrichment_session["session"]["id"],
            direction=enrichment_direction,
            conn=conn,
        )

    assert moved_relationship["session"]["current_loop_id"] == relationship_target
    assert moved_relationship["current_item"]["loop"]["id"] == relationship_target
    assert moved_enrichment["session"]["current_loop_id"] == enrichment_target
    assert moved_enrichment["current_item"]["loop"]["id"] == enrichment_target


def test_review_session_refresh_helpers_rebuild_saved_queues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_relationship_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        rel_first = _capture_loop(
            "Buy milk and eggs before the weekend",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        _capture_loop(
            "Pick up groceries like milk and eggs",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        enrich_first = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)
        repo.insert_loop_suggestion(
            loop_id=enrich_first["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=enrich_first["id"],
            question="When should this happen?",
            conn=conn,
        )
        conn.commit()

        relationship_session = review_workflows.create_relationship_review_session(
            name="refresh-rel",
            query="status:open",
            relationship_kind="duplicate",
            candidate_limit=3,
            item_limit=25,
            current_loop_id=rel_first["id"],
            conn=conn,
            settings=settings,
        )
        enrichment_session = review_workflows.create_enrichment_review_session(
            name="refresh-enrich",
            query="status:open",
            pending_kind="clarifications",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=enrich_first["id"],
            conn=conn,
        )

        _capture_loop(
            "Draft launch email for beta users",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        _capture_loop(
            "Write beta launch email draft",
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        enrich_second = _capture_loop(
            "Clarify owner for launch", status=LoopStatus.INBOX, conn=conn
        )
        repo.insert_loop_suggestion(
            loop_id=enrich_second["id"],
            suggestion_json={"needs_clarification": ["Who owns this?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=enrich_second["id"],
            question="Who owns this?",
            conn=conn,
        )
        conn.commit()

        refreshed_relationship = review_workflows.refresh_relationship_review_session(
            session_id=relationship_session["session"]["id"],
            conn=conn,
            settings=settings,
        )
        refreshed_enrichment = review_workflows.refresh_enrichment_review_session(
            session_id=enrichment_session["session"]["id"],
            conn=conn,
        )

    assert refreshed_relationship["session"]["id"] == relationship_session["session"]["id"]
    assert refreshed_relationship["loop_count"] >= relationship_session["loop_count"]
    assert refreshed_relationship["session"]["current_loop_id"] in {
        item["loop"]["id"] for item in refreshed_relationship["items"]
    }
    assert refreshed_enrichment["session"]["id"] == enrichment_session["session"]["id"]
    assert refreshed_enrichment["loop_count"] == 2
    assert refreshed_enrichment["session"]["current_loop_id"] in {
        item["loop"]["id"] for item in refreshed_enrichment["items"]
    }


def test_enrichment_review_session_can_attach_to_and_cleanup_from_working_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop_record = _capture_loop(
            "Clarify launch date",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        repo.insert_loop_suggestion(
            loop_id=loop_record["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        repo.insert_loop_clarification(
            loop_id=loop_record["id"],
            question="When should this happen?",
            conn=conn,
        )
        working_set = working_sets.create_working_set(
            name="Launch review",
            description="Keep launch review work bounded.",
            conn=conn,
        )

        snapshot = review_workflows.create_enrichment_review_session(
            name="launch-enrich",
            query="status:open",
            pending_kind="clarifications",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=loop_record["id"],
            conn=conn,
            working_set_id=working_set["id"],
        )

        attached = working_sets.get_working_set(working_set_id=working_set["id"], conn=conn)
        assert [item["item_type"] for item in attached["items"]] == ["enrichment_review_session"]
        assert attached["items"][0]["item_id"] == snapshot["session"]["id"]
        assert attached["items"][0]["launch"]["working_set_id"] == working_set["id"]

        deleted = review_workflows.delete_enrichment_review_session(
            session_id=snapshot["session"]["id"],
            conn=conn,
        )
        assert deleted == {"deleted": True, "session_id": snapshot["session"]["id"]}

        cleaned = working_sets.get_working_set(working_set_id=working_set["id"], conn=conn)
        assert cleaned["items"] == []


@pytest.mark.parametrize(
    ("action_type", "expected_undo_kind"),
    (("apply", "loop_event"), ("reject", None)),
)
def test_enrichment_review_session_action_emits_complete_follow_through_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action_type: str,
    expected_undo_kind: str | None,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop_record = _capture_loop(
            "Plan Q2 launch retrospective",
            status=LoopStatus.INBOX,
            conn=conn,
        )
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop_record["id"],
            suggestion_json={
                "title": "Plan launch retrospective",
                "summary": "Define owner, agenda, and participants.",
                "confidence": {"title": 0.99, "summary": 0.94},
            },
            model="test-model",
            conn=conn,
        )
        conn.commit()

        action = review_workflows.create_enrichment_review_action(
            name=f"{action_type}-title-only",
            action_type=action_type,
            fields=["title"] if action_type == "apply" else None,
            description=f"{action_type.capitalize()} the queued suggestion",
            conn=conn,
        )
        snapshot = review_workflows.create_enrichment_review_session(
            name="pending-suggestions",
            query="status:open",
            pending_kind="suggestions",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=loop_record["id"],
            conn=conn,
        )

        assert snapshot["session"]["current_loop_id"] == loop_record["id"]
        assert snapshot["current_item"]["pending_suggestions"][0]["id"] == suggestion_id

        after = review_workflows.execute_enrichment_review_session_action(
            session_id=snapshot["session"]["id"],
            suggestion_id=suggestion_id,
            action_preset_id=action["id"],
            action_type=None,
            fields=None,
            conn=conn,
            settings=settings,
        )

        updated_loop = repo.read_loop(loop_id=loop_record["id"], conn=conn)

    assert after["result"]["suggestion_id"] == suggestion_id
    _assert_review_follow_through_contract(
        after["follow_through"],
        review_focus="enrichment",
        session_id=snapshot["session"]["id"],
    )
    assert after["follow_through"]["display_card"]["eyebrow"] == "Enrichment receipt"
    if expected_undo_kind is None:
        assert after["follow_through"]["undo_action"] is None
        assert (
            after["follow_through"]["display_card"]["trust"]["rollback_label"]
            == "Undo is not available for this enrichment outcome."
        )
    else:
        assert after["follow_through"]["undo_action"]["undo"]["kind"] == expected_undo_kind
    assert updated_loop is not None
    if action_type == "apply":
        assert after["result"]["applied_fields"] == ["title"]
        assert updated_loop.title == "Plan launch retrospective"
    else:
        assert updated_loop.title is None
    assert after["snapshot"]["loop_count"] == 0
    assert after["snapshot"]["session"]["current_loop_id"] is None


def test_create_enrichment_review_action_rejects_empty_apply_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        with pytest.raises(ValidationError, match="at least one suggestion field must be selected"):
            review_workflows.create_enrichment_review_action(
                name="empty-apply",
                action_type="apply",
                fields=[],
                description="Invalid empty apply action",
                conn=conn,
            )


def test_enrichment_review_session_action_rejects_empty_apply_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop_record = _capture_loop("Plan launch retrospective", status=LoopStatus.INBOX, conn=conn)
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop_record["id"],
            suggestion_json={
                "title": "Plan launch retrospective",
                "confidence": {"title": 0.99},
            },
            model="test-model",
            conn=conn,
        )
        conn.commit()

        snapshot = review_workflows.create_enrichment_review_session(
            name="pending-suggestions",
            query="status:open",
            pending_kind="suggestions",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=loop_record["id"],
            conn=conn,
        )

        with pytest.raises(ValidationError, match="at least one suggestion field must be selected"):
            review_workflows.execute_enrichment_review_session_action(
                session_id=snapshot["session"]["id"],
                suggestion_id=suggestion_id,
                action_preset_id=None,
                action_type="apply",
                fields=[],
                conn=conn,
                settings=settings,
            )


def test_enrichment_review_session_answers_clarifications_reruns_and_reenters_same_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
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
        second_loop = _capture_loop("Clarify owner for launch", status=LoopStatus.INBOX, conn=conn)

        first_suggestion_id = repo.insert_loop_suggestion(
            loop_id=first_loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        first_clarification_id = repo.insert_loop_clarification(
            loop_id=first_loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        second_suggestion_id = repo.insert_loop_suggestion(
            loop_id=second_loop["id"],
            suggestion_json={"needs_clarification": ["Who owns this?"]},
            model="test-model",
            conn=conn,
        )
        second_clarification_id = repo.insert_loop_clarification(
            loop_id=second_loop["id"],
            question="Who owns this?",
            conn=conn,
        )
        conn.commit()

        snapshot = review_workflows.create_enrichment_review_session(
            name="clarification-pass",
            query="status:open",
            pending_kind="all",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=first_loop["id"],
            conn=conn,
        )

        assert snapshot["session"]["current_loop_id"] == first_loop["id"]
        assert snapshot["current_item"]["pending_clarifications"][0]["id"] == first_clarification_id

        after = review_workflows.answer_enrichment_review_session_clarifications(
            session_id=snapshot["session"]["id"],
            loop_id=first_loop["id"],
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=first_clarification_id,
                    answer="Friday",
                )
            ],
            conn=conn,
            settings=settings,
        )

        answered_row = repo.read_loop_clarification(
            clarification_id=first_clarification_id,
            conn=conn,
        )
        remaining_pending = enrichment_review.list_loop_suggestions(
            loop_id=first_loop["id"],
            pending_only=True,
            conn=conn,
        )

    assert after["result"]["loop_id"] == first_loop["id"]
    _assert_review_follow_through_contract(
        after["follow_through"],
        review_focus="enrichment",
        session_id=snapshot["session"]["id"],
    )
    assert after["follow_through"]["display_card"]["eyebrow"] == "Enrichment receipt"
    assert after["follow_through"]["undo_action"] is None
    assert (
        after["follow_through"]["display_card"]["trust"]["rollback_label"]
        == "Undo is not available for this enrichment outcome."
    )
    assert after["result"]["clarification_result"]["answered_count"] == 1
    assert after["result"]["clarification_result"]["superseded_suggestion_ids"] == [
        first_suggestion_id
    ]
    assert after["result"]["enrichment_result"]["loop"]["id"] == first_loop["id"]
    assert after["result"]["enrichment_result"]["applied_fields"] == []
    assert after["result"]["enrichment_result"]["needs_clarification"] == []
    assert answered_row is not None
    assert answered_row["answer"] == "Friday"
    assert {suggestion["id"] for suggestion in remaining_pending} == {
        after["result"]["enrichment_result"]["suggestion_id"]
    }
    assert remaining_pending[0]["parsed"]["title"] == "Schedule launch date"
    remaining_loop_ids = {item["loop"]["id"] for item in after["snapshot"]["items"]}
    assert first_loop["id"] in remaining_loop_ids
    assert second_loop["id"] in remaining_loop_ids
    assert after["snapshot"]["session"]["current_loop_id"] == first_loop["id"]
    assert second_clarification_id in {
        clarification["id"]
        for item in after["snapshot"]["items"]
        for clarification in item.get("pending_clarifications", [])
    }
    assert (
        second_suggestion_id
        not in after["result"]["clarification_result"]["superseded_suggestion_ids"]
    )


def test_enrichment_review_session_failed_clarification_rerun_restores_retryable_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "cloop.loops.enrichment.chat_completion",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with db.core_connection(settings) as conn:
        loop_record = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop_record["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=loop_record["id"],
            question="When should this happen?",
            conn=conn,
        )
        snapshot = review_workflows.create_enrichment_review_session(
            name="clarification-pass",
            query="status:open",
            pending_kind="all",
            suggestion_limit=3,
            clarification_limit=3,
            item_limit=25,
            current_loop_id=loop_record["id"],
            conn=conn,
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="boom"):
            review_workflows.answer_enrichment_review_session_clarifications(
                session_id=snapshot["session"]["id"],
                loop_id=loop_record["id"],
                answers=[
                    enrichment_review.ClarificationAnswerInput(
                        clarification_id=clarification_id,
                        answer="Friday",
                    )
                ],
                conn=conn,
                settings=settings,
            )

        clarification = repo.read_loop_clarification(
            clarification_id=clarification_id,
            conn=conn,
        )
        pending = enrichment_review.list_loop_suggestions(
            loop_id=loop_record["id"],
            pending_only=True,
            conn=conn,
        )
        refreshed = review_workflows.get_enrichment_review_session(
            session_id=snapshot["session"]["id"],
            conn=conn,
        )

    assert clarification is not None
    assert clarification["answer"] is None
    assert [suggestion["id"] for suggestion in pending] == [suggestion_id]
    assert pending[0]["resolution"] is None
    assert refreshed["session"]["current_loop_id"] == loop_record["id"]
    assert refreshed["current_item"]["loop"]["id"] == loop_record["id"]
    assert refreshed["current_item"]["pending_clarifications"][0]["id"] == clarification_id


def test_submit_clarification_answers_rolls_back_if_supersede_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        conn.commit()

        original_resolve = enrichment_review.repo.resolve_loop_suggestion

        def fail_supersede(*, suggestion_id: int, resolution: str, **kwargs: Any) -> bool:
            if resolution == "superseded":
                return False
            return original_resolve(
                suggestion_id=suggestion_id,
                resolution=resolution,
                **kwargs,
            )

        monkeypatch.setattr(enrichment_review.repo, "resolve_loop_suggestion", fail_supersede)

        with pytest.raises(enrichment_review.ValidationError, match="could supersede it"):
            enrichment_review.submit_clarification_answers(
                loop_id=loop["id"],
                answers=[
                    enrichment_review.ClarificationAnswerInput(
                        clarification_id=clarification_id,
                        answer="Friday",
                    )
                ],
                conn=conn,
            )

        clarification = repo.read_loop_clarification(clarification_id=clarification_id, conn=conn)
        suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)

    assert clarification is not None
    assert clarification["answer"] is None
    assert suggestion is not None
    assert suggestion["resolution"] is None


def test_undo_clarification_answers_restores_unanswered_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)

        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        conn.commit()

        # Answer the clarification
        result = enrichment_review.submit_clarification_answers(
            loop_id=loop["id"],
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=clarification_id,
                    answer="Friday",
                )
            ],
            conn=conn,
        )
        assert result.answered_count == 1
        assert result.superseded_suggestion_ids == [suggestion_id]

        # Undo the answer
        undo_result = enrichment_review.undo_clarification_answers(
            loop_id=loop["id"],
            clarification_ids=[clarification_id],
            conn=conn,
        )
        assert undo_result.restored_count == 1
        assert undo_result.restored_clarification_ids == [clarification_id]
        assert undo_result.reopened_suggestion_ids == [suggestion_id]

        # Verify clarification is now unanswered
        clarification = repo.read_loop_clarification(clarification_id=clarification_id, conn=conn)
        assert clarification is not None
        assert clarification["answer"] is None
        assert clarification["answered_at"] is None

        # Verify suggestion is now pending again
        suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)
        assert suggestion is not None
        assert suggestion["resolution"] is None


def test_undo_clarification_answers_rolls_back_if_reopen_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        conn.commit()

        enrichment_review.submit_clarification_answers(
            loop_id=loop["id"],
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=clarification_id,
                    answer="Friday",
                )
            ],
            conn=conn,
        )

        monkeypatch.setattr(
            enrichment_review.repo,
            "reopen_superseded_loop_suggestion",
            lambda **kwargs: False,
        )

        with pytest.raises(RuntimeError, match="could be reopened"):
            enrichment_review.undo_clarification_answers(
                loop_id=loop["id"],
                clarification_ids=[clarification_id],
                conn=conn,
            )

        clarification = repo.read_loop_clarification(clarification_id=clarification_id, conn=conn)
        suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)

    assert clarification is not None
    assert clarification["answer"] == "Friday"
    assert suggestion is not None
    assert suggestion["resolution"] == "superseded"


def test_undo_clarification_answers_keeps_suggestion_superseded_when_other_answer_remains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)

        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?", "Who owns this?"]},
            model="test-model",
            conn=conn,
        )
        first_clarification_id = repo.insert_loop_clarification(
            loop_id=loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        second_clarification_id = repo.insert_loop_clarification(
            loop_id=loop["id"],
            question="Who owns this?",
            conn=conn,
        )
        conn.commit()

        enrichment_review.submit_clarification_answers(
            loop_id=loop["id"],
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=first_clarification_id,
                    answer="Friday",
                ),
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=second_clarification_id,
                    answer="Operations",
                ),
            ],
            conn=conn,
        )

        undo_result = enrichment_review.undo_clarification_answers(
            loop_id=loop["id"],
            clarification_ids=[first_clarification_id],
            conn=conn,
        )
        assert undo_result.restored_count == 1
        assert undo_result.reopened_suggestion_ids == []

        first_clarification = repo.read_loop_clarification(
            clarification_id=first_clarification_id,
            conn=conn,
        )
        second_clarification = repo.read_loop_clarification(
            clarification_id=second_clarification_id,
            conn=conn,
        )
        suggestion = repo.read_loop_suggestion(suggestion_id=suggestion_id, conn=conn)

    assert first_clarification is not None
    assert first_clarification["answer"] is None
    assert second_clarification is not None
    assert second_clarification["answer"] == "Operations"
    assert suggestion is not None
    assert suggestion["resolution"] == "superseded"


def test_undo_clarification_answers_rejects_duplicate_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)

        clarification_id = repo.insert_loop_clarification(
            loop_id=loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        repo.answer_loop_clarification(
            clarification_id=clarification_id,
            answer="Friday",
            conn=conn,
        )
        conn.commit()

        with pytest.raises(enrichment_review.ValidationError, match="duplicate clarification_id"):
            enrichment_review.undo_clarification_answers(
                loop_id=loop["id"],
                clarification_ids=[clarification_id, clarification_id],
                conn=conn,
            )


def test_undo_clarification_answers_rejects_if_pending_suggestion_references_question(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        loop = _capture_loop("Clarify launch date", status=LoopStatus.INBOX, conn=conn)

        first_suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=loop["id"],
            question="When should this happen?",
            conn=conn,
        )
        conn.commit()

        # Answer the clarification — this supersedes first_suggestion
        result = enrichment_review.submit_clarification_answers(
            loop_id=loop["id"],
            answers=[
                enrichment_review.ClarificationAnswerInput(
                    clarification_id=clarification_id,
                    answer="Friday",
                )
            ],
            conn=conn,
        )
        assert result.superseded_suggestion_ids == [first_suggestion_id]

        # A new pending suggestion appears referencing the same question
        # (simulating what happens after a rerun)
        repo.insert_loop_suggestion(
            loop_id=loop["id"],
            suggestion_json={"needs_clarification": ["When should this happen?"]},
            model="test-model",
            conn=conn,
        )
        conn.commit()

        # Undo should fail: the stale-state guard detects the new suggestion
        with pytest.raises(enrichment_review.ValidationError, match="Cannot undo"):
            enrichment_review.undo_clarification_answers(
                loop_id=loop["id"],
                clarification_ids=[clarification_id],
                conn=conn,
            )
