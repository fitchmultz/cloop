"""GitHub metadata and contributor-workflow coverage tests.

Purpose:
    Ensure repository-facing GitHub templates/workflows are present and sane.

Responsibilities:
    - Verify issue templates and PR template exist.
    - Verify PR-fast, full/nightly, and release workflows include key safeguards.
    - Prevent accidental regressions in contributor and CI strategy experience.

Non-scope:
    - Validating full GitHub Actions YAML schema semantics.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    """Read a repository-relative text file."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_github_templates_exist() -> None:
    """Required GitHub issue/PR templates and workflows should exist."""
    for rel in [
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/workflows/ci.yml",
        ".github/workflows/ci_full.yml",
        ".github/workflows/release.yml",
    ]:
        assert (REPO_ROOT / rel).exists(), f"Missing required GitHub metadata file: {rel}"


def test_issue_template_config_enforces_structured_issues() -> None:
    """Issue template config should disable blank issues and route security reports."""
    config = _read(".github/ISSUE_TEMPLATE/config.yml")
    assert "blank_issues_enabled: false" in config
    assert "security" in config.lower()


def test_bug_template_captures_repro_context() -> None:
    """Bug report template should collect reproduction and environment details."""
    bug = _read(".github/ISSUE_TEMPLATE/bug_report.yml")
    assert "name: Bug report" in bug
    assert "Reproduction steps" in bug
    assert "Environment" in bug
    assert "make ci" in bug


def test_feature_template_captures_scope_and_quality_expectations() -> None:
    """Feature request template should require scope, docs, and tests considerations."""
    feature = _read(".github/ISSUE_TEMPLATE/feature_request.yml")
    assert "name: Feature request" in feature
    assert "Scope and risks" in feature
    assert "docs" in feature.lower()
    assert "tests" in feature.lower()


def test_pr_template_reinforces_quality_gate() -> None:
    """PR template should require CI, docs, and changelog updates."""
    template = _read(".github/PULL_REQUEST_TEMPLATE.md")
    assert "make ci" in template
    assert "CHANGELOG.md" in template
    assert "Documentation" in template


def test_ci_fast_workflow_is_pr_scoped_and_resource_bounded() -> None:
    """PR CI workflow should be fast, bounded, and avoid full release-grade runs."""
    workflow = _read(".github/workflows/ci.yml")
    assert "pull_request" in workflow
    assert "timeout-minutes" in workflow
    assert "max-parallel" in workflow
    assert "make quality" in workflow
    assert "make test-fast" in workflow
    assert "make ci" not in workflow


def test_ci_full_workflow_covers_main_nightly_and_manual_runs() -> None:
    """Full CI workflow should cover push-to-main, nightly schedule, and manual dispatch."""
    workflow = _read(".github/workflows/ci_full.yml")
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "schedule:" in workflow
    assert "workflow_dispatch" in workflow
    assert "make ci" in workflow
    assert "make test-performance" in workflow
    assert "upload-artifact" in workflow


def test_release_workflow_requires_tag_and_quality_gate() -> None:
    """Release workflow should be tag-triggered and run make ci before publishing artifacts."""
    workflow = _read(".github/workflows/release.yml")
    assert "tags:" in workflow
    assert "v*.*.*" in workflow
    assert "make ci" in workflow
    assert "timeout-minutes" in workflow
    assert "action-gh-release" in workflow
    assert "dist/*" in workflow
