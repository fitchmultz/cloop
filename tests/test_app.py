import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.main import app
from cloop.settings import get_settings

STREAM_TOKENS = ["Answer ", "segment"]


def make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    os.environ["CLOOP_DATA_DIR"] = str(tmp_path)
    os.environ["CLOOP_LLM_MODEL"] = "mock-llm"
    os.environ["CLOOP_EMBED_MODEL"] = "mock-embed"
    get_settings.cache_clear()
    db.init_databases(get_settings())

    def mock_completion(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        messages: List[Dict[str, Any]] = kwargs.get("messages") or []
        tools = kwargs.get("tools")

        # First tool-enabled pass returns a tool call.
        if tools:
            if any(message.get("role") == "tool" for message in messages):
                return {
                    "choices": [{"message": {"content": "tool-mode-final"}}],
                    "model": "mock-llm-tool",
                    "usage": {"total_tokens": 0},
                }
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "write_note",
                                        "arguments": '{"title": "auto", "body": "generated"}',
                                    },
                                }
                            ]
                        }
                    }
                ],
                "model": "mock-llm-tool",
                "usage": {"total_tokens": 0},
            }

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

    def mock_stream_completion(*args: Any, **kwargs: Any):
        def iterator() -> Any:
            for token in STREAM_TOKENS:
                yield token

        return iterator()

    monkeypatch.setattr("cloop.llm.litellm.completion", mock_completion)
    monkeypatch.setattr("cloop.embeddings.litellm.embedding", mock_embedding)
    monkeypatch.setattr("cloop.llm.stream_completion", mock_stream_completion)
    monkeypatch.setattr("cloop.main.stream_completion", mock_stream_completion)
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
    assert answer_payload["model"] == "mock-llm"
    assert answer_payload["sources"]
    for chunk in answer_payload["chunks"]:
        assert "embedding_blob" not in chunk


def test_chat_manual_tool_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert write_data["tool_calls"] == []
    assert write_data["model"] == "mock-llm"
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
    assert read_data["tool_calls"] == []

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT tool_calls FROM interactions WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["tool_calls"] == "[]"


def test_chat_llm_tool_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    payload = {
        "messages": [{"role": "user", "content": "Please file a note."}],
        "tool_mode": "llm",
    }

    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "tool-mode-final"
    assert data["tool_calls"] == [
        {"name": "write_note", "arguments": {"title": "auto", "body": "generated"}}
    ]
    assert data["tool_result"]["action"] == "write_note"
    assert data["model"] == "mock-llm-tool"

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT tool_calls FROM interactions WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert "write_note" in row["tool_calls"]


def _read_sse(response: Any) -> List[Tuple[str, Dict[str, Any]]]:
    body = "".join(chunk for chunk in response.iter_text())
    events: List[Tuple[str, Dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        if not block:
            continue
        event_name = "message"
        payload: Dict[str, Any] = {}
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload = json.loads(line.split(":", 1)[1].strip())
        events.append((event_name, payload))
    return events


def test_chat_streaming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)

    payload = {
        "messages": [{"role": "user", "content": "Stream please."}],
        "tool_mode": "none",
    }

    with client.stream("POST", "/chat?stream=true", json=payload) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _read_sse(response)

    tokens = [event[1]["token"] for event in events if event[0] == "token"]
    assert tokens == STREAM_TOKENS
    done_events = [event for event in events if event[0] == "done"]
    assert done_events
    final_payload = done_events[-1][1]
    assert final_payload["message"] == "".join(STREAM_TOKENS)
    assert final_payload["model"] == "mock-llm"

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT response_payload FROM interactions WHERE endpoint = '/chat'"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    recorded = json.loads(row["response_payload"])
    assert recorded["message"] == "".join(STREAM_TOKENS)
    assert recorded["context"]["embed_model"] == get_settings().embed_model


def test_ask_streaming(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    doc = tmp_path / "faq.txt"
    doc.write_text("All about streaming.", encoding="utf-8")
    ingest = client.post("/ingest", json={"paths": [str(doc)]})
    assert ingest.status_code == 200

    with client.stream("GET", "/ask", params={"q": "Stream?", "stream": "true"}) as response:
        assert response.status_code == 200
        events = _read_sse(response)

    tokens = [event[1]["token"] for event in events if event[0] == "token"]
    assert tokens == STREAM_TOKENS
    final_payload = [event for event in events if event[0] == "done"][-1][1]
    assert final_payload["answer"] == "".join(STREAM_TOKENS)
    assert final_payload["model"] == get_settings().llm_model
    assert final_payload["sources"]

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT response_payload FROM interactions WHERE endpoint = '/ask'"
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    recorded = json.loads(row["response_payload"])
    assert recorded["answer"] == "".join(STREAM_TOKENS)
    assert recorded["context"]["vector_search_mode"] == get_settings().vector_search_mode.value


def test_health_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model"] == "mock-llm"
    assert payload["core_db"].endswith("core.db")
    assert payload["rag_db"].endswith("rag.db")
    assert payload["schema_version"] == db.SCHEMA_VERSION
    assert payload["embed_storage"] in {"json", "blob", "dual"}
    assert payload["tool_mode_default"] in {"manual", "llm", "none"}
    assert payload["retrieval_order"]
    assert payload["retrieval_metric"] in {"1_over_1_plus_distance", "cosine"}


def test_chat_manual_requires_tool_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    response = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "tool_mode": "manual",
        },
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["type"] == "validation_error"


def test_chat_invalid_tool_mode_returns_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    response = client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "tool_mode": "unsupported",
        },
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["message"] == "Validation failed"


def test_validation_error_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    response = client.post("/chat", json={})
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["details"]["errors"]


def test_ask_scope_filters_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    dir_one = tmp_path / "dir_one"
    dir_two = tmp_path / "dir_two"
    dir_one.mkdir()
    dir_two.mkdir()
    doc_a = dir_one / "alpha.txt"
    doc_b = dir_two / "beta.txt"
    doc_a.write_text("alpha scope content", encoding="utf-8")
    doc_b.write_text("beta scope content", encoding="utf-8")

    response = client.post("/ingest", json={"paths": [str(doc_a), str(doc_b)]})
    assert response.status_code == 200

    scoped = client.get(
        "/ask",
        params={"q": "scope?", "k": 10, "scope": "alpha.txt"},
    )
    assert scoped.status_code == 200
    scoped_payload = scoped.json()
    assert scoped_payload["sources"]
    assert all("alpha.txt" in source["document_path"] for source in scoped_payload["sources"])

    doc_scope = client.get(
        "/ask",
        params={"q": "scope?", "k": 10, "scope": "beta.txt"},
    )
    assert doc_scope.status_code == 200
    doc_payload = doc_scope.json()
    assert all("beta.txt" in source["document_path"] for source in doc_payload["sources"])


def test_ask_scope_filters_doc_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(tmp_path, monkeypatch)
    doc_a = tmp_path / "doc_a.txt"
    doc_b = tmp_path / "doc_b.txt"
    doc_a.write_text("alpha doc content", encoding="utf-8")
    doc_b.write_text("beta doc content", encoding="utf-8")
    ingest = client.post("/ingest", json={"paths": [str(doc_a), str(doc_b)]})
    assert ingest.status_code == 200

    with db.rag_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT id FROM documents WHERE document_path = ?",
            (str(doc_b),),
        ).fetchone()
    assert row is not None
    doc_id = row["id"]

    scoped = client.get(
        "/ask",
        params={"q": "doc id?", "k": 10, "scope": f"doc:{doc_id}"},
    )
    assert scoped.status_code == 200
    payload = scoped.json()
    assert payload["sources"]
    assert all(source["document_path"] == str(doc_b) for source in payload["sources"])


def test_ask_returns_400_on_embedding_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path, monkeypatch)
    doc = tmp_path / "drift.txt"
    doc.write_text("guard", encoding="utf-8")
    ingest = client.post("/ingest", json={"paths": [str(doc)]})
    assert ingest.status_code == 200

    with db.rag_connection(get_settings()) as conn:
        conn.execute("UPDATE chunks SET embedding_dim = embedding_dim + 1")
        conn.commit()

    response = client.get("/ask", params={"q": "drift?"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["type"] == "http_error"
    assert "embedding_dim mismatch" in payload["error"]["message"]


def test_loop_not_found_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that LoopNotFoundError maps to HTTP 404."""
    client = make_client(tmp_path, monkeypatch)

    response = client.get("/loops/999999")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"
    assert "Loop not found" in data["error"]["message"]


def test_loop_update_not_found_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that updating a non-existent loop returns 404."""
    client = make_client(tmp_path, monkeypatch)

    response = client.patch("/loops/999999", json={"title": "Updated"})
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"


def test_loop_close_not_found_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that closing a non-existent loop returns 404."""
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/loops/999999/close", json={"status": "completed"})
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"


def test_loop_status_not_found_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that status transition on non-existent loop returns 404."""
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/loops/999999/status", json={"status": "actionable"})
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"


def test_loop_enrich_not_found_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that enriching a non-existent loop returns 404."""
    client = make_client(tmp_path, monkeypatch)

    response = client.post("/loops/999999/enrich")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"


def test_loop_capture_invalid_timestamp_returns_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that invalid timestamp returns validation error (422 from Pydantic)."""
    client = make_client(tmp_path, monkeypatch)

    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "not-a-timestamp",
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["type"] == "validation_error"


def test_loop_update_empty_fields_returns_400(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that updating with no fields returns 400."""
    client = make_client(tmp_path, monkeypatch)

    # First capture a loop (with autopilot disabled to avoid background task issues)
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()

    capture_resp = client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2024-01-01T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert capture_resp.status_code == 200
    loop_id = capture_resp.json()["id"]

    # Try to update with empty fields (by using a dict with only excluded defaults)
    response = client.patch(f"/loops/{loop_id}", json={})
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["type"] == "http_error"
    assert "no_fields_to_update" in data["error"]["message"]


def test_generic_exception_sanitized_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that generic exception handler logs details but returns sanitized response."""
    import logging
    from unittest.mock import patch

    def mock_ingest_paths(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Simulated ingestion failure with /secret/path")

    monkeypatch.setattr("cloop.main.ingest_paths", mock_ingest_paths)
    client = TestClient(app, raise_server_exceptions=False)

    doc = tmp_path / "test.txt"
    doc.write_text("content", encoding="utf-8")

    with patch.object(logging.getLogger("cloop.main"), "exception") as mock_log:
        response = client.post("/ingest", json={"paths": [str(doc)]})

    assert response.status_code == 500
    data = response.json()
    assert data["error"]["type"] == "server_error"
    assert data["error"]["message"] == "Unexpected server error"

    assert "error_id" in data["error"]["details"]
    error_id = data["error"]["details"]["error_id"]
    assert len(error_id) == 36
    assert error_id.count("-") == 4

    assert "exception" not in data["error"]["details"]
    assert "Simulated ingestion failure" not in str(data)
    assert "/secret/path" not in str(data)

    mock_log.assert_called_once()
    call_args = str(mock_log.call_args)
    assert error_id in call_args


def test_generic_exception_never_exposes_sensitive_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify that sensitive information is never exposed in error responses."""
    import logging
    from unittest.mock import patch

    sensitive_patterns = [
        "/Users/secret",
        "/home/admin",
        "password=",
        "api_key=",
        "token=",
        "connection string",
    ]

    for pattern in sensitive_patterns:

        def mock_fail(*args: Any, _pattern: str = pattern, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError(f"Error involving {_pattern}")

        monkeypatch.setattr("cloop.main.ingest_paths", mock_fail)
        client = TestClient(app, raise_server_exceptions=False)

        doc = tmp_path / "test.txt"
        doc.write_text("content", encoding="utf-8")

        with patch.object(logging.getLogger("cloop.main"), "exception"):
            response = client.post("/ingest", json={"paths": [str(doc)]})

        response_text = response.text.lower()
        assert pattern.lower() not in response_text, (
            f"Sensitive pattern '{pattern}' exposed in response"
        )
