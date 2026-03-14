"""CLI tests for saved review actions and review sessions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from cloop import db
from cloop.cli_package.main import main
from cloop.loops import repo
from cloop.settings import Settings, get_settings

VECTORS = {
    "buy milk and eggs before the weekend": np.array([1.0, 0.0, 0.0], dtype=np.float32),
    "pick up groceries like milk and eggs": np.array([0.99, 0.01, 0.0], dtype=np.float32),
    "draft launch email for beta users": np.array([0.0, 1.0, 0.0], dtype=np.float32),
    "write beta launch email draft": np.array([0.0, 0.99, 0.01], dtype=np.float32),
}


def _make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
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


def _last_json(capsys: Any) -> Any:
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    for index in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[index:])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return json.loads(captured.out)


def test_relationship_review_workflow_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    _make_settings(tmp_path, monkeypatch)
    _mock_relationship_embeddings(monkeypatch)
    for raw_text in [
        "Buy milk and eggs before the weekend",
        "Pick up groceries like milk and eggs",
        "Draft launch email for beta users",
        "Write beta launch email draft",
    ]:
        assert main(["capture", raw_text]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "review",
                "relationship-action",
                "create",
                "--name",
                "dismiss-suggested",
                "--action",
                "dismiss",
                "--relationship-type",
                "suggested",
            ]
        )
        == 0
    )
    action = _last_json(capsys)

    assert (
        main(
            [
                "review",
                "relationship-session",
                "create",
                "--name",
                "duplicate-pass",
                "--query",
                "status:open",
                "--kind",
                "duplicate",
                "--current-loop-id",
                "1",
            ]
        )
        == 0
    )
    session = _last_json(capsys)
    assert session["current_item"]["loop"]["id"] == 1

    assert (
        main(
            [
                "review",
                "relationship-session",
                "apply-action",
                "--session",
                str(session["session"]["id"]),
                "--loop",
                "1",
                "--candidate",
                "2",
                "--candidate-type",
                "duplicate",
                "--action-id",
                str(action["id"]),
            ]
        )
        == 0
    )
    result = _last_json(capsys)
    assert result["result"]["link_state"] == "dismissed"
    remaining_loop_ids = {item["loop"]["id"] for item in result["snapshot"]["items"]}
    assert 1 not in remaining_loop_ids
    assert 2 not in remaining_loop_ids
    assert result["snapshot"]["session"]["current_loop_id"] in remaining_loop_ids

    assert main(["review", "relationship-session", "list"]) == 0
    listed = _last_json(capsys)
    assert {item["id"] for item in listed} == {session["session"]["id"]}


def test_enrichment_review_workflow_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: Any,
) -> None:
    settings = _make_settings(tmp_path, monkeypatch)

    assert main(["capture", "Plan launch retrospective"]) == 0
    assert main(["capture", "Clarify launch checklist owner"]) == 0
    capsys.readouterr()

    with db.core_connection(settings) as conn:
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=1,
            suggestion_json={
                "title": "Plan launch retrospective meeting",
                "summary": "Collect decisions and owners.",
                "confidence": {"title": 0.99, "summary": 0.94},
            },
            model="test-model",
            conn=conn,
        )
        superseded_suggestion_id = repo.insert_loop_suggestion(
            loop_id=2,
            suggestion_json={"needs_clarification": ["Who owns the checklist?"]},
            model="test-model",
            conn=conn,
        )
        clarification_id = repo.insert_loop_clarification(
            loop_id=2,
            question="Who owns the checklist?",
            conn=conn,
        )
        conn.commit()

    assert (
        main(
            [
                "review",
                "enrichment-action",
                "create",
                "--name",
                "apply-title",
                "--action",
                "apply",
                "--fields",
                "title",
            ]
        )
        == 0
    )
    action = _last_json(capsys)

    assert (
        main(
            [
                "review",
                "enrichment-session",
                "create",
                "--name",
                "follow-up-pass",
                "--query",
                "status:open",
                "--pending-kind",
                "all",
                "--current-loop-id",
                "1",
            ]
        )
        == 0
    )
    session = _last_json(capsys)
    assert session["current_item"]["loop"]["id"] == 1

    assert (
        main(
            [
                "review",
                "enrichment-session",
                "apply-action",
                "--session",
                str(session["session"]["id"]),
                "--suggestion",
                str(suggestion_id),
                "--action-id",
                str(action["id"]),
            ]
        )
        == 0
    )
    apply_result = _last_json(capsys)
    assert apply_result["result"]["suggestion_id"] == suggestion_id
    assert apply_result["snapshot"]["session"]["current_loop_id"] == 2

    assert (
        main(
            [
                "review",
                "enrichment-session",
                "answer-clarifications",
                "--session",
                str(session["session"]["id"]),
                "--loop",
                "2",
                "--item",
                f"{clarification_id}=Operations",
            ]
        )
        == 0
    )
    answer_result = _last_json(capsys)
    assert answer_result["result"]["loop_id"] == 2
    assert answer_result["result"]["superseded_suggestion_ids"] == [superseded_suggestion_id]
    assert answer_result["snapshot"]["loop_count"] == 0
