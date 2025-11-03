from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.main import app
from cloop.settings import get_settings


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    os.environ["CLOOP_DATA_DIR"] = str(tmp_path)
    get_settings.cache_clear()  # type: ignore[attr-defined]
    db.init_databases(get_settings())

    def mock_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {
            "choices": [{"message": {"content": "mock-response"}}],
            "model": "mock-llm",
            "usage": {"total_tokens": 0},
        }

    def mock_embedding(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        inputs = kwargs.get("input") or []
        vectors = []
        for index, _ in enumerate(inputs):
            vectors.append({"embedding": [0.1 + index, 0.2 + index, 0.3 + index]})
        return {"data": vectors}

    monkeypatch.setattr("cloop.llm.litellm.completion", mock_completion)
    monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_embedding)
    return TestClient(app)


def test_ingest_and_ask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    doc = tmp_path / "note.txt"
    doc.write_text("FastAPI makes it easy to build APIs.", encoding="utf-8")

    response = client.post("/ingest", json={"paths": [str(doc)]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["files"] == 1
    assert payload["chunks"] >= 1

    ask_response = client.get("/ask", params={"q": "What does FastAPI help with?"})
    assert ask_response.status_code == 200
    answer_payload = ask_response.json()
    assert answer_payload["answer"] == "mock-response"
    assert answer_payload["chunks"]


def test_chat_with_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    write_payload = {
        "messages": [{"role": "user", "content": "Log a new note."}],
        "tool_call": {
            "name": "write_note",
            "title": "todo",
            "body": "remember to test",
        },
    }
    write_response = client.post("/chat", json=write_payload)
    assert write_response.status_code == 200
    write_data = write_response.json()
    assert write_data["tool_result"]["action"] == "write_note"
    note_id = write_data["tool_result"]["note"]["id"]

    read_payload = {
        "messages": [{"role": "user", "content": "Fetch my note."}],
        "tool_call": {"name": "read_note", "note_id": note_id},
    }
    read_response = client.post("/chat", json=read_payload)
    assert read_response.status_code == 200
    read_data = read_response.json()
    assert read_data["tool_result"]["action"] == "read_note"
    assert read_data["tool_result"]["note"]["title"] == "todo"
