"""Tests for repo runtime cleanup detection helpers.

Purpose:
    Verify runtime-cleanup attribution and orphaned-profile detection for Cloop's
    local verification tooling.

Responsibilities:
    - Confirm repo-owned pi bridge helpers are classified as cleanup targets.
    - Confirm active browser profiles are preserved while orphaned profiles are reported.
    - Confirm cwd lookups stay scoped to candidate processes instead of every process.

Scope:
    - Unit coverage for `scripts.cleanup_runtime` only.

Usage:
    - Run `uv run --locked pytest tests/test_cleanup_runtime.py -q`.

Invariants/Assumptions:
    - Tests never inspect real system processes.
    - Temporary directories stand in for temp browser profiles.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cleanup_runtime.py"
_SPEC = importlib.util.spec_from_file_location("cleanup_runtime", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
cleanup_runtime = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cleanup_runtime
_SPEC.loader.exec_module(cleanup_runtime)


def test_collect_cleanup_snapshot_detects_repo_bridge_and_orphaned_profiles(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    temp_root = tmp_path / "tmp"
    temp_root.mkdir()
    orphaned_profile = temp_root / "playwright_chromiumdev_profile-orphan"
    orphaned_profile.mkdir()
    active_profile = temp_root / "playwright_chromiumdev_profile-active"
    active_profile.mkdir()

    processes = (
        cleanup_runtime.ProcessInfo(
            pid=101, command="node ./src/cloop/pi_bridge/bridge.mjs", cwd=None
        ),
        cleanup_runtime.ProcessInfo(
            pid=202,
            command=(f"agent-browser-darwin-arm64 --user-data-dir {active_profile} --headless"),
            cwd=None,
        ),
        cleanup_runtime.ProcessInfo(pid=303, command="python -m pytest", cwd=None),
    )
    cwd_lookups: list[int] = []

    monkeypatch.setattr(cleanup_runtime, "_run_ps", lambda: processes)
    monkeypatch.setattr(cleanup_runtime.tempfile, "gettempdir", lambda: str(temp_root))

    def _fake_read_cwd(pid: int) -> Path | None:
        cwd_lookups.append(pid)
        if pid == 101:
            return repo_root
        return None

    monkeypatch.setattr(cleanup_runtime, "_read_cwd", _fake_read_cwd)

    snapshot = cleanup_runtime.collect_cleanup_snapshot(repo_root=repo_root)

    assert [process.pid for process in snapshot.repo_processes] == [101]
    assert [process.pid for process in snapshot.ambiguous_automation_processes] == [202]
    assert snapshot.active_profiles == (active_profile.resolve(),)
    assert snapshot.orphaned_profiles == (orphaned_profile.resolve(),)
    assert cwd_lookups == [101, 202]


def test_collect_cleanup_snapshot_skips_cwd_lookup_for_absolute_bridge_path(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "repo"
    bridge_path = repo_root / "src/cloop/pi_bridge/bridge.mjs"
    bridge_path.parent.mkdir(parents=True)
    bridge_path.write_text("", encoding="utf-8")

    processes = (cleanup_runtime.ProcessInfo(pid=404, command=f"node {bridge_path}", cwd=None),)

    monkeypatch.setattr(cleanup_runtime, "_run_ps", lambda: processes)
    monkeypatch.setattr(
        cleanup_runtime, "_read_cwd", lambda pid: (_ for _ in ()).throw(AssertionError(pid))
    )

    snapshot = cleanup_runtime.collect_cleanup_snapshot(repo_root=repo_root)

    assert [process.pid for process in snapshot.repo_processes] == [404]
