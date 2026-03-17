"""SQLite vector extension state and detection helpers.

Purpose:
    Manage optional SQLite vector-extension loading and backend detection
    behind the canonical `cloop.db` facade.

Responsibilities:
    - Track vector-extension availability as thread-safe process state
    - Attempt extension loading at most once per process
    - Detect whether vec, vss, or no vector backend is available

Non-scope:
    - Connection lifecycle management or schema migrations
    - Embedding generation or similarity-search orchestration

Scope:
    - Process-local vector extension state only
    - No feature-level query behavior above backend detection

Usage:
    Called by `cloop.db.rag_connection()` and public vector-state helpers.

Invariants/Assumptions:
    - Extension detection is idempotent within a process until reset
    - State access remains thread-safe across concurrent callers
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class VectorBackend(StrEnum):
    NONE = "none"
    VEC = "vec"
    VSS = "vss"


@dataclass(frozen=True)
class VectorExtensionState:
    """Immutable snapshot of vector extension state."""

    attempted: bool
    available: bool
    backend: VectorBackend
    load_error: str | None


class VectorExtensionManager:
    """Thread-safe singleton for managing vector extension state.

    The extension is loaded once per process. This manager provides
    atomic access to the state and supports reset for error recovery.
    """

    _instance: "VectorExtensionManager | None" = None
    _lock: threading.Lock = threading.Lock()
    _state: VectorExtensionState
    _state_lock: threading.Lock

    def __new__(cls) -> "VectorExtensionManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._state = VectorExtensionState(
                        attempted=False,
                        available=False,
                        backend=VectorBackend.NONE,
                        load_error=None,
                    )
                    instance._state_lock = threading.Lock()
                    cls._instance = instance
        return cls._instance

    def get_state(self) -> VectorExtensionState:
        """Return current state snapshot (thread-safe)."""
        with self._state_lock:
            return self._state

    def attempt_load(self, conn: sqlite3.Connection, extension_path: str | None) -> None:
        """Attempt to load vector extension (once per process, thread-safe).

        This method is idempotent - subsequent calls are no-ops.
        """
        with self._state_lock:
            if self._state.attempted:
                return

            if not extension_path:
                self._state = VectorExtensionState(
                    attempted=True,
                    available=False,
                    backend=VectorBackend.NONE,
                    load_error=None,
                )
                return

            try:
                conn.enable_load_extension(True)
                conn.load_extension(extension_path)
                backend = detect_vector_backend(conn)
                self._state = VectorExtensionState(
                    attempted=True,
                    available=backend is not VectorBackend.NONE,
                    backend=backend,
                    load_error=None,
                )
            except sqlite3.Error as e:
                self._state = VectorExtensionState(
                    attempted=True,
                    available=False,
                    backend=VectorBackend.NONE,
                    load_error=str(e),
                )
                logger.warning(
                    "Failed to load SQLite vector extension from '%s': %s. "
                    "Vector search will fall back to SQLite/Python mode.",
                    extension_path,
                    e,
                )
            finally:
                conn.enable_load_extension(False)

    def reset(self) -> None:
        """Reset state to allow re-detection (used after errors)."""
        with self._state_lock:
            self._state = VectorExtensionState(
                attempted=False,
                available=False,
                backend=VectorBackend.NONE,
                load_error=None,
            )


def get_vector_manager() -> VectorExtensionManager:
    """Get the singleton manager instance."""
    return VectorExtensionManager()


def detect_vector_backend(conn: sqlite3.Connection) -> VectorBackend:
    try:
        conn.execute("DROP TABLE IF EXISTS temp_vec_probe")
        conn.execute("CREATE VIRTUAL TABLE temp_vec_probe USING vec0(embedding float[1])")
        conn.execute("DROP TABLE temp_vec_probe")
        return VectorBackend.VEC
    except sqlite3.Error:
        pass
    try:
        conn.execute("DROP TABLE IF EXISTS temp_vss_probe")
        conn.execute("CREATE VIRTUAL TABLE temp_vss_probe USING vss0(embedding(1))")
        conn.execute("DROP TABLE temp_vss_probe")
        return VectorBackend.VSS
    except sqlite3.Error:
        return VectorBackend.NONE


def maybe_load_vector_extension(conn: sqlite3.Connection, *, extension_path: str | None) -> None:
    get_vector_manager().attempt_load(conn, extension_path)


def vector_extension_available() -> bool:
    return get_vector_manager().get_state().available


def get_vector_backend() -> VectorBackend:
    return get_vector_manager().get_state().backend


def get_vector_load_error() -> str | None:
    return get_vector_manager().get_state().load_error


def reset_vector_backend() -> None:
    get_vector_manager().reset()


__all__ = [
    "VectorBackend",
    "VectorExtensionManager",
    "VectorExtensionState",
    "detect_vector_backend",
    "get_vector_backend",
    "get_vector_load_error",
    "get_vector_manager",
    "maybe_load_vector_extension",
    "reset_vector_backend",
    "vector_extension_available",
]
