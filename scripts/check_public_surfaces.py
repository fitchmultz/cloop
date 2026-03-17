#!/usr/bin/env python3
"""Purpose: Verify the cheapest public runtime surfaces still boot correctly.

Responsibilities:
    - Smoke test that package-root import stays lightweight through the active Python environment.
    - Smoke test FastAPI app import without starting the server.
    - Smoke test the packaged backup CLI help surface through the `cloop` entrypoint.

Scope:
    - Local/public runtime surface verification for import and CLI boot regressions.
    - Clear failure reporting suitable for local development, CI, and release gates.

Usage:
    - Run `uv run python scripts/check_public_surfaces.py` from the repository root.
    - Run `make smoke-public` to execute the same checks through the Makefile gate.

Invariants/Assumptions:
    - The script runs inside the project environment (for example via `uv run`).
    - The package-root smoke must fail if `import cloop` implicitly loads app/runtime-heavy modules.
    - The `cloop` console entrypoint is available on PATH when the project is installed.
    - Successful app smoke prints `FastAPI` so the check can confirm the imported object type.

Exit codes:
    0 - All public surface smoke checks passed.
    1 - One or more smoke checks failed.

Examples:
    uv run python scripts/check_public_surfaces.py
    uv run python scripts/check_public_surfaces.py --verbose
    make smoke-public
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SmokeCheck:
    """Definition of a single subprocess-backed smoke check."""

    name: str
    command: tuple[str, ...]
    expected_stdout_substring: str | None = None


@dataclass(frozen=True)
class SmokeFailure:
    """Structured failure details for a smoke check."""

    check: SmokeCheck
    reason: str
    stdout: str
    stderr: str
    returncode: int


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for smoke verification."""
    parser = argparse.ArgumentParser(
        description="Run cheap smoke checks for Cloop public imports and CLI entrypoints.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 - All public surface smoke checks passed
  1 - One or more smoke checks failed

Examples:
  uv run python scripts/check_public_surfaces.py
  uv run python scripts/check_public_surfaces.py --verbose
  make smoke-public
        """,
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to run commands from (default: script parent)",
    )
    parser.add_argument(
        "--cloop-command",
        default="cloop",
        help="CLI executable used for backup help smoke (default: cloop)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print command output for successful checks too.",
    )
    return parser


def build_smoke_checks(*, cloop_command: str) -> list[SmokeCheck]:
    """Create the ordered set of public runtime smoke checks."""
    return [
        SmokeCheck(
            name="package import boundary",
            command=(
                sys.executable,
                "-c",
                (
                    "import sys; import cloop; "
                    "heavy = sorted(name for name in "
                    "('cloop.main', 'cloop.ai_bridge', 'cloop.rag', 'fastapi') "
                    "if name in sys.modules); "
                    "print('LIGHTWEIGHT' if not heavy else ','.join(heavy)); "
                    "raise SystemExit(0 if not heavy else 1)"
                ),
            ),
            expected_stdout_substring="LIGHTWEIGHT",
        ),
        SmokeCheck(
            name="FastAPI app import",
            command=(
                sys.executable,
                "-c",
                "from cloop.main import app; print(type(app).__name__)",
            ),
            expected_stdout_substring="FastAPI",
        ),
        SmokeCheck(
            name="backup CLI help",
            command=(cloop_command, "backup", "--help"),
            expected_stdout_substring="Manage Cloop data backups",
        ),
    ]


def run_smoke_check(*, check: SmokeCheck, cwd: Path) -> SmokeFailure | None:
    """Execute one smoke check and return a structured failure when it fails."""
    completed = subprocess.run(
        check.command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()

    if completed.returncode != 0:
        return SmokeFailure(
            check=check,
            reason=f"command exited with status {completed.returncode}",
            stdout=stdout,
            stderr=stderr,
            returncode=completed.returncode,
        )

    if (
        check.expected_stdout_substring is not None
        and check.expected_stdout_substring not in completed.stdout
    ):
        return SmokeFailure(
            check=check,
            reason=(f"expected stdout to contain {check.expected_stdout_substring!r}"),
            stdout=stdout,
            stderr=stderr,
            returncode=completed.returncode,
        )

    return None


def format_command(command: tuple[str, ...]) -> str:
    """Render a subprocess command for human-readable logs."""
    return shlex.join(command)


def print_stream(label: str, content: str) -> None:
    """Print a labeled subprocess stream when content exists."""
    if content:
        print(f"    {label}: {content}")


def main() -> int:
    """Run all configured public surface smoke checks."""
    parser = build_parser()
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    checks = build_smoke_checks(cloop_command=args.cloop_command)

    failures: list[SmokeFailure] = []
    for check in checks:
        print(f"RUN: {check.name} :: {format_command(check.command)}")
        failure = run_smoke_check(check=check, cwd=repo_root)
        if failure is None:
            print(f"OK: {check.name}")
            if args.verbose:
                completed = subprocess.run(
                    check.command,
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                print_stream("stdout", completed.stdout.strip())
                print_stream("stderr", completed.stderr.strip())
            continue

        failures.append(failure)
        print(f"FAIL: {check.name} ({failure.reason})", file=sys.stderr)
        print(f"  command: {format_command(check.command)}", file=sys.stderr)
        print_stream("stdout", failure.stdout)
        print_stream("stderr", failure.stderr)

    if failures:
        print(
            f"ERROR: public surface smoke checks failed ({len(failures)}/{len(checks)})",
            file=sys.stderr,
        )
        return 1

    print(f"OK: public surface smoke checks passed ({len(checks)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
