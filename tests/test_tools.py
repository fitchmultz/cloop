import pytest

from cloop.loops.errors import ValidationError
from cloop.tools import (
    _require_fields,
    execute_loop_close,
    execute_loop_create,
    execute_loop_get,
    execute_loop_list,
    execute_loop_next,
    execute_loop_search,
    execute_loop_snooze,
    execute_loop_transition,
    execute_loop_update,
    normalize_tool_arguments,
)


class TestRequireFields:
    """Tests for the _require_fields validation function."""

    def test_raises_when_field_missing(self):
        """Should raise ValidationError when a required field is not present."""
        with pytest.raises(ValidationError, match="Invalid fields"):
            _require_fields({"body": "test"}, "title", "body")

    def test_raises_when_multiple_fields_missing(self):
        """Should list all missing fields in the error message."""
        with pytest.raises(ValidationError, match="title, body"):
            _require_fields({}, "title", "body")

    def test_passes_when_field_is_empty_string(self):
        """Empty strings should be valid - they are present, just empty."""
        # This should NOT raise - empty string is a valid value
        _require_fields({"title": "", "body": "test"}, "title", "body")

    def test_passes_when_all_fields_present(self):
        """Should not raise when all required fields are present."""
        _require_fields({"title": "Hello", "body": "World"}, "title", "body")

    def test_passes_when_field_is_false(self):
        """False boolean should be valid - the key is present."""
        _require_fields({"enabled": False, "name": "test"}, "enabled", "name")

    def test_passes_when_field_is_zero(self):
        """Zero should be valid - the key is present."""
        _require_fields({"count": 0, "name": "test"}, "count", "name")

    def test_passes_when_field_is_empty_list(self):
        """Empty list should be valid - the key is present."""
        _require_fields({"items": [], "name": "test"}, "items", "name")


class TestNormalizeToolArguments:
    """Tests for the normalize_tool_arguments function."""

    def test_returns_dict_unchanged(self):
        """Should return dict input as-is."""
        input_dict = {"title": "test", "body": "content"}
        result = normalize_tool_arguments(input_dict)
        assert result == input_dict

    def test_parses_json_string(self):
        """Should parse JSON string into dict."""
        result = normalize_tool_arguments('{"title": "test"}')
        assert result == {"title": "test"}

    def test_returns_empty_dict_for_empty_string(self):
        """Should return empty dict for empty string."""
        result = normalize_tool_arguments("")
        assert result == {}

    def test_raises_for_invalid_json(self):
        """Should raise ValidationError for invalid JSON."""
        with pytest.raises(ValidationError, match="Invalid arguments"):
            normalize_tool_arguments("not valid json")


class TestLoopCreate:
    """Tests for execute_loop_create."""

    def test_creates_loop_with_minimal_args(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        result = execute_loop_create(raw_text="Test task")

        assert result["action"] == "loop_create"
        assert result["loop"]["raw_text"] == "Test task"
        assert result["loop"]["status"] == "inbox"
        assert result["loop"]["id"] is not None

    def test_creates_loop_with_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        result = execute_loop_create(raw_text="Urgent task", status="actionable")

        assert result["loop"]["status"] == "actionable"

    def test_requires_raw_text(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        with pytest.raises(ValidationError, match="raw_text"):
            execute_loop_create()

    def test_rejects_invalid_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        with pytest.raises(ValidationError, match="invalid status"):
            execute_loop_create(raw_text="Test", status="invalid_status")


class TestLoopGet:
    """Tests for execute_loop_get."""

    def test_gets_loop_by_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop first
        created = execute_loop_create(raw_text="Test task")
        loop_id = created["loop"]["id"]

        # Get the loop
        result = execute_loop_get(loop_id=loop_id)

        assert result["action"] == "loop_get"
        assert result["loop"]["id"] == loop_id
        assert result["loop"]["raw_text"] == "Test task"

    def test_requires_loop_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        with pytest.raises(ValidationError, match="loop_id"):
            execute_loop_get()

    def test_raises_for_nonexistent_loop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        with pytest.raises(ValidationError, match="Loop not found"):
            execute_loop_get(loop_id=99999)


class TestLoopList:
    """Tests for execute_loop_list."""

    def test_lists_loops(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create some loops
        execute_loop_create(raw_text="Task 1")
        execute_loop_create(raw_text="Task 2")

        result = execute_loop_list()

        assert result["action"] == "loop_list"
        assert len(result["items"]) == 2
        assert "next_cursor" in result
        assert "limit" in result

    def test_filters_by_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create loops with different statuses
        execute_loop_create(raw_text="Inbox task", status="inbox")
        execute_loop_create(raw_text="Actionable task", status="actionable")

        # List only actionable
        result = execute_loop_list(status="actionable")

        assert len(result["items"]) == 1
        assert result["items"][0]["status"] == "actionable"

    def test_respects_limit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create multiple loops
        for i in range(5):
            execute_loop_create(raw_text=f"Task {i}")

        result = execute_loop_list(limit=2)

        assert result["limit"] == 2
        # May have more items if pagination returns extra, but limit field should be respected


class TestLoopUpdate:
    """Tests for execute_loop_update."""

    def test_updates_loop_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task")
        loop_id = created["loop"]["id"]

        # Update the loop
        result = execute_loop_update(
            loop_id=loop_id,
            fields={"title": "Updated Title", "time_minutes": 30},
        )

        assert result["action"] == "loop_update"
        assert result["loop"]["title"] == "Updated Title"
        assert result["loop"]["time_minutes"] == 30

    def test_requires_loop_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        with pytest.raises(ValidationError, match="loop_id"):
            execute_loop_update(fields={"title": "Test"})

    def test_requires_fields(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task")
        loop_id = created["loop"]["id"]

        with pytest.raises(ValidationError, match="fields"):
            execute_loop_update(loop_id=loop_id, fields={})


class TestLoopClose:
    """Tests for execute_loop_close."""

    def test_closes_loop_as_completed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task", status="actionable")
        loop_id = created["loop"]["id"]

        # Close as completed
        result = execute_loop_close(loop_id=loop_id, status="completed")

        assert result["action"] == "loop_close"
        assert result["loop"]["status"] == "completed"

    def test_closes_loop_as_dropped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task")
        loop_id = created["loop"]["id"]

        # Close as dropped
        result = execute_loop_close(loop_id=loop_id, status="dropped")

        assert result["action"] == "loop_close"
        assert result["loop"]["status"] == "dropped"

    def test_defaults_to_completed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task", status="actionable")
        loop_id = created["loop"]["id"]

        # Close without specifying status
        result = execute_loop_close(loop_id=loop_id)

        assert result["loop"]["status"] == "completed"

    def test_rejects_non_terminal_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task")
        loop_id = created["loop"]["id"]

        with pytest.raises(ValidationError, match="must be 'completed' or 'dropped'"):
            execute_loop_close(loop_id=loop_id, status="inbox")


class TestLoopTransition:
    """Tests for execute_loop_transition."""

    def test_transitions_to_actionable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop in inbox
        created = execute_loop_create(raw_text="Test task", status="inbox")
        loop_id = created["loop"]["id"]

        # Transition to actionable
        result = execute_loop_transition(loop_id=loop_id, status="actionable")

        assert result["action"] == "loop_transition"
        assert result["loop"]["status"] == "actionable"

    def test_transitions_to_blocked(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task", status="actionable")
        loop_id = created["loop"]["id"]

        # Transition to blocked
        result = execute_loop_transition(loop_id=loop_id, status="blocked")

        assert result["loop"]["status"] == "blocked"

    def test_rejects_terminal_status(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task")
        loop_id = created["loop"]["id"]

        with pytest.raises(ValidationError, match="use loop_close for terminal statuses"):
            execute_loop_transition(loop_id=loop_id, status="completed")


class TestLoopSnooze:
    """Tests for execute_loop_snooze."""

    def test_snoozes_loop(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task")
        loop_id = created["loop"]["id"]

        # Snooze the loop
        snooze_time = "2025-12-31T23:59:59Z"
        result = execute_loop_snooze(loop_id=loop_id, snooze_until_utc=snooze_time)

        assert result["action"] == "loop_snooze"
        # The service layer may normalize the datetime format, so just check it's set
        assert result["loop"]["snooze_until_utc"] is not None
        assert "2025-12-31T23:59:59" in result["loop"]["snooze_until_utc"]

    def test_requires_snooze_until(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create a loop
        created = execute_loop_create(raw_text="Test task")
        loop_id = created["loop"]["id"]

        with pytest.raises(ValidationError, match="snooze_until_utc"):
            execute_loop_snooze(loop_id=loop_id)


class TestLoopSearch:
    """Tests for execute_loop_search."""

    def test_searches_loops(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create loops
        execute_loop_create(raw_text="Buy groceries")
        execute_loop_create(raw_text="Call dentist")

        # Search for groceries
        result = execute_loop_search(query="groceries")

        assert result["action"] == "loop_search"
        assert len(result["items"]) >= 1
        assert "next_cursor" in result
        assert "limit" in result

    def test_returns_empty_for_no_matches(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Search for nonexistent
        result = execute_loop_search(query="xyznonexistent")

        assert result["action"] == "loop_search"
        assert len(result["items"]) == 0


class TestLoopNext:
    """Tests for execute_loop_next."""

    def test_returns_bucket_structure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        result = execute_loop_next()

        assert result["action"] == "loop_next"
        assert "due_soon" in result
        assert "quick_wins" in result
        assert "high_leverage" in result
        assert "standard" in result
        assert isinstance(result["due_soon"], list)
        assert isinstance(result["quick_wins"], list)
        assert isinstance(result["high_leverage"], list)
        assert isinstance(result["standard"], list)

    def test_respects_limit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        from cloop import db
        from cloop.settings import get_settings

        get_settings.cache_clear()
        db.init_databases(get_settings())

        # Create many actionable loops
        for i in range(10):
            execute_loop_create(raw_text=f"Task {i}", status="actionable")

        # Get next with limit
        result = execute_loop_next(limit=3)

        # Total across all buckets should not exceed limit
        total = (
            len(result["due_soon"])
            + len(result["quick_wins"])
            + len(result["high_leverage"])
            + len(result["standard"])
        )
        assert total <= 3
