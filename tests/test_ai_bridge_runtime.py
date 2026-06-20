"""Tests for the Python-side pi bridge runtime."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from cloop.ai_bridge.errors import BridgeProtocolError, BridgeStartupError, BridgeUpstreamError
from cloop.ai_bridge.protocol import BridgeStartRequest
from cloop.ai_bridge.runtime import BridgeRuntime


def _write_bridge_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake_bridge.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


def _start_request() -> BridgeStartRequest:
    return BridgeStartRequest(
        request_id="req-1",
        model="zai/glm-5.2",
        messages=[{"role": "user", "content": "hello"}],
        thinking_level="none",
        timeout_ms=1_000,
        max_tool_rounds=1,
        tools=[],
    )


def _assert_runtime_stopped(runtime: BridgeRuntime) -> None:
    process = runtime._process
    assert process is None or process.poll() is not None


def test_bridge_runtime_ping_round_trip(tmp_path: Path) -> None:
    script = _write_bridge_script(
        tmp_path,
        """
        import json
        import sys

        print(
            json.dumps({"protocol": 1, "type": "hello", "bridge": "fake", "version": "1"}),
            flush=True,
        )
        for line in sys.stdin:
            message = json.loads(line)
            if message["type"] == "ping":
                print(
                    json.dumps(
                        {
                            "protocol": 1,
                            "type": "pong",
                            "request_id": message["request_id"],
                            "latency_ms": 2.5,
                        }
                    ),
                    flush=True,
                )
        """,
    )
    runtime = BridgeRuntime(command=[sys.executable, "-u", str(script)], agent_dir=None)
    try:
        payload = runtime.ping()
    finally:
        runtime.shutdown()

    assert payload["bridge"]["bridge"] == "fake"
    assert payload["latency_ms"] == 2.5


def test_bridge_runtime_resolves_model_metadata(tmp_path: Path) -> None:
    script = _write_bridge_script(
        tmp_path,
        """
        import json
        import sys

        print(
            json.dumps({"protocol": 1, "type": "hello", "bridge": "fake", "version": "1"}),
            flush=True,
        )
        for line in sys.stdin:
            message = json.loads(line)
            if message["type"] == "resolve_model":
                print(
                    json.dumps(
                        {
                            "protocol": 1,
                            "type": "model_resolved",
                            "request_id": message["request_id"],
                            "requested_selector": message["selectors"][0],
                            "requested_selectors": message["selectors"],
                            "resolved_selector": message["selectors"][1],
                            "fallback_used": True,
                            "selector_mode": message["selector_mode"],
                        }
                    ),
                    flush=True,
                )
        """,
    )
    runtime = BridgeRuntime(command=[sys.executable, "-u", str(script)], agent_dir=None)
    try:
        resolution = runtime.resolve_model(
            selectors=("zai/glm-5.2", "kimi-coding/kimi-for-coding"),
            selector_mode="fallback",
        )
    finally:
        runtime.shutdown()

    assert resolution.requested_selector == "zai/glm-5.2"
    assert resolution.requested_selectors == ("zai/glm-5.2", "kimi-coding/kimi-for-coding")
    assert resolution.resolved_selector == "kimi-coding/kimi-for-coding"
    assert resolution.fallback_used is True
    assert resolution.selector_mode == "fallback"


def test_bridge_runtime_rejects_malformed_handshake(tmp_path: Path) -> None:
    script = _write_bridge_script(
        tmp_path,
        """
        import sys

        sys.stdout.write("not-json\\n")
        sys.stdout.flush()
        """,
    )
    runtime = BridgeRuntime(command=[sys.executable, "-u", str(script)], agent_dir=None)
    with pytest.raises(BridgeProtocolError, match="Malformed bridge JSONL"):
        runtime.ensure_started()

    _assert_runtime_stopped(runtime)


def test_bridge_runtime_times_out_when_handshake_never_arrives(tmp_path: Path) -> None:
    script = _write_bridge_script(
        tmp_path,
        """
        import time

        time.sleep(1.0)
        """,
    )
    runtime = BridgeRuntime(
        command=[sys.executable, "-u", str(script)],
        agent_dir=None,
        startup_timeout_s=0.1,
    )
    with pytest.raises(BridgeStartupError, match="Timed out waiting for pi bridge handshake"):
        runtime.ensure_started()

    _assert_runtime_stopped(runtime)


def test_bridge_session_surfaces_upstream_error_events(tmp_path: Path) -> None:
    script = _write_bridge_script(
        tmp_path,
        """
        import json
        import sys

        print(
            json.dumps({"protocol": 1, "type": "hello", "bridge": "fake", "version": "1"}),
            flush=True,
        )
        for line in sys.stdin:
            message = json.loads(line)
            if message["type"] == "start":
                print(
                    json.dumps(
                        {
                            "protocol": 1,
                            "type": "error",
                            "request_id": message["request_id"],
                            "code": "upstream_failed",
                            "message": "model boom",
                            "retryable": False,
                            "provider": "fake",
                        }
                    ),
                    flush=True,
                )
        """,
    )
    runtime = BridgeRuntime(command=[sys.executable, "-u", str(script)], agent_dir=None)
    session = runtime.open_session(_start_request())
    try:
        with pytest.raises(BridgeUpstreamError, match="model boom") as exc_info:
            list(session.events())
    finally:
        runtime.shutdown()

    assert exc_info.value.details == {"provider": "fake"}


def test_bridge_session_reports_invalid_event_payloads(tmp_path: Path) -> None:
    script = _write_bridge_script(
        tmp_path,
        """
        import json
        import sys

        print(
            json.dumps({"protocol": 1, "type": "hello", "bridge": "fake", "version": "1"}),
            flush=True,
        )
        for line in sys.stdin:
            message = json.loads(line)
            if message["type"] == "start":
                sys.stdout.write("not-json\\n")
                sys.stdout.flush()
        """,
    )
    runtime = BridgeRuntime(command=[sys.executable, "-u", str(script)], agent_dir=None)
    session = runtime.open_session(_start_request())
    try:
        with pytest.raises(BridgeUpstreamError, match="Invalid pi bridge payload"):
            list(session.events())
    finally:
        runtime.shutdown()


def test_bridge_runtime_reports_missing_executable() -> None:
    runtime = BridgeRuntime(command=["/definitely-missing-node-binary"], agent_dir=None)
    with pytest.raises(BridgeStartupError, match="Failed to start pi bridge command"):
        runtime.ensure_started()
