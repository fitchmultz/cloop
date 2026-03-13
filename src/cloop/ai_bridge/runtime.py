"""Threaded subprocess runtime for the pi bridge.

Purpose:
    Manage one long-lived Node subprocess that serves generative requests over a
    strict JSONL protocol.

Responsibilities:
    - Start, handshake, and shut down the bridge process
    - Multiplex request sessions via request_id
    - Dispatch JSONL events to per-request queues
    - Forward tool results and aborts back to the bridge
    - Expose a lightweight health probe

Non-scope:
    - Route-level SSE behavior (see routes/)
    - Tool execution policy (see llm.py and tools.py)
"""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
from typing import Any, cast

from ..settings import Settings
from .errors import (
    BridgeProcessError,
    BridgeProtocolError,
    BridgeStartupError,
    BridgeTimeoutError,
    BridgeUpstreamError,
)
from .protocol import (
    PROTOCOL_VERSION,
    TERMINAL_EVENT_TYPES,
    BridgeStartRequest,
    build_abort_message,
    build_ping_message,
    build_start_message,
    build_tool_result_message,
    encode_line,
    parse_line,
)

logger = logging.getLogger(__name__)

_SENTINEL = object()
_RUNTIME_LOCK = threading.Lock()
_RUNTIME: BridgeRuntime | None = None
_RUNTIME_KEY: tuple[tuple[str, ...], str | None] | None = None


class BridgeSession:
    """Handle for one in-flight bridge request."""

    def __init__(self, runtime: BridgeRuntime, request_id: str) -> None:
        self.runtime = runtime
        self.request_id = request_id
        self._events: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._closed = False

    def put(self, payload: dict[str, Any] | object) -> None:
        self._events.put(payload)

    def send_tool_result(
        self, *, tool_call_id: str, payload: dict[str, Any], is_error: bool
    ) -> None:
        self.runtime._send(
            build_tool_result_message(
                request_id=self.request_id,
                tool_call_id=tool_call_id,
                payload=payload,
                is_error=is_error,
            )
        )

    def abort(self) -> None:
        if self._closed:
            return
        self.runtime._send(build_abort_message(request_id=self.request_id))

    def events(self) -> Iterator[dict[str, Any]]:
        try:
            while True:
                payload = self._events.get()
                if payload is _SENTINEL:
                    break
                event = payload
                if not isinstance(event, dict):
                    raise BridgeProtocolError("Bridge session received non-dict payload")
                typed_event = cast(dict[str, Any], event)
                event_type = typed_event["type"]
                if event_type == "error":
                    raise BridgeUpstreamError(
                        str(typed_event.get("code", "bridge_error")),
                        str(typed_event.get("message", "Bridge request failed")),
                        retryable=bool(typed_event.get("retryable", False)),
                    )
                yield typed_event
                if event_type in TERMINAL_EVENT_TYPES:
                    break
        finally:
            self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.runtime._remove_session(self.request_id)


class BridgeRuntime:
    """Long-lived Node subprocess runtime for pi-backed generation."""

    def __init__(
        self,
        *,
        command: list[str],
        agent_dir: str | None,
        startup_timeout_s: float = 10.0,
    ) -> None:
        self.command = command
        self.agent_dir = agent_dir
        self.startup_timeout_s = startup_timeout_s
        self._process: subprocess.Popen[bytes] | None = None
        self._process_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._sessions: dict[str, BridgeSession] = {}
        self._sessions_lock = threading.Lock()
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: deque[str] = deque(maxlen=100)
        self._bridge_info: dict[str, Any] | None = None

    def ensure_started(self) -> dict[str, Any]:
        with self._process_lock:
            if (
                self._process is not None
                and self._process.poll() is None
                and self._bridge_info is not None
            ):
                return self._bridge_info

            self.shutdown()

            env = os.environ.copy()
            if self.agent_dir:
                env["PI_CODING_AGENT_DIR"] = self.agent_dir

            try:
                process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    bufsize=0,
                )
            except OSError as exc:
                raise BridgeStartupError(
                    f"Failed to start pi bridge command {' '.join(self.command)!r}: {exc}"
                ) from exc

            self._process = process
            self._stderr_lines.clear()
            self._start_stderr_thread(process)
            self._bridge_info = self._read_handshake(process)
            self._start_stdout_thread(process)
            return self._bridge_info

    def open_session(self, request: BridgeStartRequest) -> BridgeSession:
        self.ensure_started()
        session = BridgeSession(self, request.request_id)
        with self._sessions_lock:
            self._sessions[request.request_id] = session
        try:
            self._send(build_start_message(request))
        except Exception:
            session.close()
            raise
        return session

    def ping(self, timeout_s: float = 5.0) -> dict[str, Any]:
        info = self.ensure_started()
        request_id = f"ping-{uuid.uuid4().hex}"
        session = BridgeSession(self, request_id)
        with self._sessions_lock:
            self._sessions[request_id] = session
        self._send(build_ping_message(request_id=request_id))
        deadline = time.monotonic() + timeout_s
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BridgeTimeoutError("Timed out waiting for pi bridge ping")
                try:
                    payload = session._events.get(timeout=remaining)
                except queue.Empty as exc:
                    raise BridgeTimeoutError("Timed out waiting for pi bridge ping") from exc
                if payload is _SENTINEL:
                    raise BridgeProcessError("Pi bridge closed while waiting for ping")
                if not isinstance(payload, dict):
                    raise BridgeProtocolError("Bridge ping received non-dict payload")
                typed_payload = cast(dict[str, Any], payload)
                if typed_payload.get("type") != "pong":
                    raise BridgeProtocolError(
                        "Expected bridge pong for request "
                        f"{request_id}, received {typed_payload.get('type')!r}"
                    )
                return {
                    "bridge": info,
                    "latency_ms": float(typed_payload.get("latency_ms", 0.0)),
                }
        finally:
            session.close()

    def shutdown(self) -> None:
        process = self._process
        self._process = None
        self._bridge_info = None

        if process is None:
            return

        try:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)

    def _send(self, payload: dict[str, Any]) -> None:
        self.ensure_started()
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise BridgeProcessError("Pi bridge process is not available")
        data = encode_line(payload)
        with self._write_lock:
            try:
                process.stdin.write(data)
                process.stdin.flush()
            except OSError as exc:
                raise BridgeProcessError(f"Failed to write to pi bridge: {exc}") from exc

    def _read_handshake(self, process: subprocess.Popen[bytes]) -> dict[str, Any]:
        if process.stdout is None:
            raise BridgeStartupError("Pi bridge stdout is unavailable")

        handshake_queue: queue.Queue[tuple[bytes | None, Exception | None]] = queue.Queue(maxsize=1)

        def _reader() -> None:
            assert process.stdout is not None
            try:
                handshake_queue.put((process.stdout.readline(), None))
            except Exception as exc:  # noqa: BLE001
                handshake_queue.put((None, exc))

        threading.Thread(
            target=_reader,
            name="cloop-pi-bridge-handshake",
            daemon=True,
        ).start()

        deadline = time.monotonic() + self.startup_timeout_s
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr_text = "\n".join(self._stderr_lines).strip()
                detail = f": {stderr_text}" if stderr_text else ""
                raise BridgeStartupError(f"Pi bridge exited during startup{detail}")
            try:
                line, error = handshake_queue.get(timeout=min(0.05, deadline - time.monotonic()))
            except queue.Empty:
                continue
            if error is not None:
                raise BridgeStartupError(f"Failed reading pi bridge handshake: {error}") from error
            if not line:
                time.sleep(0.01)
                continue
            payload = parse_line(line.decode("utf-8"))
            if payload.get("type") != "hello":
                raise BridgeProtocolError(
                    f"Expected pi bridge hello handshake, received {payload.get('type')!r}"
                )
            return payload
        raise BridgeStartupError("Timed out waiting for pi bridge handshake")

    def _start_stdout_thread(self, process: subprocess.Popen[bytes]) -> None:
        def _reader() -> None:
            assert process.stdout is not None
            try:
                for raw_line in iter(process.stdout.readline, b""):
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        payload = parse_line(line)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("Invalid pi bridge payload: %s", exc)
                        self._fail_all_sessions(
                            BridgeProtocolError(f"Invalid pi bridge payload: {exc}")
                        )
                        continue

                    request_id = payload.get("request_id")
                    if not isinstance(request_id, str):
                        if payload.get("type") == "hello":
                            continue
                        self._fail_all_sessions(
                            BridgeProtocolError(
                                f"Bridge payload missing request_id: {payload.get('type')!r}"
                            )
                        )
                        continue

                    with self._sessions_lock:
                        session = self._sessions.get(request_id)
                    if session is None:
                        logger.warning(
                            "Dropping pi bridge event for unknown request_id %s (%s)",
                            request_id,
                            payload.get("type"),
                        )
                        continue
                    session.put(payload)
            finally:
                self._fail_all_sessions(self._build_process_exit_error(process))

        self._stdout_thread = threading.Thread(
            target=_reader,
            name="cloop-pi-bridge-stdout",
            daemon=True,
        )
        self._stdout_thread.start()

    def _start_stderr_thread(self, process: subprocess.Popen[bytes]) -> None:
        def _reader() -> None:
            assert process.stderr is not None
            for raw_line in iter(process.stderr.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                self._stderr_lines.append(line)
                logger.warning("pi bridge stderr: %s", line)

        self._stderr_thread = threading.Thread(
            target=_reader,
            name="cloop-pi-bridge-stderr",
            daemon=True,
        )
        self._stderr_thread.start()

    def _build_process_exit_error(self, process: subprocess.Popen[bytes]) -> BridgeProcessError:
        exit_code = process.poll()
        stderr_text = "\n".join(self._stderr_lines).strip()
        detail = f": {stderr_text}" if stderr_text else ""
        return BridgeProcessError(f"Pi bridge exited with code {exit_code}{detail}")

    def _fail_all_sessions(self, exc: Exception) -> None:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.put(
                {
                    "type": "error",
                    "protocol": PROTOCOL_VERSION,
                    "request_id": session.request_id,
                    "code": type(exc).__name__,
                    "message": str(exc),
                    "retryable": False,
                }
            )
            session.put(_SENTINEL)
        self._process = None
        self._bridge_info = None

    def _remove_session(self, request_id: str) -> None:
        with self._sessions_lock:
            self._sessions.pop(request_id, None)


def get_bridge_runtime(settings: Settings) -> BridgeRuntime:
    """Return the singleton bridge runtime for the active bridge command."""
    global _RUNTIME, _RUNTIME_KEY
    command = settings.pi_bridge_command()
    key = (tuple(command), settings.pi_agent_dir)
    with _RUNTIME_LOCK:
        if _RUNTIME is None or _RUNTIME_KEY != key:
            if _RUNTIME is not None:
                _RUNTIME.shutdown()
            _RUNTIME = BridgeRuntime(command=command, agent_dir=settings.pi_agent_dir)
            _RUNTIME_KEY = key
        return _RUNTIME


def shutdown_bridge_runtime() -> None:
    """Terminate the singleton bridge runtime, if any."""
    global _RUNTIME, _RUNTIME_KEY
    with _RUNTIME_LOCK:
        if _RUNTIME is not None:
            _RUNTIME.shutdown()
        _RUNTIME = None
        _RUNTIME_KEY = None


def bridge_health(settings: Settings) -> dict[str, Any]:
    """Probe the bridge and return readiness details for /health."""
    runtime = get_bridge_runtime(settings)
    ping = runtime.ping(timeout_s=min(settings.pi_timeout, 5.0))
    bridge_info = dict(ping["bridge"])
    bridge_info["latency_ms"] = ping["latency_ms"]
    return bridge_info
