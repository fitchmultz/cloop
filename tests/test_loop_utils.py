"""Tests for loop utility functions.

Purpose:
    Verify correct behavior of tag normalization utilities.
"""

from cloop.loops.utils import normalize_tag, normalize_tags


class TestNormalizeTag:
    def test_lowercase(self):
        assert normalize_tag("WORK") == "work"

    def test_strip_whitespace(self):
        assert normalize_tag("  work  ") == "work"

    def test_strip_and_lower(self):
        assert normalize_tag("  WORK  ") == "work"

    def test_none_returns_none(self):
        assert normalize_tag(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_tag("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_tag("   ") is None

    def test_preserves_internal_spaces(self):
        assert normalize_tag("work item") == "work item"


class TestNormalizeTags:
    def test_empty_list(self):
        assert normalize_tags([]) == []

    def test_none_returns_empty_list(self):
        assert normalize_tags(None) == []

    def test_multiple_tags(self):
        assert normalize_tags(["WORK", "  home  ", "Personal"]) == ["work", "home", "personal"]

    def test_filters_empty_strings(self):
        assert normalize_tags(["work", "", "  ", "home"]) == ["work", "home"]

    def test_preserves_order(self):
        assert normalize_tags(["C", "B", "A"]) == ["c", "b", "a"]

    def test_converts_non_strings(self):
        assert normalize_tags([123, "work"]) == ["123", "work"]

    def test_mixed_empty_and_valid(self):
        result = normalize_tags(["  ", "VALID", "", "ANOTHER"])
        assert result == ["valid", "another"]
