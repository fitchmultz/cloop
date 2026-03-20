"""Regression coverage for pi selector defaults and operator-facing docs.

Purpose:
    Keep code defaults, `.env.example`, and key setup docs aligned on the
    project-preferred explicit pi selectors.

Responsibilities:
    - Assert settings defaults stay aligned with the preferred pi selector order
    - Assert `.env.example` mirrors those defaults
    - Assert README and verification docs document the same selector guidance

Non-scope:
    - Exhaustively validating all documentation prose
    - Testing pi availability or upstream provider behavior
"""

from pathlib import Path

from cloop.settings import DEFAULT_PI_MODEL_PREFERENCES, DEFAULT_PI_ORGANIZER_MODEL_PREFERENCES

REPO_ROOT = Path(__file__).resolve().parent.parent
README_PATH = REPO_ROOT / "README.md"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
VERIFICATION_DOC_PATH = REPO_ROOT / "docs" / "verification_checklist.md"

DEFAULT_PI_MODEL_CHAIN = ",".join(DEFAULT_PI_MODEL_PREFERENCES)
DEFAULT_PI_ORGANIZER_MODEL_CHAIN = ",".join(DEFAULT_PI_ORGANIZER_MODEL_PREFERENCES)


def test_env_example_pi_selectors_match_settings_defaults() -> None:
    env_example = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    assert f"CLOOP_PI_MODEL={DEFAULT_PI_MODEL_CHAIN}" in env_example
    assert f"CLOOP_PI_ORGANIZER_MODEL={DEFAULT_PI_ORGANIZER_MODEL_CHAIN}" in env_example
    assert "CLOOP_PI_SELECTOR_MODE=fallback" in env_example


def test_readme_documents_current_pi_selector_defaults() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    assert f"CLOOP_PI_MODEL={DEFAULT_PI_MODEL_CHAIN}" in readme
    assert f"CLOOP_PI_ORGANIZER_MODEL={DEFAULT_PI_ORGANIZER_MODEL_CHAIN}" in readme
    assert "CLOOP_PI_SELECTOR_MODE=fallback" in readme
    assert "pi --list-models" in readme
    assert "first selector that `pi --list-models` reports as available" in readme


def test_verification_checklist_documents_current_pi_selector_defaults() -> None:
    checklist = VERIFICATION_DOC_PATH.read_text(encoding="utf-8")

    assert f"CLOOP_PI_MODEL={DEFAULT_PI_MODEL_CHAIN}" in checklist
    assert f"CLOOP_PI_ORGANIZER_MODEL={DEFAULT_PI_ORGANIZER_MODEL_CHAIN}" in checklist
    assert "CLOOP_PI_SELECTOR_MODE=fallback" in checklist
    assert "pi --list-models" in checklist
