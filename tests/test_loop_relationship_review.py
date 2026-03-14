"""Relationship-review tests for duplicate and related-loop workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.loops import duplicates, relationship_review, repo
from cloop.loops.models import LoopStatus
from cloop.settings import Settings, get_settings

VECTORS = {
    "buy milk and eggs before the weekend": np.array([1.0, 0.0, 0.0], dtype=np.float32),
    "pick up groceries like milk and eggs": np.array([0.99, 0.01, 0.0], dtype=np.float32),
    "plan weekend grocery run and meal prep": np.array([0.82, 0.57, 0.0], dtype=np.float32),
    "reply to the client email about the contract": np.array([0.0, 1.0, 0.0], dtype=np.float32),
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


def _mock_exact_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_relationship_review_classifies_duplicate_and_related_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_exact_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        loop_one = repo.create_loop(
            raw_text="Buy milk and eggs before the weekend",
            captured_at_utc="2026-03-14T12:00:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        loop_two = repo.create_loop(
            raw_text="Pick up groceries like milk and eggs",
            captured_at_utc="2026-03-14T12:05:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        loop_three = repo.create_loop(
            raw_text="Plan weekend grocery run and meal prep",
            captured_at_utc="2026-03-14T12:10:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.SCHEDULED,
            conn=conn,
        )
        repo.create_loop(
            raw_text="Reply to the client email about the contract",
            captured_at_utc="2026-03-14T12:15:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.BLOCKED,
            conn=conn,
        )
        conn.commit()

    with db.core_connection(settings) as conn:
        result = relationship_review.review_loop_relationships(
            loop_id=loop_one.id,
            statuses=None,
            duplicate_limit=10,
            related_limit=10,
            conn=conn,
            settings=settings,
        )
        queue = relationship_review.list_relationship_review_queue(
            statuses=None,
            relationship_kind="all",
            limit=10,
            candidate_limit=3,
            conn=conn,
            settings=settings,
        )

    assert result["indexed_count"] == 4
    assert [candidate["id"] for candidate in result["duplicate_candidates"]] == [loop_two.id]
    assert [candidate["id"] for candidate in result["related_candidates"]] == [loop_three.id]
    assert queue["loop_count"] >= 3
    assert any(item["loop"]["id"] == loop_one.id for item in queue["items"])


def test_relationship_review_confirm_dismiss_and_merge_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_exact_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        loop_one = repo.create_loop(
            raw_text="Buy milk and eggs before the weekend",
            captured_at_utc="2026-03-14T12:00:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        loop_two = repo.create_loop(
            raw_text="Pick up groceries like milk and eggs",
            captured_at_utc="2026-03-14T12:05:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        loop_three = repo.create_loop(
            raw_text="Plan weekend grocery run and meal prep",
            captured_at_utc="2026-03-14T12:10:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.SCHEDULED,
            conn=conn,
        )
        conn.commit()

    with db.core_connection(settings) as conn:
        relationship_review.confirm_relationship(
            loop_id=loop_one.id,
            candidate_loop_id=loop_three.id,
            relationship_type="related",
            conn=conn,
        )
        relationship_review.dismiss_relationship(
            loop_id=loop_one.id,
            candidate_loop_id=loop_two.id,
            relationship_type="duplicate",
            conn=conn,
        )
        after_decisions = relationship_review.review_loop_relationships(
            loop_id=loop_one.id,
            statuses=None,
            duplicate_limit=10,
            related_limit=10,
            conn=conn,
            settings=settings,
        )
        conn.commit()

    assert [candidate["id"] for candidate in after_decisions["existing_related"]] == [loop_three.id]
    assert all(
        candidate["id"] != loop_three.id for candidate in after_decisions["related_candidates"]
    )
    assert all(
        candidate["id"] != loop_two.id for candidate in after_decisions["duplicate_candidates"]
    )

    with db.core_connection(settings) as conn:
        relationship_review.confirm_relationship(
            loop_id=loop_one.id,
            candidate_loop_id=loop_two.id,
            relationship_type="duplicate",
            conn=conn,
        )
        merge_result = duplicates.merge_loops(
            surviving_loop_id=loop_one.id,
            duplicate_loop_id=loop_two.id,
            conn=conn,
            settings=settings,
        )
        resolved_rows = repo.list_loop_links_by_type(
            loop_id=loop_one.id,
            relationship_type="duplicate",
            link_state="resolved",
            conn=conn,
        )

    assert merge_result.closed_loop_id == loop_two.id
    assert any(row["related_loop_id"] == loop_two.id for row in resolved_rows)
