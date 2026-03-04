#!/usr/bin/env python3
"""Purpose: Ensure runtime package version matches pyproject metadata.

Responsibilities:
    - Read project.version from pyproject.toml.
    - Read __version__ from src/cloop/_version.py.
    - Fail fast on mismatches to prevent release drift.

Non-scope:
    - Bumping versions automatically.
    - Enforcing changelog/tag semantics.

Exit codes:
    0 - Version values are in sync.
    1 - Version mismatch or runtime parsing error.

Examples:
    uv run python scripts/check_version_sync.py
    make version-check
"""

from __future__ import annotations

import argparse
import ast
import sys
import tomllib
from pathlib import Path


def read_pyproject_version(pyproject_path: Path) -> str:
    """Read [project].version from pyproject.toml."""
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("[project].version missing or invalid in pyproject.toml")
    return version.strip()


def read_runtime_version(version_path: Path) -> str:
    """Read __version__ assignment from src/cloop/_version.py via AST."""
    module = ast.parse(version_path.read_text(encoding="utf-8"), filename=str(version_path))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value.strip()
                raise ValueError("__version__ in _version.py must be a string literal")
    raise ValueError("__version__ assignment not found in src/cloop/_version.py")


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for version sync checks."""
    parser = argparse.ArgumentParser(
        description="Validate pyproject.toml version matches src/cloop/_version.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 - Versions are in sync
  1 - Mismatch or parsing error

Examples:
  uv run python scripts/check_version_sync.py
  make version-check
        """,
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root path (default: script parent)",
    )
    return parser


def main() -> int:
    """Validate version consistency between project metadata and runtime module."""
    parser = build_parser()
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    pyproject_path = repo_root / "pyproject.toml"
    version_path = repo_root / "src" / "cloop" / "_version.py"

    try:
        pyproject_version = read_pyproject_version(pyproject_path)
        runtime_version = read_runtime_version(version_path)
    except (OSError, tomllib.TOMLDecodeError, SyntaxError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if pyproject_version != runtime_version:
        print(
            "ERROR: version mismatch: "
            f"pyproject.toml={pyproject_version!r} "
            f"src/cloop/_version.py={runtime_version!r}",
            file=sys.stderr,
        )
        return 1

    print(f"OK: version sync verified ({pyproject_version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
