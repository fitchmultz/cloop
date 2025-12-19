import json
import sqlite3
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional

from .settings import Settings, get_settings

_VECTOR_EXTENSION_ATTEMPTED = False
_VECTOR_EXTENSION_AVAILABLE = False


class VectorBackend(StrEnum):
    NONE = "none"
    VEC = "vec"
    VSS = "vss"


SCHEMA_VERSION: int = 7
RAG_SCHEMA_VERSION: int = 1
_VECTOR_BACKEND: VectorBackend = VectorBackend.NONE

PRAGMAS = [
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("foreign_keys", "ON"),
    ("cache_size", "-20000"),
    ("temp_store", "MEMORY"),
]

_CORE_SCHEMA = """
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE interactions (
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

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE loops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    definition_of_done TEXT,
    next_action TEXT,
    status TEXT NOT NULL,
    captured_at_utc TEXT NOT NULL,
    captured_tz_offset_min INTEGER NOT NULL,
    due_at_utc TEXT,
    snooze_until_utc TEXT,
    time_minutes INTEGER,
    activation_energy INTEGER,
    urgency REAL,
    importance REAL,
    project_id INTEGER,
    user_locks_json TEXT NOT NULL DEFAULT '[]',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    enrichment_state TEXT NOT NULL DEFAULT 'idle',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX idx_loops_status ON loops(status);
CREATE INDEX idx_loops_captured_at ON loops(captured_at_utc);

CREATE TABLE loop_tags (
    loop_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (loop_id, tag_id),
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_tags_loop_id ON loop_tags(loop_id);
CREATE INDEX idx_loop_tags_tag_id ON loop_tags(tag_id);

CREATE TABLE loop_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    related_loop_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    confidence REAL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    FOREIGN KEY(related_loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_loop_links_unique
    ON loop_links(loop_id, related_loop_id, relationship_type, source);

CREATE TABLE loop_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_events_loop_id ON loop_events(loop_id);

CREATE TABLE loop_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    suggestion_json TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_suggestions_loop_id ON loop_suggestions(loop_id);

CREATE TABLE loop_embeddings (
    loop_id INTEGER PRIMARY KEY,
    embedding_blob BLOB NOT NULL,
    embedding_dim INTEGER NOT NULL,
    embedding_norm REAL NOT NULL,
    embed_model TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);
"""

_CORE_MIGRATIONS: dict[int, str] = {
    2: """
    CREATE TABLE loops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_text TEXT NOT NULL,
        title TEXT,
        status TEXT NOT NULL,
        captured_at_utc TEXT NOT NULL,
        captured_tz_offset_min INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        closed_at TEXT
    );

    CREATE INDEX idx_loops_status ON loops(status);
    CREATE INDEX idx_loops_captured_at ON loops(captured_at_utc);

    CREATE TABLE loop_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_loop_events_loop_id ON loop_events(loop_id);
    """,
    3: """
    ALTER TABLE loops ADD COLUMN summary TEXT;
    ALTER TABLE loops ADD COLUMN definition_of_done TEXT;
    ALTER TABLE loops ADD COLUMN next_action TEXT;
    ALTER TABLE loops ADD COLUMN due_at_utc TEXT;
    ALTER TABLE loops ADD COLUMN snooze_until_utc TEXT;
    ALTER TABLE loops ADD COLUMN time_minutes INTEGER;
    ALTER TABLE loops ADD COLUMN activation_energy INTEGER;
    ALTER TABLE loops ADD COLUMN urgency REAL;
    ALTER TABLE loops ADD COLUMN importance REAL;
    ALTER TABLE loops ADD COLUMN project_id INTEGER;
    ALTER TABLE loops ADD COLUMN user_locks_json TEXT NOT NULL DEFAULT '[]';
    ALTER TABLE loops ADD COLUMN provenance_json TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE loops ADD COLUMN enrichment_state TEXT NOT NULL DEFAULT 'idle';

    CREATE TABLE projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE loop_tags (
        loop_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (loop_id, tag_id),
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
        FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_loop_tags_loop_id ON loop_tags(loop_id);
    CREATE INDEX idx_loop_tags_tag_id ON loop_tags(tag_id);

    CREATE TABLE loop_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER NOT NULL,
        related_loop_id INTEGER NOT NULL,
        relationship_type TEXT NOT NULL,
        confidence REAL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
        FOREIGN KEY(related_loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    CREATE UNIQUE INDEX idx_loop_links_unique
        ON loop_links(loop_id, related_loop_id, relationship_type, source);

    CREATE TABLE loop_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER NOT NULL,
        suggestion_json TEXT NOT NULL,
        model TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_loop_suggestions_loop_id ON loop_suggestions(loop_id);
    """,
    4: """
    CREATE TABLE loop_embeddings (
        loop_id INTEGER PRIMARY KEY,
        embedding_blob BLOB NOT NULL,
        embedding_dim INTEGER NOT NULL,
        embedding_norm REAL NOT NULL,
        embed_model TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );
    """,
    5: """
    UPDATE loops SET status = 'actionable' WHERE status = 'active';
    UPDATE loops SET status = 'blocked' WHERE status = 'waiting';
    UPDATE loops SET status = 'completed' WHERE status = 'done';
    """,
    6: """
    CREATE TEMP TABLE tag_merge AS
        SELECT LOWER(name) AS lname, MIN(id) AS keep_id
        FROM tags
        GROUP BY LOWER(name);

    UPDATE loop_tags
    SET tag_id = (
        SELECT keep_id
        FROM tag_merge
        WHERE lname = (
            SELECT LOWER(name) FROM tags WHERE id = loop_tags.tag_id
        )
    );

    DELETE FROM tags WHERE id NOT IN (SELECT keep_id FROM tag_merge);
    UPDATE tags SET name = LOWER(name);
    DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM loop_tags);
    DROP TABLE tag_merge;
    """,
    7: """
    UPDATE loops
    SET updated_at = created_at
    WHERE updated_at IS NULL OR updated_at = '';
    """,
}

_RAG_SCHEMA = """
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_path TEXT UNIQUE NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_documents_path ON documents(document_path);

CREATE TABLE chunks (
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

CREATE INDEX idx_chunks_document_path ON chunks(document_path);
CREATE INDEX idx_chunks_docid ON chunks(doc_id);
"""


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    for pragma, value in PRAGMAS:
        conn.execute(f"PRAGMA {pragma}={value}")


def _user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def _has_application_tables(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return bool(rows)


def _assert_schema(conn: sqlite3.Connection, expected: int) -> None:
    found = _user_version(conn)
    if found != expected:
        raise RuntimeError(f"schema_mismatch: expected={expected} found={found}")


def _initialize_schema_if_needed(
    conn: sqlite3.Connection,
    schema_sql: str,
    *,
    expected_version: int,
) -> None:
    version = _user_version(conn)
    if version == 0:
        if _has_application_tables(conn):
            raise RuntimeError("schema_mismatch: detected unversioned tables")
        conn.executescript(schema_sql)
        conn.execute(f"PRAGMA user_version = {expected_version}")
        conn.commit()
        return
    if version != expected_version:
        raise RuntimeError(f"schema_mismatch: expected={expected_version} found={version}")


def migrate_core_db(
    conn: sqlite3.Connection,
    *,
    from_version: int,
    to_version: int,
) -> None:
    if from_version >= to_version:
        return
    for version in range(from_version + 1, to_version + 1):
        migration = _CORE_MIGRATIONS.get(version)
        if migration is None:
            raise RuntimeError(f"missing core migration for version {version}")
        conn.executescript(migration)
        conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()


def ensure_core_schema(conn: sqlite3.Connection) -> None:
    version = _user_version(conn)
    if version == 0:
        if _has_application_tables(conn):
            raise RuntimeError("schema_mismatch: detected unversioned tables")
        conn.executescript(_CORE_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
        return
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"schema_mismatch: expected={SCHEMA_VERSION} found={version}")
    if version < SCHEMA_VERSION:
        migrate_core_db(conn, from_version=version, to_version=SCHEMA_VERSION)


def _detect_vector_backend(conn: sqlite3.Connection) -> VectorBackend:
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
        _VECTOR_EXTENSION_AVAILABLE = _VECTOR_BACKEND is not VectorBackend.NONE
    except sqlite3.Error:
        _VECTOR_EXTENSION_AVAILABLE = False
        _VECTOR_BACKEND = VectorBackend.NONE
    finally:
        conn.enable_load_extension(False)


def vector_extension_available() -> bool:
    return _VECTOR_EXTENSION_AVAILABLE


def get_vector_backend() -> VectorBackend:
    return _VECTOR_BACKEND


def reset_vector_backend() -> None:
    global _VECTOR_BACKEND, _VECTOR_EXTENSION_AVAILABLE, _VECTOR_EXTENSION_ATTEMPTED
    _VECTOR_BACKEND = VectorBackend.NONE
    _VECTOR_EXTENSION_AVAILABLE = False
    _VECTOR_EXTENSION_ATTEMPTED = False


def init_core_db(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    with core_connection(settings) as conn:
        ensure_core_schema(conn)


def init_rag_db(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    with rag_connection(settings) as conn:
        _initialize_schema_if_needed(conn, _RAG_SCHEMA, expected_version=RAG_SCHEMA_VERSION)


def init_databases(settings: Optional[Settings] = None) -> None:
    settings = settings or get_settings()
    init_core_db(settings)
    init_rag_db(settings)
    with core_connection(settings) as core_conn:
        _assert_schema(core_conn, SCHEMA_VERSION)
    with rag_connection(settings) as rag_conn:
        _assert_schema(rag_conn, RAG_SCHEMA_VERSION)


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
