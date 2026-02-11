import pytest

from cloop.tools import _require_fields, normalize_tool_arguments


class TestRequireFields:
    """Tests for the _require_fields validation function."""

    def test_raises_when_field_missing(self):
        """Should raise ValueError when a required field is not present."""
        with pytest.raises(ValueError, match="Missing required fields: title"):
            _require_fields({"body": "test"}, "title", "body")

    def test_raises_when_multiple_fields_missing(self):
        """Should list all missing fields in the error message."""
        with pytest.raises(ValueError, match="Missing required fields: title, body"):
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
        """Should raise ValueError for invalid JSON."""
        with pytest.raises(ValueError, match="Invalid tool arguments"):
            normalize_tool_arguments("not valid json")
