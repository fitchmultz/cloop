from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

from .settings import Settings, get_settings

_VECTOR_EXTENSION_ATTEMPTED = False

PRAGMAS = [
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("foreign_keys", "ON"),
    ("cache_size", "-20000"),
    ("temp_store", "MEMORY"),
]


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    for pragma, value in PRAGMAS:
        conn.execute(f"PRAGMA {pragma}={value}")


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


@contextmanager
def core_connection(settings: Optional[Settings] = None) -> Iterator[sqlite3.Connection]:
    settings = settings or get_settings()
    conn = _connect(settings.core_db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def rag_connection(settings: Optional[Settings] = None) -> Iterator[sqlite3.Connection]:
    settings = settings or get_settings()
    conn = _connect(settings.rag_db_path)
    _maybe_load_vector_extension(conn, settings)
    try:
        yield conn
    finally:
        conn.close()


def _maybe_load_vector_extension(conn: sqlite3.Connection, settings: Settings) -> None:
    global _VECTOR_EXTENSION_ATTEMPTED
    if _VECTOR_EXTENSION_ATTEMPTED:
        return
    _VECTOR_EXTENSION_ATTEMPTED = True
    extension_path = settings.sqlite_vector_extension
    if not extension_path:
        return
    try:
        conn.enable_load_extension(True)
        conn.load_extension(extension_path)
    except sqlite3.Error:
        pass
    finally:
        conn.enable_load_extension(False)


def init_core_db(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    with core_connection(settings) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                model TEXT,
                latency_ms REAL,
                request_payload TEXT,
                response_payload TEXT,
                selected_chunks TEXT,
                token_estimate INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()


def init_rag_db(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    with rag_connection(settings) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_document_path ON chunks(document_path);
            """
        )
        conn.commit()


def init_databases(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    init_core_db(settings)
    init_rag_db(settings)


def record_interaction(
    *,
    endpoint: str,
    request_payload: Dict[str, Any],
    response_payload: Dict[str, Any],
    model: Optional[str],
    latency_ms: Optional[float],
    token_estimate: Optional[int],
    selected_chunks: Optional[Iterable[Dict[str, Any]]] = None,
    settings: Optional[Settings] = None,
) -> None:
    settings = settings or get_settings()
    payload = {
        "endpoint": endpoint,
        "model": model,
        "latency_ms": latency_ms,
        "request_payload": json.dumps(request_payload),
        "response_payload": json.dumps(response_payload),
        "selected_chunks": json.dumps(list(selected_chunks) if selected_chunks else []),
        "token_estimate": token_estimate,
    }
    with core_connection(settings) as conn:
        conn.execute(
            """
            INSERT INTO interactions (
                endpoint, model, latency_ms, request_payload,
                response_payload, selected_chunks, token_estimate
            )
            VALUES (:endpoint, :model, :latency_ms, :request_payload,
                    :response_payload, :selected_chunks, :token_estimate)
            """,
            payload,
        )
        conn.commit()


def upsert_note(
    *,
    title: str,
    body: str,
    note_id: Optional[int] = None,
    settings: Optional[Settings] = None,
) -> Dict[str, Any]:
    settings = settings or get_settings()
    with core_connection(settings) as conn:
        if note_id is None:
            cursor = conn.execute(
                "INSERT INTO notes (title, body) VALUES (?, ?)",
                (title, body),
            )
            conn.commit()
            note_id = cursor.lastrowid
        else:
            conn.execute(
                """
                UPDATE notes
                SET title = ?, body = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (title, body, note_id),
            )
            conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else {}


def read_note(note_id: int, settings: Optional[Settings] = None) -> Optional[Dict[str, Any]]:
    settings = settings or get_settings()
    with core_connection(settings) as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else None
