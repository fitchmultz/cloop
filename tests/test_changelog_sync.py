"""Changelog/version synchronization coverage tests.

Purpose:
    Ensure release metadata remains consistent between pyproject and changelog.

Responsibilities:
    - Verify current project version appears in CHANGELOG.md release headings.
    - Verify changelog keeps an [Unreleased] section.
    - Verify changelog sync script succeeds on repository state.

Non-scope:
    - Validating every changelog entry category or prose quality.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_changelog_sync.py"
RELEASE_HEADING_PATTERN = re.compile(
    r"^## \[(?P<version>\d+\.\d+\.\d+)\] - (?P<date>\d{4}-\d{2}-\d{2})$",
    re.MULTILINE,
)


def _project_version() -> str:
    """Read the version declared in pyproject.toml."""
    with PYPROJECT_PATH.open("rb") as handle:
        data = tomllib.load(handle)
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


def test_changelog_has_unreleased_section() -> None:
    """Changelog should retain an explicit [Unreleased] section."""
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    assert "## [Unreleased]" in text


def test_changelog_contains_current_project_version_heading() -> None:
    """Changelog should include a dated release heading for current version."""
    text = CHANGELOG_PATH.read_text(encoding="utf-8")
    version = _project_version()
    matches = {
        match.group("version"): match.group("date")
        for match in RELEASE_HEADING_PATTERN.finditer(text)
    }
    assert version in matches, f"Missing changelog heading for current version: {version}"


def test_changelog_sync_script_passes() -> None:
    """Changelog sync script should pass on committed repository metadata."""
    assert SCRIPT_PATH.exists(), "Missing scripts/check_changelog_sync.py"
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(REPO_ROOT)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_changelog_sync.py failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
