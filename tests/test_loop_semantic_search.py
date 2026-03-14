"""Semantic loop search and on-demand embedding index tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.loops import read_service, repo, service
from cloop.loops.models import LoopStatus
from cloop.settings import Settings, get_settings


def _setup_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _mock_semantic_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_embedding(*args: Any, **kwargs: Any) -> dict[str, Any]:
        inputs = kwargs.get("input") or []
        data: list[dict[str, list[float]]] = []
        for text in inputs:
            lowered = str(text).lower()
            vector = np.array([0.05, 0.05, 0.05], dtype=np.float32)
            if any(token in lowered for token in ["milk", "eggs", "grocery", "groceries", "store"]):
                vector += np.array([1.0, 0.0, 0.0], dtype=np.float32)
            if any(
                token in lowered for token in ["email", "client", "follow-up", "follow up", "reply"]
            ):
                vector += np.array([0.0, 1.0, 0.0], dtype=np.float32)
            if any(token in lowered for token in ["quarter", "planning", "roadmap", "review"]):
                vector += np.array([0.0, 0.0, 1.0], dtype=np.float32)
            vector /= np.linalg.norm(vector)
            data.append({"embedding": vector.tolist()})
        return {"data": data}

    monkeypatch.setattr("cloop.embeddings.litellm.embedding", fake_embedding)


def test_semantic_search_backfills_embeddings_and_ranks_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic search should index missing loops and rank semantically close results first."""
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_semantic_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        repo.create_loop(
            raw_text="Buy milk and eggs before the weekend",
            captured_at_utc="2026-03-14T12:00:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        repo.create_loop(
            raw_text="Reply to the client email about contract details",
            captured_at_utc="2026-03-14T12:05:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.ACTIONABLE,
            conn=conn,
        )
        repo.create_loop(
            raw_text="Quarterly roadmap planning review",
            captured_at_utc="2026-03-14T12:10:00+00:00",
            captured_tz_offset_min=0,
            status=LoopStatus.SCHEDULED,
            conn=conn,
        )
        conn.commit()

    with db.core_connection(settings) as conn:
        result = read_service.semantic_search_loops(
            query="pick up groceries like milk",
            statuses=None,
            limit=10,
            offset=0,
            min_score=0.0,
            conn=conn,
            settings=settings,
        )
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM loop_embeddings WHERE source_text_hash != ''"
        ).fetchone()

    assert result["indexed_count"] == 3
    assert result["candidate_count"] == 3
    assert result["match_count"] == 3
    assert result["items"][0]["raw_text"] == "Buy milk and eggs before the weekend"
    assert result["items"][0]["semantic_score"] > result["items"][1]["semantic_score"]
    assert row is not None
    assert int(row["count"]) == 3


def test_semantic_search_refreshes_stale_embeddings_after_loop_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Semantic search should detect stale loop text and refresh embeddings on demand."""
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_semantic_embeddings(monkeypatch)

    with db.core_connection(settings) as conn:
        created = service.capture_loop(
            raw_text="Buy groceries for dinner",
            captured_at_iso="2026-03-14T12:00:00+00:00",
            client_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        loop_id = int(created["id"])

    with db.core_connection(settings) as conn:
        first = read_service.semantic_search_loops(
            query="groceries",
            statuses=None,
            limit=10,
            offset=0,
            min_score=0.1,
            conn=conn,
            settings=settings,
        )
        before_row = conn.execute(
            "SELECT source_text_hash FROM loop_embeddings WHERE loop_id = ?",
            (loop_id,),
        ).fetchone()
        service.update_loop(
            loop_id=loop_id,
            fields={"raw_text": "Send the client follow-up email today"},
            conn=conn,
        )
        stale_row = conn.execute(
            "SELECT source_text_hash FROM loop_embeddings WHERE loop_id = ?",
            (loop_id,),
        ).fetchone()
        refreshed = read_service.semantic_search_loops(
            query="client email",
            statuses=None,
            limit=10,
            offset=0,
            min_score=0.1,
            conn=conn,
            settings=settings,
        )
        after_row = conn.execute(
            "SELECT source_text_hash FROM loop_embeddings WHERE loop_id = ?",
            (loop_id,),
        ).fetchone()

    assert first["indexed_count"] == 1
    assert before_row is not None
    assert stale_row is not None
    assert stale_row["source_text_hash"] == before_row["source_text_hash"]
    assert refreshed["indexed_count"] == 1
    assert refreshed["items"][0]["id"] == loop_id
    assert after_row is not None
    assert after_row["source_text_hash"] != before_row["source_text_hash"]
