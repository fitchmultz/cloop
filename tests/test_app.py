import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.settings import get_settings


def test_ingest_and_ask(test_client: TestClient, tmp_data_dir: Path) -> None:
    doc = tmp_data_dir / "note.txt"
    doc.write_text("FastAPI makes it easy to build APIs.", encoding="utf-8")

    response = test_client.post("/ingest", json={"paths": [str(doc)]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["files"] == 1
    assert payload["chunks"] >= 1

    ask_response = test_client.get("/ask", params={"q": "What does FastAPI help with?"})
    assert ask_response.status_code == 200
    answer_payload = ask_response.json()
    assert answer_payload["answer"] == "mock-response"
    assert answer_payload["chunks"]
    assert answer_payload["model"] == "mock-llm"
    assert answer_payload["sources"]
    for chunk in answer_payload["chunks"]:
        assert "embedding_blob" not in chunk


def test_chat_manual_tool_mode(test_client: TestClient, tmp_data_dir: Path) -> None:
    write_payload = {
        "messages": [{"role": "user", "content": "Log a new note."}],
        "tool_call": {
            "name": "write_note",
            "arguments": {"title": "todo", "body": "remember to test"},
        },
    }
    write_response = test_client.post("/chat", json=write_payload)
    assert write_response.status_code == 200
    write_data = write_response.json()
    assert write_data["tool_result"]["action"] == "write_note"
    assert write_data["tool_calls"] == []
    assert write_data["model"] == "mock-llm"
    note_id = write_data["tool_result"]["note"]["id"]

    read_payload = {
        "messages": [{"role": "user", "content": "Fetch my note."}],
        "tool_call": {"name": "read_note", "arguments": {"note_id": note_id}},
    }
    read_response = test_client.post("/chat", json=read_payload)
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


def test_chat_manual_loop_create(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Manual mode can create loops via loop_create tool."""
    payload = {
        "messages": [{"role": "user", "content": "Create a task"}],
        "tool_call": {
            "name": "loop_create",
            "arguments": {"raw_text": "Pay rent", "status": "inbox"},
        },
    }
    response = test_client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_result"]["action"] == "loop_create"
    assert data["tool_result"]["loop"]["raw_text"] == "Pay rent"
    assert data["tool_result"]["loop"]["status"] == "inbox"


def test_chat_manual_loop_update(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Manual mode can update loops via loop_update tool."""
    # Create a loop first
    create_payload = {
        "messages": [{"role": "user", "content": "Create"}],
        "tool_call": {
            "name": "loop_create",
            "arguments": {"raw_text": "Original task"},
        },
    }
    create_resp = test_client.post("/chat", json=create_payload)
    loop_id = create_resp.json()["tool_result"]["loop"]["id"]

    # Update the loop
    update_payload = {
        "messages": [{"role": "user", "content": "Update"}],
        "tool_call": {
            "name": "loop_update",
            "arguments": {
                "loop_id": loop_id,
                "fields": {"title": "Updated Title", "time_minutes": 30},
            },
        },
    }
    response = test_client.post("/chat", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_result"]["action"] == "loop_update"
    assert data["tool_result"]["loop"]["title"] == "Updated Title"
    assert data["tool_result"]["loop"]["time_minutes"] == 30


def test_chat_manual_loop_list(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Manual mode can list loops via loop_list tool."""
    # Create some loops
    for i in range(3):
        test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": f"Create {i}"}],
                "tool_call": {
                    "name": "loop_create",
                    "arguments": {"raw_text": f"Task {i}", "status": "actionable"},
                },
            },
        )

    # List actionable loops
    list_payload = {
        "messages": [{"role": "user", "content": "List tasks"}],
        "tool_call": {
            "name": "loop_list",
            "arguments": {"status": "actionable", "limit": 10},
        },
    }
    response = test_client.post("/chat", json=list_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_result"]["action"] == "loop_list"
    assert len(data["tool_result"]["items"]) >= 3


def test_chat_manual_loop_close(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Manual mode can close loops via loop_close tool."""
    # Create a loop
    create_resp = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "Create"}],
            "tool_call": {"name": "loop_create", "arguments": {"raw_text": "Done task"}},
        },
    )
    loop_id = create_resp.json()["tool_result"]["loop"]["id"]

    # Close the loop
    close_payload = {
        "messages": [{"role": "user", "content": "Complete"}],
        "tool_call": {
            "name": "loop_close",
            "arguments": {"loop_id": loop_id, "status": "completed"},
        },
    }
    response = test_client.post("/chat", json=close_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["tool_result"]["action"] == "loop_close"
    assert data["tool_result"]["loop"]["status"] == "completed"


def test_chat_manual_invalid_tool_arguments(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Manual mode validates tool arguments and returns 400 on validation errors."""
    # Missing required raw_text for loop_create
    payload = {
        "messages": [{"role": "user", "content": "Invalid"}],
        "tool_call": {
            "name": "loop_create",
            "arguments": {},  # Missing raw_text
        },
    }
    response = test_client.post("/chat", json=payload)
    assert response.status_code == 400


def test_chat_manual_unsupported_tool(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Manual mode returns 400 for unsupported tool names."""
    payload = {
        "messages": [{"role": "user", "content": "Bad tool"}],
        "tool_call": {
            "name": "nonexistent_tool",
            "arguments": {},
        },
    }
    response = test_client.post("/chat", json=payload)
    assert response.status_code == 400
    assert "Unsupported tool" in response.json()["error"]["message"]


def test_chat_manual_backward_compat_note_tools(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """Existing note tool calls work with new arguments-based schema."""
    # write_note with new schema
    write_payload = {
        "messages": [{"role": "user", "content": "Write note"}],
        "tool_call": {
            "name": "write_note",
            "arguments": {"title": "Test", "body": "Content"},
        },
    }
    write_resp = test_client.post("/chat", json=write_payload)
    assert write_resp.status_code == 200
    note_id = write_resp.json()["tool_result"]["note"]["id"]

    # read_note with new schema
    read_payload = {
        "messages": [{"role": "user", "content": "Read note"}],
        "tool_call": {
            "name": "read_note",
            "arguments": {"note_id": note_id},
        },
    }
    read_resp = test_client.post("/chat", json=read_payload)
    assert read_resp.status_code == 200
    assert read_resp.json()["tool_result"]["note"]["title"] == "Test"


def test_chat_llm_tool_mode(test_client: TestClient, tmp_data_dir: Path) -> None:
    payload = {
        "messages": [{"role": "user", "content": "Please file a note."}],
        "tool_mode": "llm",
    }

    response = test_client.post("/chat", json=payload)
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


def test_chat_streaming(test_client: TestClient, tmp_data_dir: Path) -> None:
    from tests.conftest import STREAM_TOKENS

    payload = {
        "messages": [{"role": "user", "content": "Stream please."}],
        "tool_mode": "none",
    }

    with test_client.stream("POST", "/chat?stream=true", json=payload) as response:
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


def test_ask_streaming(test_client: TestClient, tmp_data_dir: Path) -> None:
    from tests.conftest import STREAM_TOKENS

    doc = tmp_data_dir / "faq.txt"
    doc.write_text("All about streaming.", encoding="utf-8")
    ingest = test_client.post("/ingest", json={"paths": [str(doc)]})
    assert ingest.status_code == 200

    with test_client.stream("GET", "/ask", params={"q": "Stream?", "stream": "true"}) as response:
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


def test_health_endpoint(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model"] == "mock-llm"
    assert payload["core_db"] == "core.db"
    assert payload["rag_db"] == "rag.db"
    assert "/" not in payload["core_db"]
    assert "/" not in payload["rag_db"]
    assert not payload["core_db"].startswith("/")
    assert not payload["rag_db"].startswith("/")
    assert "Users" not in payload["core_db"]
    assert "home" not in payload["rag_db"]
    assert payload["schema_version"] == db.SCHEMA_VERSION
    assert payload["embed_storage"] in {"json", "blob", "dual"}
    assert payload["tool_mode_default"] in {"manual", "llm", "none"}
    assert payload["retrieval_order"]
    assert payload["retrieval_metric"] in {"1_over_1_plus_distance", "cosine"}
    # Verify dependency checks
    assert "checks" in payload
    assert payload["checks"]["core_db"]["ok"] is True
    assert payload["checks"]["rag_db"]["ok"] is True
    assert payload["checks"]["core_db"]["latency_ms"] >= 0
    assert payload["checks"]["rag_db"]["latency_ms"] >= 0
    assert payload["checks"]["core_db"]["error"] is None
    assert payload["checks"]["rag_db"]["error"] is None
    # Verify vector extension status fields
    assert "vector_available" in payload
    assert isinstance(payload["vector_available"], bool)
    assert "vector_load_error" in payload
    # vector_load_error should be None (no extension configured in tests) or a string
    if payload["vector_load_error"] is not None:
        assert isinstance(payload["vector_load_error"], str)
    # When no extension configured, vector_backend should be "none"
    # and vector_available should be False
    if payload["vector_backend"] == "none":
        assert payload["vector_available"] is False


def test_healthz_alias_matches_health(test_client: TestClient, tmp_data_dir: Path) -> None:
    health = test_client.get("/health")
    healthz = test_client.get("/healthz")
    assert health.status_code == 200
    assert healthz.status_code == 200
    health_payload = health.json()
    healthz_payload = healthz.json()
    for key in health_payload:
        if key == "checks":
            continue
        assert healthz_payload[key] == health_payload[key]
    assert set(healthz_payload["checks"]) == set(health_payload["checks"])
    for check_name in health_payload["checks"]:
        health_check = health_payload["checks"][check_name]
        healthz_check = healthz_payload["checks"][check_name]
        assert healthz_check["ok"] == health_check["ok"]
        assert healthz_check["error"] == health_check["error"]
        assert healthz_payload["checks"][check_name]["latency_ms"] >= 0


def test_static_js_uses_no_cache_headers(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.get("/static/js/init.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_health_endpoint_with_broken_core_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Health endpoint returns ok=False when core database is inaccessible."""
    # Set up a path to a file that exists but isn't a valid SQLite database
    broken_db_path = tmp_path / "broken.db"
    broken_db_path.write_text("not a sqlite database")

    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_CORE_DB_PATH", str(broken_db_path))
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()

    # Need to create a fresh client without initializing databases
    from cloop.main import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["checks"]["core_db"]["ok"] is False
    assert payload["checks"]["core_db"]["error"] is not None


def test_chat_manual_requires_tool_call(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "tool_mode": "manual",
        },
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["type"] == "validation_error"


def test_chat_invalid_tool_mode_returns_error(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.post(
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


def test_validation_error_shape(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.post("/chat", json={})
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["details"]["errors"]


def test_ask_scope_filters_path(test_client: TestClient, tmp_data_dir: Path) -> None:
    dir_one = tmp_data_dir / "dir_one"
    dir_two = tmp_data_dir / "dir_two"
    dir_one.mkdir()
    dir_two.mkdir()
    doc_a = dir_one / "alpha.txt"
    doc_b = dir_two / "beta.txt"
    doc_a.write_text("alpha scope content", encoding="utf-8")
    doc_b.write_text("beta scope content", encoding="utf-8")

    response = test_client.post("/ingest", json={"paths": [str(doc_a), str(doc_b)]})
    assert response.status_code == 200

    scoped = test_client.get(
        "/ask",
        params={"q": "scope?", "k": 10, "scope": "alpha.txt"},
    )
    assert scoped.status_code == 200
    scoped_payload = scoped.json()
    assert scoped_payload["sources"]
    assert all("alpha.txt" in source["document_path"] for source in scoped_payload["sources"])

    doc_scope = test_client.get(
        "/ask",
        params={"q": "scope?", "k": 10, "scope": "beta.txt"},
    )
    assert doc_scope.status_code == 200
    doc_payload = doc_scope.json()
    assert all("beta.txt" in source["document_path"] for source in doc_payload["sources"])


def test_ask_scope_filters_doc_id(test_client: TestClient, tmp_data_dir: Path) -> None:
    doc_a = tmp_data_dir / "doc_a.txt"
    doc_b = tmp_data_dir / "doc_b.txt"
    doc_a.write_text("alpha doc content", encoding="utf-8")
    doc_b.write_text("beta doc content", encoding="utf-8")
    ingest = test_client.post("/ingest", json={"paths": [str(doc_a), str(doc_b)]})
    assert ingest.status_code == 200

    with db.rag_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT id FROM documents WHERE document_path = ?",
            (str(doc_b),),
        ).fetchone()
    assert row is not None
    doc_id = row["id"]

    scoped = test_client.get(
        "/ask",
        params={"q": "doc id?", "k": 10, "scope": f"doc:{doc_id}"},
    )
    assert scoped.status_code == 200
    payload = scoped.json()
    assert payload["sources"]
    assert all(source["document_path"] == str(doc_b) for source in payload["sources"])


def test_ask_returns_400_on_embedding_drift(test_client: TestClient, tmp_data_dir: Path) -> None:
    doc = tmp_data_dir / "drift.txt"
    doc.write_text("guard", encoding="utf-8")
    ingest = test_client.post("/ingest", json={"paths": [str(doc)]})
    assert ingest.status_code == 200

    with db.rag_connection(get_settings()) as conn:
        conn.execute("UPDATE chunks SET embedding_dim = embedding_dim + 1")
        conn.commit()

    response = test_client.get("/ask", params={"q": "drift?"})
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"]["type"] == "http_error"
    assert "embedding_dim mismatch" in payload["error"]["message"]


def test_loop_not_found_returns_404(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.get("/loops/999999")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"
    assert "Loop not found" in data["error"]["message"]


def test_loop_update_not_found_returns_404(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.patch("/loops/999999", json={"title": "Updated"})
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"


def test_loop_close_not_found_returns_404(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.post("/loops/999999/close", json={"status": "completed"})
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"


def test_loop_status_not_found_returns_404(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.post("/loops/999999/status", json={"status": "actionable"})
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"


def test_loop_enrich_not_found_returns_404(test_client: TestClient, tmp_data_dir: Path) -> None:
    response = test_client.post("/loops/999999/enrich")
    assert response.status_code == 404
    data = response.json()
    assert data["error"]["type"] == "not_found"


def test_loop_capture_invalid_timestamp_returns_validation_error(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    response = test_client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "not-a-timestamp",
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["type"] == "validation_error"


def test_loop_update_empty_fields_returns_400(
    test_client: TestClient, tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()

    capture_resp = test_client.post(
        "/loops/capture",
        json={
            "raw_text": "Test loop",
            "captured_at": "2024-01-01T12:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert capture_resp.status_code == 200
    loop_id = capture_resp.json()["id"]

    response = test_client.patch(f"/loops/{loop_id}", json={})
    assert response.status_code == 400
    data = response.json()
    assert data["error"]["type"] == "http_error"
    assert "no_fields_to_update" in data["error"]["message"]


def test_generic_exception_sanitized_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import logging
    from unittest.mock import patch

    from cloop.main import app

    def mock_ingest_paths(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Simulated ingestion failure with /secret/path")

    monkeypatch.setattr("cloop.routes.rag.ingest_paths", mock_ingest_paths)
    client = TestClient(app, raise_server_exceptions=False)

    doc = tmp_path / "test.txt"
    doc.write_text("content", encoding="utf-8")

    with patch.object(logging.getLogger("cloop.handlers"), "exception") as mock_log:
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
    import logging
    from unittest.mock import patch

    from cloop.main import app

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

        monkeypatch.setattr("cloop.routes.rag.ingest_paths", mock_fail)
        client = TestClient(app, raise_server_exceptions=False)

        doc = tmp_path / "test.txt"
        doc.write_text("content", encoding="utf-8")

        with patch.object(logging.getLogger("cloop.handlers"), "exception"):
            response = client.post("/ingest", json={"paths": [str(doc)]})

        response_text = response.text.lower()
        assert pattern.lower() not in response_text, (
            f"Sensitive pattern '{pattern}' exposed in response"
        )


def test_mock_responses_match_litellm_format(
    mock_completion_response: Dict[str, Any],
    mock_tool_call_response: Dict[str, Any],
    mock_tool_final_response: Dict[str, Any],
) -> None:
    """Verify all mock responses have correct litellm.completion() format.

    This test ensures our mocks stay aligned with the actual API contract,
    preventing silent breakage if litellm response format changes.
    """
    for response in [mock_completion_response, mock_tool_final_response]:
        assert "choices" in response
        assert isinstance(response["choices"], list)
        assert len(response["choices"]) >= 1
        assert "message" in response["choices"][0]
        assert "content" in response["choices"][0]["message"]
        assert "model" in response
        assert "usage" in response

    assert "tool_calls" in mock_tool_call_response["choices"][0]["message"]
    tool_call = mock_tool_call_response["choices"][0]["message"]["tool_calls"][0]
    assert tool_call["type"] == "function"
    assert "name" in tool_call["function"]
    assert "arguments" in tool_call["function"]


def test_ui_contains_chat_and_rag_elements(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify the index.html contains chat and RAG UI elements."""
    response = test_client.get("/")
    assert response.status_code == 200
    html = response.text

    # Check for tab navigation
    assert 'data-tab="inbox"' in html
    assert 'data-tab="chat"' in html
    assert 'data-tab="rag"' in html

    # Check for chat elements (static structure - dynamic elements rendered by JS)
    assert 'id="chat-form"' in html
    assert 'id="chat-input"' in html
    assert 'id="chat-messages"' in html

    # Check for RAG elements (static structure - dynamic elements rendered by JS)
    assert 'id="rag-form"' in html
    assert 'id="rag-input"' in html
    assert 'id="rag-answer"' in html
    assert "Export data" in html
    assert "Import data" in html

    # Verify modular CSS/JS is loaded (new architecture)
    assert "chat.js" in html or "init.js" in html
    assert "chat-rag.css" in html or "components.css" in html
    assert "/static/js/init.js?v=" in html


def test_ui_contains_next_actions_elements(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify the index.html contains Next Actions tab and bucket elements."""
    response = test_client.get("/")
    assert response.status_code == 200
    html = response.text

    # Check for Next tab
    assert 'data-tab="next"' in html

    # Check for Next view container (static structure)
    assert 'id="next-main"' in html
    assert 'id="next-buckets"' in html

    # Check for refresh button
    assert 'id="refresh-next-btn"' in html

    # Verify modular JS/CSS is loaded for Next view (new architecture)
    assert "next.js" in html or "init.js" in html


def test_loops_next_endpoint_data_flow(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify /loops/next returns expected bucket structure that UI can render.

    This test ensures the API returns data in the format the Next view expects,
    with all fields needed for renderLoop() and renderPriorityBadges().
    """
    # Create some loops with enrichment data (use inbox status to avoid autopilot)
    for i in range(3):
        response = test_client.post(
            "/loops/capture",
            json={
                "raw_text": f"Task {i} for next view",
                "captured_at": "2024-01-01T12:00:00Z",
                "client_tz_offset_min": 0,
                "actionable": False,  # inbox status - no autopilot
            },
        )
        assert response.status_code == 200
        loop_id = response.json()["id"]

        # Update with next_action and enrichment data to make it appear in next view
        test_client.patch(
            f"/loops/{loop_id}",
            json={
                "next_action": f"Do task {i}",
                "urgency": 0.8 if i == 0 else 0.5,
                "importance": 0.9 if i == 1 else 0.4,
                "time_minutes": 15 if i == 0 else 60,
                "activation_energy": 1 if i == 0 else 2,
            },
        )

    # Get next loops
    next_response = test_client.get("/loops/next?limit=10")
    assert next_response.status_code == 200
    data = next_response.json()

    # Verify bucket structure matches UI expectations
    assert "due_soon" in data
    assert "quick_wins" in data
    assert "high_leverage" in data
    assert "standard" in data

    # Each bucket should be a list
    for bucket_name in ["due_soon", "quick_wins", "high_leverage", "standard"]:
        assert isinstance(data[bucket_name], list)

    # Verify at least some loops were categorized
    total_loops = sum(len(data[b]) for b in ["due_soon", "quick_wins", "high_leverage", "standard"])
    assert total_loops > 0, "Expected at least one loop to be categorized"

    # Verify fields needed by renderLoop() and renderPriorityBadges()
    for bucket_name in ["due_soon", "quick_wins", "high_leverage", "standard"]:
        for loop in data[bucket_name]:
            # Core fields needed by renderLoop()
            assert "id" in loop, "Loop missing id field"
            assert "raw_text" in loop, "Loop missing raw_text field"
            assert "status" in loop, "Loop missing status field"
            assert "captured_at_utc" in loop, "Loop missing captured_at_utc field"
            assert "updated_at_utc" in loop, "Loop missing updated_at_utc field"
            assert "tags" in loop, "Loop missing tags field"
            assert isinstance(loop["tags"], list), "tags should be a list"

            # Fields needed by renderPriorityBadges()
            # These may be null for unenriched loops, but the fields should exist
            assert "urgency" in loop, "Loop missing urgency field"
            assert "importance" in loop, "Loop missing importance field"
            assert "activation_energy" in loop, "Loop missing activation_energy field"


def test_chat_streaming_ui_flow(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Test chat streaming works end-to-end for UI consumption."""
    payload = {"messages": [{"role": "user", "content": "Hello"}], "tool_mode": "none"}

    with test_client.stream("POST", "/chat?stream=true", json=payload) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        body = "".join(chunk for chunk in response.iter_text())
        assert "event: token" in body or "event: done" in body


def test_chat_streaming_with_llm_tool_mode_returns_400(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """Streaming with tool_mode='llm' must return 400 error."""
    payload = {
        "messages": [{"role": "user", "content": "Stream with tools"}],
        "tool_mode": "llm",
    }

    response = test_client.post("/chat?stream=true", json=payload)
    assert response.status_code == 400
    error_data = response.json()
    assert "error" in error_data
    assert "message" in error_data["error"]
    assert "Streaming not supported" in error_data["error"]["message"]
    assert "llm tool_mode" in error_data["error"]["message"]


def test_rag_returns_sources_for_ui(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify RAG endpoint returns source structure needed for UI citations."""
    doc = tmp_data_dir / "source-test.txt"
    doc.write_text("This is test content for source citations.", encoding="utf-8")

    ingest = test_client.post("/ingest", json={"paths": [str(doc)]})
    assert ingest.status_code == 200

    response = test_client.get("/ask", params={"q": "test content"})
    assert response.status_code == 200
    data = response.json()

    assert data["answer"]
    assert data["sources"]
    for source in data["sources"]:
        assert "document_path" in source
        assert "chunk_index" in source
        assert "score" in source


def test_snooze_single_loop_via_api(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Test that snooze_until_utc can be set via PATCH /loops/{id}."""
    # Create a loop
    create_response = test_client.post(
        "/loops/capture",
        json={
            "raw_text": "Test snooze",
            "captured_at": "2026-02-15T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert create_response.status_code == 200
    loop_id = create_response.json()["id"]

    # Snooze the loop
    snooze_time = "2026-02-16T10:00:00Z"
    snooze_response = test_client.patch(
        f"/loops/{loop_id}",
        json={"snooze_until_utc": snooze_time},
    )
    assert snooze_response.status_code == 200
    # API may return +00:00 or Z format depending on how timestamp is formatted
    assert snooze_response.json()["snooze_until_utc"].startswith("2026-02-16T10:00:00")

    # Verify the snooze is persisted
    get_response = test_client.get(f"/loops/{loop_id}")
    assert get_response.status_code == 200
    assert get_response.json()["snooze_until_utc"].startswith("2026-02-16T10:00:00")


def test_clear_snooze(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Test that snooze can be cleared by setting snooze_until_utc to null."""
    # Create and snooze a loop
    create_response = test_client.post(
        "/loops/capture",
        json={
            "raw_text": "Test clear snooze",
            "captured_at": "2026-02-15T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    test_client.patch(
        f"/loops/{loop_id}",
        json={"snooze_until_utc": "2026-02-16T10:00:00Z"},
    )

    # Clear the snooze
    clear_response = test_client.patch(
        f"/loops/{loop_id}",
        json={"snooze_until_utc": None},
    )
    assert clear_response.status_code == 200
    assert clear_response.json()["snooze_until_utc"] is None


def test_recurrence_via_api(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Test that recurrence can be set via PATCH /loops/{id}."""
    # Create a loop
    create_response = test_client.post(
        "/loops/capture",
        json={
            "raw_text": "Test recurrence",
            "captured_at": "2026-02-15T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    loop_id = create_response.json()["id"]

    # Set recurrence
    recurrence_response = test_client.patch(
        f"/loops/{loop_id}",
        json={
            "recurrence_rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
            "recurrence_tz": "America/New_York",
            "recurrence_enabled": True,
        },
    )
    assert recurrence_response.status_code == 200
    data = recurrence_response.json()
    assert data["recurrence_rrule"] == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    assert data["recurrence_tz"] == "America/New_York"
    assert data["recurrence_enabled"] is True


def test_capture_with_natural_language_schedule(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """Test that capture with schedule phrase creates a recurring loop."""
    response = test_client.post(
        "/loops/capture",
        json={
            "raw_text": "Weekly standup",
            "captured_at": "2026-02-15T10:00:00Z",
            "client_tz_offset_min": -300,  # EST
            "schedule": "every weekday",
        },
    )
    assert response.status_code == 200
    data = response.json()
    # Should have parsed to an RRULE
    assert data["recurrence_rrule"] is not None
    assert "FREQ=WEEKLY" in data["recurrence_rrule"]


def test_bulk_snooze_endpoint(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Test bulk snooze endpoint used by UI bulk actions."""
    # Create two loops
    ids = []
    for i in range(2):
        response = test_client.post(
            "/loops/capture",
            json={
                "raw_text": f"Bulk snooze test {i}",
                "captured_at": "2026-02-15T10:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        ids.append(response.json()["id"])

    # Bulk snooze
    snooze_time = "2026-02-17T10:00:00Z"
    response = test_client.post(
        "/loops/bulk/snooze",
        json={
            "items": [
                {"loop_id": ids[0], "snooze_until_utc": snooze_time},
                {"loop_id": ids[1], "snooze_until_utc": snooze_time},
            ],
            "transactional": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["succeeded"] == 2
    assert data["failed"] == 0


def test_ui_contains_snooze_and_recurrence_elements(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """Verify the index.html loads modular JS/CSS for snooze and recurrence features."""
    response = test_client.get("/")
    assert response.status_code == 200
    html = response.text

    # Verify modular JS/CSS is loaded (new architecture)
    # Snooze and recurrence are dynamically rendered by JS modules
    assert "init.js" in html
    assert "loop.js" in html or "modals.js" in html or "components.css" in html
    # Check for snooze in help modal (separate span elements for text and shortcut)
    assert ">Snooze<" in html or "Snooze</span>" in html
    assert ">s</span>" in html or "help-key" in html.lower()


def test_loop_metrics_endpoint(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify /loops/metrics returns expected SLI structure and values."""
    # Create some loops with various states
    for i in range(5):
        response = test_client.post(
            "/loops/capture",
            json={
                "raw_text": f"Metrics test loop {i}",
                "captured_at": "2026-02-15T10:00:00Z",
                "client_tz_offset_min": 0,
                "actionable": i < 3,  # 3 actionable, 2 inbox
            },
        )
        assert response.status_code == 200

    # Get metrics
    metrics_response = test_client.get("/loops/metrics")
    assert metrics_response.status_code == 200
    data = metrics_response.json()

    # Verify required fields exist
    assert "generated_at_utc" in data
    assert "total_loops" in data
    assert "status_counts" in data
    assert "stale_open_count" in data
    assert "blocked_too_long_count" in data
    assert "no_next_action_count" in data
    assert "enrichment_pending_count" in data
    assert "enrichment_failed_count" in data
    assert "capture_count_24h" in data
    assert "completion_count_24h" in data
    assert "avg_age_open_hours" in data

    # Verify status_counts structure
    status_counts = data["status_counts"]
    assert "inbox" in status_counts
    assert "actionable" in status_counts
    assert "blocked" in status_counts
    assert "scheduled" in status_counts
    assert "completed" in status_counts
    assert "dropped" in status_counts

    # Verify counts match created loops
    assert data["total_loops"] == 5
    assert status_counts["inbox"] == 2
    assert status_counts["actionable"] == 3


def test_loop_metrics_empty_db(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify metrics endpoint handles empty database gracefully."""
    response = test_client.get("/loops/metrics")
    assert response.status_code == 200
    data = response.json()

    assert data["total_loops"] == 0
    assert data["stale_open_count"] == 0
    assert data["avg_age_open_hours"] is None  # No open loops


def test_web_root_returns_html(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify GET / returns index.html with proper content-type."""
    response = test_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert "<!doctype html>" in response.text.lower()
    assert "<html" in response.text.lower()


def test_web_root_contains_ui_elements(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify index.html contains expected UI structure."""
    response = test_client.get("/")
    assert response.status_code == 200
    html = response.text
    # Key UI elements that should always be present
    assert "<title>" in html
    assert "</html>" in html.lower()


def test_web_manifest_returns_json(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify GET /manifest.json returns PWA manifest with correct headers."""
    response = test_client.get("/manifest.json")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/manifest+json"
    assert "Cache-Control" in response.headers
    assert "max-age=86400" in response.headers["Cache-Control"]

    # Verify it's valid JSON with expected fields
    data = response.json()
    assert "name" in data or "short_name" in data
    assert "icons" in data or "display" in data


def test_web_service_worker_returns_js(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify GET /sw.js returns service worker with correct headers."""
    response = test_client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/javascript"
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["Service-Worker-Allowed"] == "/"

    # Verify it's valid JavaScript (contains expected content)
    js = response.text
    assert "self.addEventListener" in js or "importScripts" in js or "const" in js or "var" in js


def test_web_static_files_served(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify static files are served from /static/ path."""
    # Test manifest.json via static path (since it's in static dir)
    response = test_client.get("/static/manifest.json")
    assert response.status_code == 200
    assert response.headers["content-type"] in ["application/json", "application/manifest+json"]


def test_web_static_file_not_found(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify requesting non-existent static file returns 404."""
    response = test_client.get("/static/nonexistent-file-12345.txt")
    assert response.status_code == 404


def test_web_malformed_paths(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify malformed or suspicious paths don't break the server."""
    # Directory traversal attempt
    response = test_client.get("/static/../../../etc/passwd")
    assert response.status_code == 404

    # Empty path segments - should either 404 or handle gracefully
    response = test_client.get("/static//double-slash")
    assert response.status_code in [200, 404]


def test_web_root_missing_index_html_returns_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify GET / returns 404 when index.html is missing."""
    # Create a temporary static dir without index.html
    static_dir = tmp_path / "static"
    static_dir.mkdir()

    # Create a minimal manifest.json so other routes work
    (static_dir / "manifest.json").write_text('{"name": "test"}')
    (static_dir / "sw.js").write_text("// test")

    # Patch the static directory
    from cloop import web

    monkeypatch.setattr(web, "_STATIC_DIR", static_dir)

    from cloop.main import app

    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 404


def test_web_manifest_missing_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /manifest.json returns 404 when file is missing."""
    static_dir = tmp_path / "static"
    static_dir.mkdir()

    # Create index.html but not manifest.json
    (static_dir / "index.html").write_text("<html></html>")
    (static_dir / "sw.js").write_text("// test")

    from cloop import web

    monkeypatch.setattr(web, "_STATIC_DIR", static_dir)

    from cloop.main import app

    client = TestClient(app)

    response = client.get("/manifest.json")
    assert response.status_code == 404


def test_web_sw_missing_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify GET /sw.js returns 404 when file is missing."""
    static_dir = tmp_path / "static"
    static_dir.mkdir()

    # Create index.html but not sw.js
    (static_dir / "index.html").write_text("<html></html>")
    (static_dir / "manifest.json").write_text('{"name": "test"}')

    from cloop import web

    monkeypatch.setattr(web, "_STATIC_DIR", static_dir)

    from cloop.main import app

    client = TestClient(app)

    response = client.get("/sw.js")
    assert response.status_code == 404


def test_bulk_update_exceeds_limit(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Bulk update with more than 100 items should fail."""
    from cloop.constants import BULK_OPERATION_MAX_ITEMS

    # Create enough loops to exceed limit
    loop_ids = []
    for i in range(BULK_OPERATION_MAX_ITEMS + 5):
        resp = test_client.post(
            "/loops/capture",
            json={
                "raw_text": f"Test loop {i}",
                "captured_at": "2024-01-01T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_ids.append(resp.json()["id"])

    # Attempt bulk update with too many items
    updates = [{"loop_id": lid, "fields": {"next_action": "test"}} for lid in loop_ids]
    resp = test_client.post("/loops/bulk/update", json={"updates": updates})

    assert resp.status_code == 422  # Validation error
    assert "at most 100" in resp.json()["error"]["details"]["errors"][0]["msg"].lower()


def test_bulk_close_exceeds_limit(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Bulk close with more than 100 items should fail."""
    from cloop.constants import BULK_OPERATION_MAX_ITEMS

    # Create enough loops to exceed limit
    loop_ids = []
    for i in range(BULK_OPERATION_MAX_ITEMS + 5):
        resp = test_client.post(
            "/loops/capture",
            json={
                "raw_text": f"Test loop {i}",
                "captured_at": "2024-01-01T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_ids.append(resp.json()["id"])

    # Attempt bulk close with too many items
    items = [{"loop_id": lid, "status": "completed"} for lid in loop_ids]
    resp = test_client.post("/loops/bulk/close", json={"items": items})

    assert resp.status_code == 422  # Validation error
    assert "at most 100" in resp.json()["error"]["details"]["errors"][0]["msg"].lower()


def test_bulk_snooze_exceeds_limit(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Bulk snooze with more than 100 items should fail."""
    from cloop.constants import BULK_OPERATION_MAX_ITEMS

    # Create enough loops to exceed limit
    loop_ids = []
    for i in range(BULK_OPERATION_MAX_ITEMS + 5):
        resp = test_client.post(
            "/loops/capture",
            json={
                "raw_text": f"Test loop {i}",
                "captured_at": "2024-01-01T12:00:00Z",
                "client_tz_offset_min": 0,
            },
        )
        loop_ids.append(resp.json()["id"])

    # Attempt bulk snooze with too many items
    items = [{"loop_id": lid, "snooze_until_utc": "2024-02-01T12:00:00Z"} for lid in loop_ids]
    resp = test_client.post("/loops/bulk/snooze", json={"items": items})

    assert resp.status_code == 422  # Validation error
    assert "at most 100" in resp.json()["error"]["details"]["errors"][0]["msg"].lower()


def test_chat_loop_context_disabled_by_default(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Loop context is NOT injected when not requested (defaults to False)."""
    # Create an actionable loop using the service
    from cloop import db
    from cloop.loops.models import LoopStatus
    from cloop.loops.service import capture_loop
    from cloop.settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        result = capture_loop(
            raw_text="Test task for default context",
            captured_at_iso="2026-02-18T10:00:00Z",
            client_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        # Transition to actionable with next_action (required for next_loops)
        conn.execute(
            "UPDATE loops SET status = 'actionable', next_action = 'Do something' WHERE id = ?",
            (result["id"],),
        )
        conn.commit()

    # Chat without context injection
    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What should I do?"}],
            "tool_mode": "none",
        },
    )
    assert response.status_code == 200

    # Verify no loop context in recorded interaction
    from cloop import db
    from cloop.settings import get_settings

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT request_payload, response_payload FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    request_payload = json.loads(row["request_payload"])
    response_payload = json.loads(row["response_payload"])

    # When not specified, include_loop_context defaults to False
    assert request_payload.get("include_loop_context") is False
    assert "loop_context" not in response_payload.get("context", {})


def test_chat_loop_context_injected_when_enabled(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """Loop context IS injected when include_loop_context=True."""
    # Create an actionable loop using the service
    from cloop import db
    from cloop.loops.models import LoopStatus
    from cloop.loops.service import capture_loop
    from cloop.settings import get_settings

    settings = get_settings()
    with db.core_connection(settings) as conn:
        result = capture_loop(
            raw_text="Actionable task for context test",
            captured_at_iso="2026-02-18T10:00:00Z",
            client_tz_offset_min=0,
            status=LoopStatus.INBOX,
            conn=conn,
        )
        # Transition to actionable with next_action (required for next_loops)
        conn.execute(
            "UPDATE loops SET status = 'actionable', next_action = 'Do something' WHERE id = ?",
            (result["id"],),
        )
        conn.commit()

    # Chat WITH context injection
    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What should I do?"}],
            "tool_mode": "none",
            "include_loop_context": True,
        },
    )
    assert response.status_code == 200

    # Verify loop context is present
    from cloop import db
    from cloop.settings import get_settings

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT request_payload, response_payload FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    request_payload = json.loads(row["request_payload"])
    response_payload = json.loads(row["response_payload"])

    assert request_payload.get("include_loop_context") is True
    assert "loop_context" in response_payload.get("context", {})
    loop_context = response_payload["context"]["loop_context"]
    assert (
        "Loop Context" in loop_context
        or "Quick Wins" in loop_context
        or "Standard" in loop_context
        or "High Leverage" in loop_context
    )


def test_chat_injects_grounding_guidance_when_loop_context_enabled(
    test_client: TestClient,
    tmp_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_chat_completion(
        messages: list[dict[str, Any]],
        *,
        settings: Any = None,
    ) -> tuple[str, dict[str, Any]]:
        captured["messages"] = messages
        return "grounded-response", {"latency_ms": 1.0, "model": "mock-llm", "usage": {}}

    monkeypatch.setattr("cloop.routes.chat.chat_completion", fake_chat_completion)

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What should I do next?"}],
            "tool_mode": "none",
            "include_loop_context": True,
        },
    )
    assert response.status_code == 200
    messages = captured["messages"]
    assert messages[0]["role"] == "system"
    assert "loop-aware planning assistant" in messages[0]["content"]
    assert "Avoid motivational filler" in messages[0]["content"]


def test_chat_ui_requests_loop_and_memory_context_in_static_client() -> None:
    api_path = Path(__file__).resolve().parents[1] / "src" / "cloop" / "static" / "js" / "api.js"
    api_js = api_path.read_text(encoding="utf-8")
    assert "include_loop_context: options.includeLoopContext ?? true" in api_js
    assert "include_memory_context: options.includeMemoryContext ?? true" in api_js


def test_chat_logging_tolerates_non_json_usage_objects(
    test_client: TestClient,
    tmp_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UsageLike:
        def model_dump(self) -> dict[str, int]:
            return {"prompt_tokens": 3, "completion_tokens": 5}

    def fake_chat_completion(
        messages: list[dict[str, Any]],
        *,
        settings: Any = None,
    ) -> tuple[str, dict[str, Any]]:
        return "grounded-response", {
            "latency_ms": 1.0,
            "model": "mock-llm",
            "usage": UsageLike(),
        }

    monkeypatch.setattr("cloop.routes.chat.chat_completion", fake_chat_completion)

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What should I focus on next?"}],
            "tool_mode": "none",
            "include_loop_context": True,
        },
    )
    assert response.status_code == 200


def test_chat_loop_context_empty_when_no_loops(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Loop context is empty/absent when no relevant loops exist."""
    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "tool_mode": "none",
            "include_loop_context": True,
        },
    )
    assert response.status_code == 200

    from cloop import db
    from cloop.settings import get_settings

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT response_payload FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    response_payload = json.loads(row["response_payload"])

    # Either absent or empty string is acceptable
    loop_context = response_payload.get("context", {}).get("loop_context")
    assert loop_context is None or loop_context == ""


def test_chat_memory_context_not_injected_by_default(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """Memory context is NOT injected when include_memory_context is False/default."""
    # Create a memory entry
    test_client.post(
        "/memory",
        json={"content": "I prefer dark mode", "category": "preference"},
    )

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "tool_mode": "none",
        },
    )
    assert response.status_code == 200

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT request_payload, response_payload FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    request_payload = json.loads(row["request_payload"])
    response_payload = json.loads(row["response_payload"])

    assert request_payload.get("include_memory_context") is False
    assert "memory_context" not in response_payload.get("context", {})


def test_chat_memory_context_injected_when_enabled(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """Memory context IS injected when include_memory_context=True."""
    # Create a memory entry
    test_client.post(
        "/memory",
        json={"content": "I prefer dark mode", "category": "preference", "priority": 50},
    )

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "tool_mode": "none",
            "include_memory_context": True,
        },
    )
    assert response.status_code == 200

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT response_payload FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    response_payload = json.loads(row["response_payload"])

    assert "memory_context" in response_payload.get("context", {})
    memory_context = response_payload["context"]["memory_context"]
    assert "User Memory" in memory_context
    assert "dark mode" in memory_context.lower()


def test_chat_memory_context_respects_limit(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Memory context respects the memory_limit parameter."""
    # Create multiple memory entries
    for i in range(15):
        test_client.post(
            "/memory",
            json={"content": f"Memory {i}", "category": "fact", "priority": i},
        )

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "tool_mode": "none",
            "include_memory_context": True,
            "memory_limit": 5,
        },
    )
    assert response.status_code == 200

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT response_payload FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    response_payload = json.loads(row["response_payload"])
    memory_context = response_payload["context"].get("memory_context", "")

    # Should have at most 5 entries (limit applied)
    count = memory_context.count("- ")
    assert count <= 5


def test_chat_memory_context_empty_when_no_memories(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """Memory context is absent when no memories exist."""
    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "Hello"}],
            "tool_mode": "none",
            "include_memory_context": True,
        },
    )
    assert response.status_code == 200

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT response_payload FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    response_payload = json.loads(row["response_payload"])

    # Either absent or empty string is acceptable
    memory_context = response_payload.get("context", {}).get("memory_context")
    assert memory_context is None or memory_context == ""


def test_chat_rag_context_disabled_by_default(test_client: TestClient, tmp_data_dir: Path) -> None:
    """RAG context is NOT retrieved when not requested (defaults to False)."""
    doc = tmp_data_dir / "knowledge.txt"
    doc.write_text("The answer to everything is 42.", encoding="utf-8")
    ingest = test_client.post("/ingest", json={"paths": [str(doc)]})
    assert ingest.status_code == 200

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What is the answer?"}],
            "tool_mode": "none",
        },
    )
    assert response.status_code == 200

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT request_payload, selected_chunks FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    request_payload = json.loads(row["request_payload"])
    selected_chunks = json.loads(row["selected_chunks"])

    assert request_payload.get("include_rag_context") is False
    assert selected_chunks == []


def test_chat_rag_context_injected_when_enabled(
    test_client: TestClient, tmp_data_dir: Path
) -> None:
    """RAG context IS retrieved and injected when include_rag_context=True."""
    doc = tmp_data_dir / "secret.txt"
    doc.write_text("The secret code is ALPHA-7749.", encoding="utf-8")
    ingest = test_client.post("/ingest", json={"paths": [str(doc)]})
    assert ingest.status_code == 200

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What is the secret code?"}],
            "tool_mode": "none",
            "include_rag_context": True,
        },
    )
    assert response.status_code == 200

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT request_payload, selected_chunks FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    request_payload = json.loads(row["request_payload"])
    selected_chunks = json.loads(row["selected_chunks"])

    assert request_payload.get("include_rag_context") is True
    assert len(selected_chunks) >= 1
    assert any("ALPHA-7749" in chunk.get("content", "") for chunk in selected_chunks)


def test_chat_rag_context_with_scope(test_client: TestClient, tmp_data_dir: Path) -> None:
    """RAG context respects scope filter."""
    doc_a = tmp_data_dir / "alpha.txt"
    doc_b = tmp_data_dir / "beta.txt"
    doc_a.write_text("Alpha project uses Python.", encoding="utf-8")
    doc_b.write_text("Beta project uses Rust.", encoding="utf-8")

    ingest = test_client.post("/ingest", json={"paths": [str(doc_a), str(doc_b)]})
    assert ingest.status_code == 200

    response = test_client.post(
        "/chat",
        json={
            "messages": [{"role": "user", "content": "What language?"}],
            "tool_mode": "none",
            "include_rag_context": True,
            "rag_scope": "alpha.txt",
        },
    )
    assert response.status_code == 200

    with db.core_connection(get_settings()) as conn:
        row = conn.execute(
            "SELECT selected_chunks FROM interactions "
            "WHERE endpoint = '/chat' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    selected_chunks = json.loads(row["selected_chunks"])

    assert len(selected_chunks) >= 1
    assert all("alpha.txt" in chunk.get("document_path", "") for chunk in selected_chunks)


def test_chat_rag_context_graceful_failure(
    test_client: TestClient, tmp_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chat continues without error when RAG retrieval fails."""
    from unittest.mock import patch

    doc = tmp_data_dir / "test.txt"
    doc.write_text("Test content", encoding="utf-8")
    test_client.post("/ingest", json={"paths": [str(doc)]})

    def mock_retrieve_fail(*args: Any, **kwargs: Any) -> List[Dict[str, Any]]:
        raise RuntimeError("Simulated RAG failure")

    with patch("cloop.routes.chat.retrieve_similar_chunks", mock_retrieve_fail):
        response = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Hello"}],
                "tool_mode": "none",
                "include_rag_context": True,
            },
        )

    assert response.status_code == 200
