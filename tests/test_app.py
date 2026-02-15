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
            "title": "todo",
            "body": "remember to test",
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
        "tool_call": {"name": "read_note", "note_id": note_id},
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

    # Check for chat elements
    assert 'id="chat-form"' in html
    assert 'id="chat-input"' in html
    assert 'id="chat-messages"' in html
    assert "chat-bubble" in html

    # Check for RAG elements
    assert 'id="rag-form"' in html
    assert 'id="rag-input"' in html
    assert 'id="rag-answer"' in html
    assert "rag-sources" in html


def test_ui_contains_next_actions_elements(test_client: TestClient, tmp_data_dir: Path) -> None:
    """Verify the index.html contains Next Actions tab and bucket elements."""
    response = test_client.get("/")
    assert response.status_code == 200
    html = response.text

    # Check for Next tab
    assert 'data-tab="next"' in html

    # Check for Next view container
    assert 'id="next-main"' in html
    assert 'id="next-buckets"' in html

    # Check for bucket CSS classes
    assert "next-bucket" in html
    assert "bucket-due_soon" in html.replace(" ", "") or "due_soon" in html
    assert "bucket-quick_wins" in html.replace(" ", "") or "quick_wins" in html
    assert "bucket-high_leverage" in html.replace(" ", "") or "high_leverage" in html

    # Check for refresh button
    assert 'id="refresh-next-btn"' in html

    # Check for priority badge styles
    assert "priority-score" in html or "priority-" in html


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
