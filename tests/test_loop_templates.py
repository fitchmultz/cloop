"""Loop template tests for Cloop.

Purpose:
    Test the loop template subsystem including creation, retrieval, update,
    deletion, variable substitution, and API endpoints.

Responsibilities:
    - Test template CRUD operations (create, read, update, delete)
    - Test system template protection (cannot modify/delete)
    - Test template variable substitution ({{date}}, {{day}}, etc.)
    - Test applying templates to capture requests
    - Test extracting update fields from template defaults
    - Test creating templates from existing loops
    - Test template API endpoints

Non-scope:
    - Loop capture without templates (see test_loop_capture.py)
    - Loop enrichment/prioritization (see test_loop_enrichment.py, test_loop_prioritization.py)
    - RAG functionality (see test_rag.py)
    - MCP server operations (see test_mcp_server.py)

Invariants/Assumptions:
    - Tests use isolated temporary databases via make_test_client fixture
    - System templates are created by database migrations
    - Template variable substitution uses UTC datetime internally
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cloop import db
from cloop.loops import repo, template_management
from cloop.loops.errors import ValidationError
from cloop.loops.models import LoopStatus
from cloop.loops.templates import (
    apply_template_to_capture,
    extract_update_fields_from_template,
    substitute_template_variables,
)
from cloop.settings import get_settings

# ============================================================================
# Loop Template Tests
# ============================================================================


def test_template_create_and_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test creating a template and listing templates."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a template
    template = repo.create_loop_template(
        name="Test Template",
        description="A test template",
        raw_text_pattern="Task for {{date}}",
        defaults_json={"tags": ["test"], "time_minutes": 30},
        is_system=False,
        conn=conn,
    )

    assert template["name"] == "Test Template"
    assert template["description"] == "A test template"
    assert template["is_system"] == 0

    # List templates
    templates = repo.list_loop_templates(conn=conn)
    assert any(t["name"] == "Test Template" for t in templates)

    conn.close()


def test_template_get_by_id_and_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test getting a template by ID and by name."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a template
    template = repo.create_loop_template(
        name="Get Test",
        description="Testing get methods",
        raw_text_pattern="Pattern",
        defaults_json={},
        conn=conn,
    )
    template_id = template["id"]

    # Get by ID
    by_id = repo.get_loop_template(template_id=template_id, conn=conn)
    assert by_id is not None
    assert by_id["name"] == "Get Test"

    # Get by name (case insensitive)
    by_name = repo.get_loop_template_by_name(name="get test", conn=conn)
    assert by_name is not None
    assert by_name["id"] == template_id

    conn.close()


def test_template_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client) -> None:
    """Test updating a template."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a template
    template = repo.create_loop_template(
        name="Update Test",
        description="Before update",
        raw_text_pattern="Old pattern",
        defaults_json={},
        conn=conn,
    )

    # Update the template
    updated = repo.update_loop_template(
        template_id=template["id"],
        name="Updated Name",
        description="After update",
        conn=conn,
    )

    assert updated["name"] == "Updated Name"
    assert updated["description"] == "After update"

    conn.close()


def test_template_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client) -> None:
    """Test deleting a template."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a template
    template = repo.create_loop_template(
        name="Delete Test",
        description="To be deleted",
        raw_text_pattern="",
        defaults_json={},
        conn=conn,
    )
    template_id = template["id"]

    # Delete the template
    deleted = repo.delete_loop_template(template_id=template_id, conn=conn)
    assert deleted is True

    # Verify it's gone
    by_id = repo.get_loop_template(template_id=template_id, conn=conn)
    assert by_id is None

    conn.close()


def test_system_template_cannot_be_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test that system templates cannot be modified or deleted."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Get a system template (created by migration)
    templates = repo.list_loop_templates(conn=conn)
    system_template = next((t for t in templates if t["is_system"]), None)
    assert system_template is not None

    # Try to update
    with pytest.raises(ValidationError, match="system templates cannot be modified"):
        repo.update_loop_template(
            template_id=system_template["id"],
            name="New Name",
            conn=conn,
        )

    # Try to delete
    with pytest.raises(ValidationError, match="system templates cannot be deleted"):
        repo.delete_loop_template(template_id=system_template["id"], conn=conn)

    conn.close()


def test_template_variable_substitution() -> None:
    """Test template variable substitution."""
    text = "Date: {{date}}, Day: {{day}}, Week: {{week}}, Month: {{month}}, Year: {{year}}"
    result = substitute_template_variables(
        text,
        now_utc=datetime(2026, 2, 14, 10, 30, 0, tzinfo=timezone.utc),
        tz_offset_min=0,
    )

    assert "Date: 2026-02-14" in result
    assert "Day: Saturday" in result
    assert "Week: 7" in result  # ISO week
    assert "Month: February" in result
    assert "Year: 2026" in result


def test_apply_template_to_capture() -> None:
    """Test applying a template to capture request defaults."""
    template = {
        "raw_text_pattern": "Meeting on {{date}}\n\nNotes:",
        "defaults_json": '{"tags": ["meeting"], "actionable": true, "time_minutes": 30}',
    }

    result = apply_template_to_capture(
        template=template,
        raw_text_override="Discuss project roadmap",
        now_utc=datetime(2026, 2, 14, 10, 30, 0, tzinfo=timezone.utc),
        tz_offset_min=0,
    )

    assert "Meeting on 2026-02-14" in result["raw_text"]
    assert "Discuss project roadmap" in result["raw_text"]
    assert result["tags"] == ["meeting"]
    assert result["actionable"] is True
    assert result["time_minutes"] == 30


def test_extract_update_fields_from_template() -> None:
    """Test extracting update fields from applied template defaults."""
    # Test with all fields populated
    applied = {
        "raw_text": "Some text",
        "tags": ["work", "urgent"],
        "time_minutes": 45,
        "activation_energy": 3,
        "urgency": 0.8,
        "importance": 0.9,
        "project": "my-project",
        "actionable": True,
        "scheduled": False,
        "blocked": False,
    }
    update_fields = extract_update_fields_from_template(applied)
    assert update_fields["tags"] == ["work", "urgent"]
    assert update_fields["time_minutes"] == 45
    assert update_fields["activation_energy"] == 3
    assert update_fields["urgency"] == 0.8
    assert update_fields["importance"] == 0.9
    assert update_fields["project"] == "my-project"
    # status flags should NOT be in update_fields
    assert "actionable" not in update_fields

    # Test with empty/None values - should not include those fields
    applied_empty = {
        "raw_text": "Some text",
        "tags": None,
        "time_minutes": None,
        "project": "",
        "actionable": False,
    }
    update_fields_empty = extract_update_fields_from_template(applied_empty)
    assert update_fields_empty == {}


def test_create_template_from_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test creating a template from an existing loop."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    conn = sqlite3.connect(settings.core_db_path)
    conn.row_factory = sqlite3.Row

    # Create a loop with tags
    loop = repo.create_loop(
        raw_text="Weekly review task",
        captured_at_utc="2026-02-14T10:00:00+00:00",
        captured_tz_offset_min=0,
        status=LoopStatus.ACTIONABLE,
        conn=conn,
    )
    repo.replace_loop_tags(loop_id=loop.id, tag_names=["weekly", "review"], conn=conn)
    repo.update_loop_fields(
        loop_id=loop.id,
        fields={"time_minutes": 30},
        conn=conn,
    )

    # Create template from loop
    template = template_management.create_template_from_loop(
        loop_id=loop.id,
        template_name="Weekly Review Template",
        conn=conn,
    )

    assert template["name"] == "Weekly Review Template"
    assert template["raw_text_pattern"] == "Weekly review task"
    assert "weekly" in template["defaults_json"]
    assert "review" in template["defaults_json"]

    conn.close()


def test_template_api_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test template API endpoints."""
    client = make_test_client()

    # List templates (should include system templates)
    response = client.get("/loops/templates")
    assert response.status_code == 200
    templates = response.json()["templates"]
    assert any(t["name"] == "Daily Standup" for t in templates)
    assert any(t["name"] == "Quick Task" for t in templates)

    # Create a template
    response = client.post(
        "/loops/templates",
        json={
            "name": "API Test Template",
            "description": "Created via API",
            "raw_text_pattern": "Task: {{date}}",
            "defaults": {"tags": ["api-test"], "time_minutes": 15},
        },
    )
    assert response.status_code == 201
    template_id = response.json()["id"]

    # Get template by ID
    response = client.get(f"/loops/templates/{template_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "API Test Template"

    # Capture with template
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "My task",
            "template_id": template_id,
            "captured_at": "2026-02-14T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    loop = response.json()
    assert "api-test" in loop["tags"]


def test_capture_with_template_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test capturing a loop using a template by name."""
    client = make_test_client()

    # Capture with template by name
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Standup notes",
            "template_name": "Daily Standup",
            "captured_at": "2026-02-14T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    assert response.status_code == 200
    loop = response.json()
    assert "standup" in loop["tags"]
    assert "daily" in loop["tags"]


def test_save_loop_as_template_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Test the save-as-template endpoint."""
    client = make_test_client()

    # Create a loop
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": "Weekly task to review",
            "actionable": True,
            "captured_at": "2026-02-14T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    )
    loop_id = response.json()["id"]

    # Add tags
    client.patch(f"/loops/{loop_id}", json={"tags": ["weekly"]})

    # Save as template
    response = client.post(
        f"/loops/{loop_id}/save-as-template",
        json={
            "name": "My Weekly Template",
        },
    )
    assert response.status_code == 201
    template = response.json()
    assert template["name"] == "My Weekly Template"
    assert template["is_system"] is False


def test_capture_fields_override_template_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Explicit capture fields must take precedence over template defaults."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)

    client = make_test_client()

    # Create a template with a default due_at_utc (+7 days)
    template_response = client.post(
        "/loops/templates",
        json={
            "name": "Precedence Test Template",
            "description": "Tests capture field precedence",
            "raw_text_pattern": "Task for {{date}}",
            "defaults": {
                "due_at_utc": "2026-02-27T10:00:00Z",  # +7 days from test date
                "time_minutes": 60,
            },
        },
    )
    assert template_response.status_code == 201
    template_id = template_response.json()["id"]

    # Capture with template but explicitly set due_at_utc to +1 day
    now = datetime.now(timezone.utc)
    explicit_due = (now + timedelta(days=1)).isoformat(timespec="seconds").replace("+00:00", "Z")

    capture_response = client.post(
        "/loops/capture",
        json={
            "raw_text": "My urgent task",
            "template_id": template_id,
            "captured_at": "2026-02-20T10:00:00Z",
            "client_tz_offset_min": 0,
            "due_at_utc": explicit_due,  # Explicit - must win over template default
            "time_minutes": 30,  # Explicit - must win over template default
        },
    )
    assert capture_response.status_code == 200
    loop = capture_response.json()

    # Explicit values must win (not template defaults)
    assert loop["due_at_utc"] is not None
    # Should be ~1 day out, not ~7 days
    due_dt = datetime.fromisoformat(loop["due_at_utc"].replace("Z", "+00:00"))
    delta_hours = (due_dt - now).total_seconds() / 3600
    assert delta_hours < 48, f"Expected ~24h but got {delta_hours}h - template default may have won"

    # time_minutes should also be explicit value
    assert loop["time_minutes"] == 30, "Expected explicit time_minutes=30, not template default 60"


def test_template_create_idempotency_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Creating a template with the same idempotency key should replay."""
    client = make_test_client()
    headers = {"Idempotency-Key": "template-create-key"}
    payload = {
        "name": "Idempotent Template",
        "description": "Created once",
        "raw_text_pattern": "Task: {{date}}",
        "defaults": {"tags": ["idempotent"]},
    }

    first = client.post("/loops/templates", json=payload, headers=headers)
    assert first.status_code == 201

    second = client.post("/loops/templates", json=payload, headers=headers)
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]


def test_save_as_template_idempotency_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_test_client
) -> None:
    """Saving a loop as a template should support idempotent retries."""
    client = make_test_client()
    loop = client.post(
        "/loops/capture",
        json={
            "raw_text": "Reusable loop",
            "captured_at": "2026-02-14T10:00:00Z",
            "client_tz_offset_min": 0,
        },
    ).json()

    headers = {"Idempotency-Key": "save-as-template-key"}
    payload = {"name": "Replayable Template"}

    first = client.post(f"/loops/{loop['id']}/save-as-template", json=payload, headers=headers)
    assert first.status_code == 201

    second = client.post(f"/loops/{loop['id']}/save-as-template", json=payload, headers=headers)
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
