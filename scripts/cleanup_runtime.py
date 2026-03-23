#!/usr/bin/env python3
"""Purpose: Detect and clean repo-owned runtime processes and orphaned automation profiles.

Responsibilities:
    - Report long-lived repo runtime processes that should not outlive an agent session.
    - Terminate repo-owned dev servers and other clearly attributable runtime helpers on request.
    - Remove orphaned Playwright and agent-browser temp profiles that are no longer in use.

Scope:
    - Local developer and agent cleanup hygiene for this repository only.
    - Conservative cleanup that avoids killing ambiguous user-owned applications.

Usage:
    - Run `uv run python scripts/cleanup_runtime.py --check`
      to inspect repo-owned runtime state.
    - Run `uv run python scripts/cleanup_runtime.py --clean`
      to stop repo-owned runtime processes and remove orphaned temp browser profiles.
    - Use `make verify-runtime-clean` or `make cleanup-runtime`
      for the same actions.

Invariants/Assumptions:
    - Repo-owned Vite processes are identified by a cwd under this repository.
    - Repo-owned Python servers are identified by explicit Cloop command lines.
    - Repo-owned pi bridge helpers are identified by the canonical bridge script path.
    - Generic browser automation processes without repo attribution are
      reported as ambiguous and are never killed automatically.
    - Orphaned temp profiles are safe to remove when no live process references them.

Exit codes:
    0 - No repo-owned runtime leaks remain.
    1 - One or more repo-owned runtime leaks remain.

Examples:
    uv run python scripts/cleanup_runtime.py --check
    uv run python scripts/cleanup_runtime.py --clean
    make verify-runtime-clean
    make cleanup-runtime
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_PROFILE_PATTERNS = ("agent-browser-chrome-*", "playwright_chromiumdev_profile-*")
_PROFILE_PATH_RE = re.compile(
    r"(/\S*(?:agent-browser-chrome-[^\s/]+|playwright_chromiumdev_profile-[^\s/]+))"
)
_AUTOMATION_MARKERS = (
    "agent-browser-darwin-arm64",
    "agent-browser-chrome-",
    "playwright_chromiumdev_profile-",
    "peekaboo",
    "xctest",
)
_BRIDGE_PATH_FRAGMENT = "src/cloop/pi_bridge/bridge.mjs"


@dataclass(frozen=True)
class ProcessInfo:
    """Single process snapshot from `ps`."""

    pid: int
    command: str
    cwd: Path | None


@dataclass(frozen=True)
class CleanupSnapshot:
    """Collected runtime resources relevant to cleanup hygiene."""

    repo_processes: tuple[ProcessInfo, ...]
    ambiguous_automation_processes: tuple[ProcessInfo, ...]
    orphaned_profiles: tuple[Path, ...]
    active_profiles: tuple[Path, ...]


@dataclass(frozen=True)
class CleanupResult:
    """Outcome summary for cleanup execution."""

    killed_pids: tuple[int, ...]
    removed_profiles: tuple[Path, ...]
    remaining_repo_processes: tuple[ProcessInfo, ...]
    ambiguous_automation_processes: tuple[ProcessInfo, ...]
    remaining_orphaned_profiles: tuple[Path, ...]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or clean repo-owned runtime processes and orphaned automation profiles."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit Codes:
  0 - No repo-owned runtime leaks remain
  1 - Repo-owned runtime leaks still require attention

Examples:
  uv run python scripts/cleanup_runtime.py --check
  uv run python scripts/cleanup_runtime.py --clean
  make verify-runtime-clean
  make cleanup-runtime
        """,
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root used to attribute repo-owned processes.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="Report current cleanup state (default)."
    )
    mode.add_argument(
        "--clean",
        action="store_true",
        help="Kill repo-owned processes and remove orphaned temp profiles.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed command lines and profile paths.",
    )
    return parser


def _run_ps() -> tuple[ProcessInfo, ...]:
    completed = subprocess.run(
        ["ps", "-axo", "pid=,command="],
        check=True,
        capture_output=True,
        text=True,
    )
    processes: list[ProcessInfo] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        pid_text, _, command = line.partition(" ")
        if not pid_text.isdigit() or not command:
            continue
        processes.append(ProcessInfo(pid=int(pid_text), command=command.strip(), cwd=None))
    return tuple(processes)


def _read_cwd(pid: int) -> Path | None:
    completed = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        if line.startswith("n"):
            return Path(line[1:]).resolve()
    return None


def _is_repo_path(path: Path | None, *, repo_root: Path) -> bool:
    if path is None:
        return False
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return True


def _command_mentions_repo_path(command: str, *, repo_root: Path, suffix: str) -> bool:
    return str((repo_root / suffix).resolve()) in command


def _is_pnpm_dev_process(command: str) -> bool:
    return " pnpm " in f" {command} " and any(
        marker in command for marker in (" dev", " vite", " preview", "vitest --watch")
    )


def _needs_cwd_lookup(process: ProcessInfo, *, repo_root: Path) -> bool:
    command = process.command
    if any(marker in command for marker in _AUTOMATION_MARKERS):
        return True
    if "vite/bin/vite.js" in command or _is_pnpm_dev_process(command):
        return True
    if _BRIDGE_PATH_FRAGMENT in command and not _command_mentions_repo_path(
        command, repo_root=repo_root, suffix=_BRIDGE_PATH_FRAGMENT
    ):
        return True
    return False


def _attach_candidate_cwds(
    processes: Iterable[ProcessInfo], *, repo_root: Path
) -> tuple[ProcessInfo, ...]:
    enriched: list[ProcessInfo] = []
    for process in processes:
        cwd = process.cwd
        if cwd is None and _needs_cwd_lookup(process, repo_root=repo_root):
            cwd = _read_cwd(process.pid)
        enriched.append(ProcessInfo(pid=process.pid, command=process.command, cwd=cwd))
    return tuple(enriched)


def _is_repo_process(process: ProcessInfo, *, repo_root: Path) -> bool:
    command = process.command
    if "uvicorn cloop.main:app" in command or "cloop.main:app" in command:
        return True
    if "cloop-scheduler" in command or "cloop.scheduler" in command:
        return True
    if _BRIDGE_PATH_FRAGMENT in command:
        return _command_mentions_repo_path(
            command, repo_root=repo_root, suffix=_BRIDGE_PATH_FRAGMENT
        ) or _is_repo_path(process.cwd, repo_root=repo_root)
    if "vite/bin/vite.js" in command or _is_pnpm_dev_process(command):
        return _is_repo_path(process.cwd, repo_root=repo_root)
    return False


def _is_automation_process(process: ProcessInfo) -> bool:
    command = process.command
    if process.pid == os.getpid() or "cleanup_runtime.py" in command:
        return False
    if command.startswith("rg ") or " rg " in f" {command} ":
        return False
    return any(marker in command for marker in _AUTOMATION_MARKERS)


def _active_profile_paths(processes: Iterable[ProcessInfo]) -> tuple[Path, ...]:
    profile_paths: set[Path] = set()
    for process in processes:
        if not _is_automation_process(process):
            continue
        for match in _PROFILE_PATH_RE.finditer(process.command):
            profile_paths.add(Path(match.group(1)).resolve())
    return tuple(sorted(profile_paths))


def collect_cleanup_snapshot(*, repo_root: Path) -> CleanupSnapshot:
    """Collect repo-owned processes plus orphaned temp profile directories."""
    processes = _attach_candidate_cwds(_run_ps(), repo_root=repo_root)
    repo_processes: list[ProcessInfo] = []
    ambiguous_automation_processes: list[ProcessInfo] = []
    for process in processes:
        repo_owned = _is_repo_process(process, repo_root=repo_root)
        if repo_owned:
            repo_processes.append(process)
            continue
        if _is_automation_process(process):
            ambiguous_automation_processes.append(process)
    active_profiles = _active_profile_paths(processes)
    tmp_root = Path(tempfile.gettempdir()).resolve()
    discovered_profiles: set[Path] = set()
    for pattern in _PROFILE_PATTERNS:
        discovered_profiles.update(path.resolve() for path in tmp_root.glob(pattern))
    orphaned_profiles = tuple(
        sorted(path for path in discovered_profiles if path not in active_profiles)
    )
    return CleanupSnapshot(
        repo_processes=tuple(repo_processes),
        ambiguous_automation_processes=tuple(ambiguous_automation_processes),
        orphaned_profiles=orphaned_profiles,
        active_profiles=active_profiles,
    )


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_processes(processes: Iterable[ProcessInfo]) -> tuple[int, ...]:
    target_pids = tuple(sorted({process.pid for process in processes}))
    for pid in target_pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not any(_pid_exists(pid) for pid in target_pids):
            return target_pids
        time.sleep(0.1)
    for pid in target_pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
    return target_pids


def remove_orphaned_profiles(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Remove orphaned temp browser profiles."""
    removed: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        shutil.rmtree(path, ignore_errors=False)
        removed.append(path)
    return tuple(removed)


def run_cleanup(*, repo_root: Path) -> CleanupResult:
    """Kill repo-owned processes, remove orphaned profiles, and rescan."""
    snapshot = collect_cleanup_snapshot(repo_root=repo_root)
    killed_pids = _terminate_processes(snapshot.repo_processes)
    removed_profiles = remove_orphaned_profiles(snapshot.orphaned_profiles)
    remaining = collect_cleanup_snapshot(repo_root=repo_root)
    return CleanupResult(
        killed_pids=killed_pids,
        removed_profiles=removed_profiles,
        remaining_repo_processes=remaining.repo_processes,
        ambiguous_automation_processes=remaining.ambiguous_automation_processes,
        remaining_orphaned_profiles=remaining.orphaned_profiles,
    )


def _print_processes(label: str, processes: Iterable[ProcessInfo], *, verbose: bool) -> None:
    processes = tuple(processes)
    print(f"{label}: {len(processes)}")
    if not verbose:
        return
    for process in processes:
        cwd = str(process.cwd) if process.cwd is not None else "<unknown cwd>"
        print(f"  - pid={process.pid} cwd={cwd} cmd={process.command}")


def _print_paths(label: str, paths: Iterable[Path], *, verbose: bool) -> None:
    paths = tuple(paths)
    print(f"{label}: {len(paths)}")
    if not verbose:
        return
    for path in paths:
        print(f"  - {path}")


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()

    if args.clean:
        result = run_cleanup(repo_root=repo_root)
        print(f"killed_repo_processes: {len(result.killed_pids)}")
        if args.verbose and result.killed_pids:
            for pid in result.killed_pids:
                print(f"  - pid={pid}")
        _print_paths("removed_orphaned_profiles", result.removed_profiles, verbose=args.verbose)
        _print_processes(
            "remaining_repo_processes",
            result.remaining_repo_processes,
            verbose=args.verbose,
        )
        _print_processes(
            "ambiguous_automation_processes",
            result.ambiguous_automation_processes,
            verbose=args.verbose,
        )
        _print_paths(
            "remaining_orphaned_profiles",
            result.remaining_orphaned_profiles,
            verbose=args.verbose,
        )
        return 0 if not result.remaining_repo_processes else 1

    snapshot = collect_cleanup_snapshot(repo_root=repo_root)
    _print_processes("repo_processes", snapshot.repo_processes, verbose=args.verbose)
    _print_processes(
        "ambiguous_automation_processes",
        snapshot.ambiguous_automation_processes,
        verbose=args.verbose,
    )
    _print_paths("active_temp_profiles", snapshot.active_profiles, verbose=args.verbose)
    _print_paths("orphaned_temp_profiles", snapshot.orphaned_profiles, verbose=args.verbose)
    return 0 if not snapshot.repo_processes else 1


if __name__ == "__main__":
    raise SystemExit(main())
