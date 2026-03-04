#!/usr/bin/env python3
"""Purpose: Ensure CHANGELOG.md stays aligned with the project version metadata.

Responsibilities:
    - Read [project].version from pyproject.toml.
    - Verify CHANGELOG.md contains a release heading for that version.
    - Verify CHANGELOG.md keeps an [Unreleased] section for forward changes.

Non-scope:
    - Auto-updating changelog content or release dates.
    - Validating Keep a Changelog formatting beyond required headings.

Exit codes:
    0 - Changelog and project version are aligned.
    1 - Missing files, parse errors, or heading mismatches.

Examples:
    uv run python scripts/check_changelog_sync.py
    make changelog-check
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

RELEASE_HEADING_PATTERN = re.compile(
    r"^## \[(?P<version>\d+\.\d+\.\d+)\] - (?P<date>\d{4}-\d{2}-\d{2})$"
)
UNRELEASED_HEADING = "## [Unreleased]"


def read_project_version(pyproject_path: Path) -> str:
    """Read [project].version from pyproject.toml."""
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)

    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("[project].version missing or invalid in pyproject.toml")
    return version.strip()


def changelog_release_versions(changelog_text: str) -> dict[str, str]:
    """Return mapping of release version -> date from changelog headings."""
    releases: dict[str, str] = {}
    for line in changelog_text.splitlines():
        match = RELEASE_HEADING_PATTERN.match(line.strip())
        if match:
            releases[match.group("version")] = match.group("date")
    return releases


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for changelog sync checks."""
    parser = argparse.ArgumentParser(
        description="Validate pyproject version is present in CHANGELOG.md",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 - Changelog is aligned with pyproject version
  1 - Missing files, parse errors, or mismatches

Examples:
  uv run python scripts/check_changelog_sync.py
  make changelog-check
        """,
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root path (default: script parent)",
    )
    return parser


def main() -> int:
    """Validate changelog version coverage and required headings."""
    parser = build_parser()
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    pyproject_path = repo_root / "pyproject.toml"
    changelog_path = repo_root / "CHANGELOG.md"

    if not pyproject_path.exists():
        print(f"ERROR: {pyproject_path} not found", file=sys.stderr)
        return 1
    if not changelog_path.exists():
        print(f"ERROR: {changelog_path} not found", file=sys.stderr)
        return 1

    try:
        version = read_project_version(pyproject_path)
        changelog_text = changelog_path.read_text(encoding="utf-8")
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    releases = changelog_release_versions(changelog_text)
    if version not in releases:
        print(
            "ERROR: CHANGELOG.md missing release heading for project version "
            f"{version!r} (expected: '## [{version}] - YYYY-MM-DD')",
            file=sys.stderr,
        )
        return 1

    if UNRELEASED_HEADING not in changelog_text:
        print("ERROR: CHANGELOG.md missing required '## [Unreleased]' section", file=sys.stderr)
        return 1

    print(
        "OK: changelog sync verified "
        f"(version={version}, release-date={releases[version]}, unreleased-section=present)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
