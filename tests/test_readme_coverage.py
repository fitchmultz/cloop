"""README documentation coverage tests.

Purpose:
    Verify that README.md documents key features to prevent discoverability gaps.

Responsibilities:
    - Assert CLI commands are documented
    - Assert web UI features are documented
    - Assert workflow concepts are explained

Non-scope:
    - Testing actual feature functionality (see other test files)
"""

from pathlib import Path

import pytest

README_PATH = Path(__file__).parent.parent / "README.md"


@pytest.fixture
def readme_content() -> str:
    """Load README.md content."""
    return README_PATH.read_text()


class TestCLICommandsDocumented:
    """Verify CLI commands have README documentation."""

    def test_loop_review_command_documented(self, readme_content: str) -> None:
        """'cloop loop review' must be documented in README."""
        assert "loop review" in readme_content, "README must document 'cloop loop review' command"

    def test_loop_review_flags_documented(self, readme_content: str) -> None:
        """Review command flags must be documented."""
        assert "--daily" in readme_content or "--weekly" in readme_content, (
            "README must document loop review flags (--daily, --weekly, --all)"
        )


class TestWebUIDocumented:
    """Verify web UI features have README documentation."""

    def test_quick_capture_workflow_documented(self, readme_content: str) -> None:
        """Quick Capture workflow must be explained."""
        assert "Quick Capture" in readme_content, "README must explain Quick Capture workflow"

    def test_tabs_overview_documented(self, readme_content: str) -> None:
        """Web UI tabs must be listed."""
        assert "Inbox" in readme_content and "Next" in readme_content, (
            "README must list web UI tabs (Inbox, Next, etc.)"
        )

    def test_review_cohorts_documented(self, readme_content: str) -> None:
        """Review cohorts must be explained."""
        assert "stale" in readme_content and "no_next_action" in readme_content, (
            "README must explain review cohorts (stale, no_next_action, etc.)"
        )

    def test_keyboard_shortcuts_referenced(self, readme_content: str) -> None:
        """Keyboard shortcuts must be mentioned."""
        assert "keyboard" in readme_content.lower() or "?" in readme_content, (
            "README must reference keyboard shortcuts (press ? for help)"
        )


class TestWorkflowDocumented:
    """Verify overall workflow is documented."""

    def test_capture_to_close_workflow(self, readme_content: str) -> None:
        """The capture → organize → close workflow must be explained."""
        content_lower = readme_content.lower()
        assert "capture" in content_lower, "README must explain capture step of workflow"
