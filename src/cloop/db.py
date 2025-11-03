from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

from .settings import Settings, get_settings

_VECTOR_EXTENSION_ATTEMPTED = False
_VECTOR_EXTENSION_AVAILABLE = False
_VECTOR_BACKEND = "none"

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


def _detect_vector_backend(conn: sqlite3.Connection) -> str:
    try:
        conn.execute("DROP TABLE IF EXISTS temp_vec_probe")
        conn.execute("CREATE VIRTUAL TABLE temp_vec_probe USING vec0(embedding float[1])")
        conn.execute("DROP TABLE temp_vec_probe")
        return "vec"
    except sqlite3.Error:
        pass
    try:
        conn.execute("DROP TABLE IF EXISTS temp_vss_probe")
        conn.execute("CREATE VIRTUAL TABLE temp_vss_probe USING vss0(embedding(1))")
        conn.execute("DROP TABLE temp_vss_probe")
        return "vss"
    except sqlite3.Error:
        return "none"


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
    global _VECTOR_EXTENSION_ATTEMPTED, _VECTOR_EXTENSION_AVAILABLE, _VECTOR_BACKEND
    if _VECTOR_EXTENSION_ATTEMPTED:
        return
    _VECTOR_EXTENSION_ATTEMPTED = True
    extension_path = settings.sqlite_vector_extension
    if not extension_path:
        return
    try:
        conn.enable_load_extension(True)
        conn.load_extension(extension_path)
        _VECTOR_BACKEND = _detect_vector_backend(conn)
        _VECTOR_EXTENSION_AVAILABLE = _VECTOR_BACKEND != "none"
    except sqlite3.Error:
        _VECTOR_EXTENSION_AVAILABLE = False
        _VECTOR_BACKEND = "none"
    finally:
        conn.enable_load_extension(False)


def vector_extension_available() -> bool:
    return _VECTOR_EXTENSION_AVAILABLE


def get_vector_backend() -> str:
    return _VECTOR_BACKEND


def reset_vector_backend() -> None:
    global _VECTOR_BACKEND, _VECTOR_EXTENSION_AVAILABLE, _VECTOR_EXTENSION_ATTEMPTED
    _VECTOR_BACKEND = "none"
    _VECTOR_EXTENSION_AVAILABLE = False
    _VECTOR_EXTENSION_ATTEMPTED = False


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
                tool_calls TEXT,
                selected_chunks TEXT,
                token_estimate INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        try:
            conn.execute("ALTER TABLE interactions ADD COLUMN tool_calls TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()


def init_rag_db(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    with rag_connection(settings) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_path TEXT UNIQUE NOT NULL,
                mtime_ns INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(document_path);

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                metadata TEXT,
                doc_id INTEGER,
                embedding_blob BLOB,
                embedding_norm REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_document_path ON chunks(document_path);
            CREATE INDEX IF NOT EXISTS idx_chunks_docid ON chunks(doc_id);
            """
        )
        try:
            conn.execute("ALTER TABLE chunks ADD COLUMN doc_id INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE chunks ADD COLUMN embedding_blob BLOB")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE chunks ADD COLUMN embedding_norm REAL")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("CREATE INDEX idx_chunks_docid ON chunks(doc_id)")
        except sqlite3.OperationalError:
            pass
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
    tool_calls: Optional[Iterable[Dict[str, Any]]] = None,
    settings: Optional[Settings] = None,
) -> None:
    settings = settings or get_settings()
    sanitized_chunks: list[Dict[str, Any]] = []
    if selected_chunks:
        for chunk in selected_chunks:
            chunk_map = dict(chunk)
            if "embedding_blob" in chunk_map:
                chunk_map["embedding_blob"] = None
            sanitized_chunks.append(chunk_map)

    payload = {
        "endpoint": endpoint,
        "model": model,
        "latency_ms": latency_ms,
        "request_payload": json.dumps(request_payload),
        "response_payload": json.dumps(response_payload),
        "tool_calls": json.dumps(list(tool_calls) if tool_calls else []),
        "selected_chunks": json.dumps(sanitized_chunks),
        "token_estimate": token_estimate,
    }
    with core_connection(settings) as conn:
        conn.execute(
            """
            INSERT INTO interactions (
                endpoint, model, latency_ms, request_payload,
                response_payload, tool_calls, selected_chunks, token_estimate
            )
            VALUES (:endpoint, :model, :latency_ms, :request_payload,
                    :response_payload, :tool_calls, :selected_chunks, :token_estimate)
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
