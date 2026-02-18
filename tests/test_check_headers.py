"""Tests for scripts/check_headers.py header validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_headers import has_valid_header  # type: ignore


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
