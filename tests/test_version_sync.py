"""Version synchronization tests.

Purpose:
    Ensure release metadata stays consistent between pyproject and runtime exports.

Responsibilities:
    - Verify pyproject.toml project.version matches src/cloop/_version.py.
    - Verify FastAPI app metadata uses the runtime package version.

Non-scope:
    - Automated version bumping workflows.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from cloop._version import __version__
from cloop.main import app

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
VERSION_PATH = REPO_ROOT / "src" / "cloop" / "_version.py"


def _read_pyproject_version() -> str:
    """Return project.version from pyproject.toml."""
    with PYPROJECT_PATH.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def _read_runtime_file_version() -> str:
    """Return __version__ from src/cloop/_version.py via AST parsing."""
    tree = ast.parse(VERSION_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
    raise AssertionError("__version__ assignment not found in src/cloop/_version.py")


def test_pyproject_version_matches_runtime_file() -> None:
    """Version in pyproject.toml must match src/cloop/_version.py."""
    assert _read_pyproject_version() == _read_runtime_file_version()


def test_runtime_version_export_matches_fastapi_version() -> None:
    """FastAPI app.version should be wired to runtime package version."""
    assert app.version == __version__
