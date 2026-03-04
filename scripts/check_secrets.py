#!/usr/bin/env python3
"""Purpose: Prevent accidental secret leaks in tracked repository files.
Responsibilities:
  - Enumerate git-tracked files from the repository root.
  - Scan text files for high-risk secret patterns.
  - Report findings with file/line context and fail non-zero.
  - Optionally emit machine-readable JSON for automation.
Non-scope: Full DLP coverage, entropy-based detection, or history rewriting.

Exit Codes:
  0 - No potential secrets found.
  1 - Potential secrets found or runtime failure.
  2 - Invalid CLI usage.

Examples:
  # Run from repository root
  uv run python scripts/check_secrets.py

  # Emit JSON output for automation
  uv run python scripts/check_secrets.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True, slots=True)
class SecretRule:
    """Pattern-based secret detection rule."""

    rule_id: str
    description: str
    pattern: re.Pattern[str]


@dataclass(frozen=True, slots=True)
class SecretFinding:
    """A potential secret match within a tracked file."""

    path: str
    line_number: int
    rule_id: str
    description: str
    line_excerpt: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "path": self.path,
            "line_number": self.line_number,
            "rule_id": self.rule_id,
            "description": self.description,
            "line_excerpt": self.line_excerpt,
        }


SECRET_RULES: Final[tuple[SecretRule, ...]] = (
    SecretRule(
        rule_id="google_api_key",
        description="Google API key",
        pattern=re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    ),
    SecretRule(
        rule_id="openai_like_key",
        description="OpenAI-style API key",
        pattern=re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    ),
    SecretRule(
        rule_id="private_key_block",
        description="Private key PEM block",
        pattern=re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
)


def list_tracked_files(repo_root: Path) -> list[Path]:
    """Return absolute paths for all git-tracked files."""
    process = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.returncode != 0:
        stderr = process.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git ls-files failed: {stderr or 'unknown error'}")

    entries = [part for part in process.stdout.split(b"\x00") if part]
    return [repo_root / entry.decode("utf-8", errors="replace") for entry in entries]


def is_probably_text_file(path: Path) -> bool:
    """Heuristically skip binary files by checking for null bytes."""
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\x00" not in sample


def normalize_excerpt(line: str, max_len: int = 140) -> str:
    """Trim and bound line excerpt length for readable output."""
    compact = line.strip()
    if len(compact) <= max_len:
        return compact
    return f"{compact[: max_len - 3]}..."


def scan_text_for_secrets(text: str, relative_path: str) -> list[SecretFinding]:
    """Scan text content and return potential secret findings."""
    findings: list[SecretFinding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for rule in SECRET_RULES:
            if rule.pattern.search(line):
                findings.append(
                    SecretFinding(
                        path=relative_path,
                        line_number=line_number,
                        rule_id=rule.rule_id,
                        description=rule.description,
                        line_excerpt=normalize_excerpt(line),
                    )
                )
    return findings


def scan_file_for_secrets(path: Path, repo_root: Path) -> list[SecretFinding]:
    """Scan one file for secret patterns, skipping non-text files."""
    if not is_probably_text_file(path):
        return []

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    relative_path = path.relative_to(repo_root).as_posix()
    return scan_text_for_secrets(content, relative_path)


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Scan git-tracked files for likely secrets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 - No potential secrets found
  1 - Potential secrets found or runtime failure
  2 - Invalid CLI usage

Examples:
  uv run python scripts/check_secrets.py
  uv run python scripts/check_secrets.py --json
        """,
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to scan (default: current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output to stdout",
    )
    return parser


def main() -> int:
    """Run tracked-file secret scanning checks."""
    parser = build_arg_parser()
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    findings: list[SecretFinding] = []

    try:
        tracked_files = list_tracked_files(repo_root)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for file_path in tracked_files:
        findings.extend(scan_file_for_secrets(file_path, repo_root))

    if args.json:
        payload = {
            "ok": not findings,
            "finding_count": len(findings),
            "findings": [finding.to_dict() for finding in findings],
        }
        print(json.dumps(payload, indent=2))
        return 1 if findings else 0

    if findings:
        print(
            f"Found {len(findings)} potential secret(s) in tracked files:",
            file=sys.stderr,
        )
        for finding in findings:
            print(
                f"  {finding.path}:{finding.line_number} "
                f"[{finding.rule_id}] {finding.line_excerpt}",
                file=sys.stderr,
            )
        return 1

    print("OK: no potential secrets found in tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
