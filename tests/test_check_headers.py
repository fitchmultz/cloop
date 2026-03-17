"""Tests for scripts/check_headers.py header validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_headers import has_valid_header, should_check  # type: ignore


class TestHeaderValidation:
    def test_valid_header_passes(self, tmp_path: Path):
        """File with all required sections passes validation."""
        filepath = tmp_path / "valid.py"
        filepath.write_text('''\
"""Module docstring.

Purpose:
    Test purpose.

Responsibilities:
    Test responsibility.

Non-scope:
    Test non-scope.
"""
pass
''')
        valid, msg = has_valid_header(filepath)
        assert valid is True
        assert msg == "OK"

    def test_missing_purpose_fails(self, tmp_path: Path):
        """File missing Purpose section fails."""
        filepath = tmp_path / "no_purpose.py"
        filepath.write_text('''\
"""Module docstring.

Responsibilities:
    Test responsibility.

Non-scope:
    Test non-scope.
"""
pass
''')
        valid, msg = has_valid_header(filepath)
        assert valid is False
        assert "Purpose" in msg

    def test_missing_responsibilities_fails(self, tmp_path: Path):
        """File missing Responsibilities section fails."""
        filepath = tmp_path / "no_resp.py"
        filepath.write_text('''\
"""Module docstring.

Purpose:
    Test purpose.

Non-scope:
    Test non-scope.
"""
pass
''')
        valid, msg = has_valid_header(filepath)
        assert valid is False
        assert "Responsibilities" in msg

    def test_missing_non_scope_fails(self, tmp_path: Path):
        """File missing Non-scope section fails."""
        filepath = tmp_path / "no_nonscope.py"
        filepath.write_text('''\
"""Module docstring.

Purpose:
    Test purpose.

Responsibilities:
    Test responsibility.
"""
pass
''')
        valid, msg = has_valid_header(filepath)
        assert valid is False
        assert "Non-scope" in msg

    def test_missing_multiple_sections_reports_all(self, tmp_path: Path):
        """Missing multiple sections reports all missing."""
        filepath = tmp_path / "minimal.py"
        filepath.write_text('''\
"""Module docstring with no sections."""
pass
''')
        valid, msg = has_valid_header(filepath)
        assert valid is False
        assert "Purpose" in msg
        assert "Responsibilities" in msg
        assert "Non-scope" in msg

    def test_missing_docstring_fails(self, tmp_path: Path):
        """File with no docstring fails."""
        filepath = tmp_path / "no_docstring.py"
        filepath.write_text("pass\n")
        valid, msg = has_valid_header(filepath)
        assert valid is False
        assert "docstring" in msg.lower()

    def test_syntax_error_fails(self, tmp_path: Path):
        """File with syntax error fails gracefully."""
        filepath = tmp_path / "syntax_error.py"
        filepath.write_text("def broken(\n")
        valid, msg = has_valid_header(filepath)
        assert valid is False
        assert "Syntax error" in msg

    def test_case_insensitive_matching(self, tmp_path: Path):
        """Section matching is case-insensitive."""
        filepath = tmp_path / "lowercase.py"
        filepath.write_text('''\
"""Module docstring.

purpose:
    lowercase purpose.

responsibilities:
    lowercase responsibilities.

non-scope:
    lowercase non-scope.
"""
pass
''')
        valid, msg = has_valid_header(filepath)
        assert valid is True

    def test_should_check_skips_nested_tests_directory(self, tmp_path: Path):
        """Test directories are skipped regardless of path separator assumptions."""
        filepath = tmp_path / "pkg" / "tests" / "example.py"
        filepath.parent.mkdir(parents=True)
        filepath.write_text("pass\n")
        assert should_check(filepath) is False

    def test_should_check_skips_named_tooling_directories(self, tmp_path: Path):
        """Path-part based skipping works for cache and virtualenv directories."""
        cache_file = tmp_path / "__pycache__" / "example.py"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("pass\n")
        assert should_check(cache_file) is False

        venv_file = tmp_path / ".venv" / "example.py"
        venv_file.parent.mkdir(parents=True)
        venv_file.write_text("pass\n")
        assert should_check(venv_file) is False

    def test_should_check_allows_regular_python_modules(self, tmp_path: Path):
        """Regular source files still participate in header validation."""
        filepath = tmp_path / "src" / "module.py"
        filepath.parent.mkdir(parents=True)
        filepath.write_text("pass\n")
        assert should_check(filepath) is True
