"""Public documentation coverage tests.

Purpose:
    Verify README.md and the linked reference guide document key capabilities
    without forcing the README to become the exhaustive command manual.

Responsibilities:
    - Assert CLI commands are discoverable in public docs
    - Assert web UI features are discoverable in public docs
    - Assert local validation and maintenance docs are represented accurately

Non-scope:
    - Testing actual feature functionality (see other test files)
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
README_PATH = REPO_ROOT / "README.md"
REFERENCE_PATH = REPO_ROOT / "docs" / "reference.md"


@pytest.fixture
def readme_content() -> str:
    """Load README.md content."""
    return README_PATH.read_text(encoding="utf-8")


@pytest.fixture
def public_docs_content(readme_content: str) -> str:
    """Load the README plus the linked detailed public reference."""
    return f"{readme_content}\n\n{REFERENCE_PATH.read_text(encoding='utf-8')}"


class TestCLICommandsDocumented:
    """Verify CLI commands have public documentation."""

    def test_loop_review_command_documented(self, public_docs_content: str) -> None:
        """'cloop loop review' must be documented in public docs."""
        assert "loop review" in public_docs_content, (
            "public docs must document 'cloop loop review' command"
        )

    def test_loop_review_flags_documented(self, public_docs_content: str) -> None:
        """Review command flags must be documented."""
        assert "--daily" in public_docs_content or "--weekly" in public_docs_content, (
            "public docs must document loop review flags (--daily, --weekly, --all)"
        )

    def test_ask_command_documents_answer_payload(self, readme_content: str) -> None:
        """README should describe the answer-oriented CLI ask payload."""
        assert "`cloop ask` returns JSON with `answer`" in readme_content
        assert "`sources`" in readme_content

    def test_next_limit_documents_total_bucket_cap(self, public_docs_content: str) -> None:
        """Public docs should clarify that next limit is total, not per bucket."""
        assert "`--limit` is a total cap across all buckets" in public_docs_content


class TestWebUIDocumented:
    """Verify web UI features have public documentation."""

    def test_life_feed_workflow_documented(self, public_docs_content: str) -> None:
        """Life feed workflow must be explained."""
        assert "life feed" in public_docs_content.lower(), (
            "public docs must explain Life feed workflow"
        )
        assert "organizer model returns a structured Life plan" in public_docs_content

    def test_tabs_overview_documented(self, public_docs_content: str) -> None:
        """Web UI tabs must be listed."""
        assert "Inbox" in public_docs_content and "Next" in public_docs_content, (
            "public docs must list web UI tabs (Inbox, Next, etc.)"
        )

    def test_review_cohorts_documented(self, public_docs_content: str) -> None:
        """Review cohorts must be explained."""
        assert "stale" in public_docs_content and "no_next_action" in public_docs_content, (
            "public docs must explain review cohorts (stale, no_next_action, etc.)"
        )

    def test_keyboard_shortcuts_referenced(self, public_docs_content: str) -> None:
        """Keyboard shortcuts must be mentioned."""
        assert "keyboard" in public_docs_content.lower() or "?" in public_docs_content, (
            "public docs must reference keyboard shortcuts (press ? for help)"
        )


class TestRepoMetadataDocumented:
    """Verify repository maintenance artifacts are referenced accurately."""

    def test_project_maintenance_docs_linked(self, readme_content: str) -> None:
        """README should link core repository policy and process docs."""
        for expected in [
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
            "docs/architecture.md",
            "docs/reference.md",
            "docs/verification_checklist.md",
            "docs/release.md",
            "LICENSE",
        ]:
            assert expected in readme_content

    def test_public_badges_match_current_local_first_positioning(self, readme_content: str) -> None:
        """README should expose current badges without implying hosted CI is active."""
        assert "actions/workflows/ci.yml/badge.svg" not in readme_content
        assert "License-MIT" in readme_content
        assert "python-3.14%2B" in readme_content

    def test_python_prerequisite_mentions_314_plus(self, readme_content: str) -> None:
        """README prerequisites should match supported Python policy."""
        assert "Python 3.14+" in readme_content

    def test_api_docs_and_health_endpoints_referenced(self, public_docs_content: str) -> None:
        """Public docs should expose API docs and machine-readable schema endpoints."""
        for expected in ["/docs", "/redoc", "/openapi.json", "/health"]:
            assert expected in public_docs_content

    def test_loops_endpoint_default_behavior_documented(self, public_docs_content: str) -> None:
        """Public docs should document the real default filter for GET /loops."""
        assert "GET /loops`: list loops (default `status=open`)" in public_docs_content

    def test_release_links_section_present(self, readme_content: str) -> None:
        """README should link release/tag pages for repo discoverability."""
        assert "Releases" in readme_content
        assert "Tags" in readme_content

    def test_local_validation_strategy_summary_present(self, readme_content: str) -> None:
        """README should document local validation rather than inactive hosted CI."""
        lower = readme_content.lower()
        assert "local validation" in lower
        assert "make check-fast" in readme_content
        assert "make ci" in readme_content
        assert "actions/workflows" not in readme_content


class TestWorkflowDocumented:
    """Verify overall workflow is documented."""

    def test_capture_to_close_workflow(self, readme_content: str) -> None:
        """The capture → organize → close workflow must be explained."""
        content_lower = readme_content.lower()
        assert "capture" in content_lower, "README must explain capture step of workflow"
        assert "close" in content_lower, "README must explain close/release outcome"
