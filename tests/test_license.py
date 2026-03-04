"""License file presence and format checks.

Purpose:
    Ensure the repository includes explicit open-source licensing metadata.

Responsibilities:
    - Assert LICENSE exists in repo root.
    - Assert LICENSE advertises MIT licensing.

Non-scope:
    - Legal validation of license suitability.
"""

from pathlib import Path

LICENSE_PATH = Path(__file__).resolve().parents[1] / "LICENSE"


def test_license_file_exists() -> None:
    """LICENSE file should exist at repository root."""
    assert LICENSE_PATH.exists(), "Missing LICENSE file"


def test_license_file_declares_mit() -> None:
    """LICENSE should identify MIT license text."""
    content = LICENSE_PATH.read_text(encoding="utf-8")
    assert "MIT License" in content
