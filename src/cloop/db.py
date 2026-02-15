"""Database connection management and schema migrations.

Purpose:
    Provide SQLite connection handling, schema versioning, and migrations
    for both core (loops/notes) and RAG (documents/chunks) databases.

Responsibilities:
    - Manage database connections with proper PRAGMA settings
    - Track and apply schema migrations via PRAGMA user_version
    - Support optional vector extensions (vec, vss) for similarity search

Non-scope:
    - Business logic and domain operations (see loops/service.py)
    - Query construction (see loops/repo.py)
"""

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping

from .settings import Settings, get_settings

logger = logging.getLogger(__name__)

_VECTOR_EXTENSION_ATTEMPTED = False
_VECTOR_EXTENSION_AVAILABLE = False
_VECTOR_LOAD_ERROR: str | None = None


class VectorBackend(StrEnum):
    NONE = "none"
    VEC = "vec"
    VSS = "vss"


SCHEMA_VERSION: int = 18
RAG_SCHEMA_VERSION: int = 1
_VECTOR_BACKEND: VectorBackend = VectorBackend.NONE

PRAGMAS = [
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
    ("foreign_keys", "ON"),
    ("cache_size", "-20000"),
    ("temp_store", "MEMORY"),
]

_IDEMPOTENCY_PENDING_WAIT_SECONDS = 15.0
_IDEMPOTENCY_PENDING_POLL_SECONDS = 0.05

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
    blocked_reason TEXT,
    completion_note TEXT,
    user_locks_json TEXT NOT NULL DEFAULT '[]',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    enrichment_state TEXT NOT NULL DEFAULT 'idle',
    recurrence_rrule TEXT,
    recurrence_tz TEXT,
    next_due_at_utc TEXT,
    recurrence_enabled INTEGER NOT NULL DEFAULT 0,
    parent_loop_id INTEGER REFERENCES loops(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
);

CREATE INDEX idx_loops_status ON loops(status);
CREATE INDEX idx_loops_captured_at ON loops(captured_at_utc);
CREATE INDEX idx_loops_recurrence_enabled ON loops(recurrence_enabled);
CREATE INDEX idx_loops_next_due_at ON loops(next_due_at_utc) WHERE recurrence_enabled = 1;
CREATE INDEX idx_loops_parent_id ON loops(parent_loop_id);

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

CREATE TABLE idempotency_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_status INTEGER,
    response_body_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL,
    UNIQUE(scope, idempotency_key)
);

CREATE INDEX idx_idempotency_keys_expires_at ON idempotency_keys(expires_at);

CREATE TABLE loop_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    query TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_loop_views_name ON loop_views(name);

CREATE TABLE webhook_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    event_types TEXT NOT NULL DEFAULT '["*"]',
    active BOOLEAN NOT NULL DEFAULT 1,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_webhook_subscriptions_active ON webhook_subscriptions(active);

CREATE TABLE webhook_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    http_status INTEGER,
    response_body TEXT,
    error_message TEXT,
    signature TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY(event_id) REFERENCES loop_events(id) ON DELETE CASCADE
);

CREATE INDEX idx_webhook_deliveries_status ON webhook_deliveries(status);
CREATE INDEX idx_webhook_deliveries_next_retry ON webhook_deliveries(next_retry_at)
    WHERE status = 'pending';
CREATE INDEX idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);

CREATE TABLE loop_claims (
    loop_id INTEGER PRIMARY KEY,
    owner TEXT NOT NULL,
    claim_token TEXT NOT NULL,
    leased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_until TEXT NOT NULL,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_claims_lease_until ON loop_claims(lease_until);

CREATE TABLE loop_dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    depends_on_loop_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    FOREIGN KEY(depends_on_loop_id) REFERENCES loops(id) ON DELETE CASCADE,
    UNIQUE(loop_id, depends_on_loop_id)
);

CREATE INDEX idx_loop_dependencies_loop_id ON loop_dependencies(loop_id);
CREATE INDEX idx_loop_dependencies_depends_on ON loop_dependencies(depends_on_loop_id);

CREATE TABLE time_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_time_sessions_loop_id ON time_sessions(loop_id);
CREATE INDEX idx_time_sessions_active ON time_sessions(loop_id, ended_at) WHERE ended_at IS NULL;

CREATE TABLE loop_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    raw_text_pattern TEXT NOT NULL DEFAULT '',
    defaults_json TEXT NOT NULL DEFAULT '{}',
    is_system INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_loop_templates_name ON loop_templates(name);
CREATE INDEX idx_loop_templates_is_system ON loop_templates(is_system);

-- Create loop_comments table for threaded discussion on loops
CREATE TABLE loop_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    parent_id INTEGER REFERENCES loop_comments(id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    body_md TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
);

CREATE INDEX idx_loop_comments_loop_id ON loop_comments(loop_id);
CREATE INDEX idx_loop_comments_parent_id ON loop_comments(parent_id);
CREATE INDEX idx_loop_comments_created_at ON loop_comments(created_at);

-- Insert system templates for fresh installations
INSERT INTO loop_templates (name, description, raw_text_pattern, defaults_json, is_system) VALUES
    ('Daily Standup', 'Daily standup notes template', 'Standup notes for {{date}}\n\nYesterday:\n- \n\nToday:\n- \n\nBlockers:\n- ', '{"tags": ["standup", "daily"], "time_minutes": 15}', 1),
    ('Weekly Review', 'Weekly review template', 'Weekly review - {{week}} of {{year}}\n\nAccomplishments:\n- \n\nPriorities for next week:\n- \n\nOpen items:\n- ', '{"tags": ["review", "weekly"], "time_minutes": 30}', 1),
    ('Meeting Notes', 'Meeting notes template', 'Meeting: [Title]\nDate: {{date}}\nTime: {{time}}\nAttendees: \n\nAgenda:\n- \n\nNotes:\n- \n\nAction items:\n- ', '{"tags": ["meeting"], "actionable": true}', 1),
    ('Bug Report', 'Bug report template', 'Bug: [Description]\n\nSteps to reproduce:\n1. \n\nExpected:\n\nActual:\n\nEnvironment:', '{"tags": ["bug"], "blocked": true}', 1),
    ('Quick Task', 'Simple actionable task template', '', '{"actionable": true, "time_minutes": 30}', 1);
"""

_CORE_MIGRATIONS: dict[int, str] = {
    18: """
    -- Create loop_comments table for threaded discussion on loops
    CREATE TABLE loop_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER NOT NULL,
        parent_id INTEGER REFERENCES loop_comments(id) ON DELETE CASCADE,
        author TEXT NOT NULL,
        body_md TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        deleted_at TEXT,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_loop_comments_loop_id ON loop_comments(loop_id);
    CREATE INDEX idx_loop_comments_parent_id ON loop_comments(parent_id);
    CREATE INDEX idx_loop_comments_created_at ON loop_comments(created_at);
    """,
    17: """
    -- Create loop_templates table for reusable loop patterns
    CREATE TABLE loop_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        raw_text_pattern TEXT NOT NULL DEFAULT '',
        defaults_json TEXT NOT NULL DEFAULT '{}',
        is_system INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX idx_loop_templates_name ON loop_templates(name);
    CREATE INDEX idx_loop_templates_is_system ON loop_templates(is_system);

    -- Insert system templates
    INSERT INTO loop_templates (name, description, raw_text_pattern, defaults_json, is_system) VALUES
        ('Daily Standup', 'Daily standup notes template', 'Standup notes for {{date}}\n\nYesterday:\n- \n\nToday:\n- \n\nBlockers:\n- ', '{"tags": ["standup", "daily"], "time_minutes": 15}', 1),
        ('Weekly Review', 'Weekly review template', 'Weekly review - {{week}} of {{year}}\n\nAccomplishments:\n- \n\nPriorities for next week:\n- \n\nOpen items:\n- ', '{"tags": ["review", "weekly"], "time_minutes": 30}', 1),
        ('Meeting Notes', 'Meeting notes template', 'Meeting: [Title]\nDate: {{date}}\nTime: {{time}}\nAttendees: \n\nAgenda:\n- \n\nNotes:\n- \n\nAction items:\n- ', '{"tags": ["meeting"], "actionable": true}', 1),
        ('Bug Report', 'Bug report template', 'Bug: [Description]\n\nSteps to reproduce:\n1. \n\nExpected:\n\nActual:\n\nEnvironment:', '{"tags": ["bug"], "blocked": true}', 1),
        ('Quick Task', 'Simple actionable task template', '', '{"actionable": true, "time_minutes": 30}', 1);
    """,
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
    8: """
    ALTER TABLE loops ADD COLUMN blocked_reason TEXT;
    """,
    9: """
    ALTER TABLE loops ADD COLUMN completion_note TEXT;
    """,
    10: """
    CREATE TABLE idempotency_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        response_status INTEGER,
        response_body_json TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT NOT NULL,
        UNIQUE(scope, idempotency_key)
    );

    CREATE INDEX idx_idempotency_keys_expires_at ON idempotency_keys(expires_at);
    """,
    11: """
    CREATE TABLE loop_views (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        query TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX idx_loop_views_name ON loop_views(name);
    """,
    12: """
    CREATE TABLE webhook_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        secret TEXT NOT NULL,
        event_types TEXT NOT NULL DEFAULT '["*"]',
        active BOOLEAN NOT NULL DEFAULT 1,
        description TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX idx_webhook_subscriptions_active ON webhook_subscriptions(active);

    CREATE TABLE webhook_deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subscription_id INTEGER NOT NULL,
        event_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        http_status INTEGER,
        response_body TEXT,
        error_message TEXT,
        signature TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        next_retry_at TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(subscription_id) REFERENCES webhook_subscriptions(id) ON DELETE CASCADE,
        FOREIGN KEY(event_id) REFERENCES loop_events(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_webhook_deliveries_status ON webhook_deliveries(status);
    CREATE INDEX idx_webhook_deliveries_next_retry ON webhook_deliveries(next_retry_at)
        WHERE status = 'pending';
    CREATE INDEX idx_webhook_deliveries_subscription ON webhook_deliveries(subscription_id);
    """,
    13: """
    CREATE TABLE loop_claims (
        loop_id INTEGER PRIMARY KEY,
        owner TEXT NOT NULL,
        claim_token TEXT NOT NULL,
        leased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        lease_until TEXT NOT NULL,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    CREATE INDEX idx_loop_claims_lease_until ON loop_claims(lease_until);
    """,
    14: """
    ALTER TABLE loops ADD COLUMN recurrence_rrule TEXT;
    ALTER TABLE loops ADD COLUMN recurrence_tz TEXT;
    ALTER TABLE loops ADD COLUMN next_due_at_utc TEXT;
    ALTER TABLE loops ADD COLUMN recurrence_enabled INTEGER NOT NULL DEFAULT 0;

    CREATE INDEX idx_loops_recurrence_enabled ON loops(recurrence_enabled);
    CREATE INDEX idx_loops_next_due_at ON loops(next_due_at_utc) WHERE recurrence_enabled = 1;
    """,
    15: """
    -- Add parent_loop_id for hierarchical subtask relationships
    ALTER TABLE loops ADD COLUMN parent_loop_id INTEGER REFERENCES loops(id) ON DELETE SET NULL;

    -- Create index for parent-child queries
    CREATE INDEX idx_loops_parent_id ON loops(parent_loop_id);

    -- Create loop_dependencies table for explicit blocked-by relationships
    CREATE TABLE loop_dependencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER NOT NULL,
        depends_on_loop_id INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE,
        FOREIGN KEY(depends_on_loop_id) REFERENCES loops(id) ON DELETE CASCADE,
        UNIQUE(loop_id, depends_on_loop_id)
    );

    -- Index for finding what blocks a loop
    CREATE INDEX idx_loop_dependencies_loop_id ON loop_dependencies(loop_id);

    -- Index for finding what depends on a loop (for cascade checks)
    CREATE INDEX idx_loop_dependencies_depends_on ON loop_dependencies(depends_on_loop_id);
    """,
    16: """
    -- Create time_sessions table for tracking actual time spent on loops
    CREATE TABLE time_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        duration_seconds INTEGER,
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(loop_id) REFERENCES loops(id) ON DELETE CASCADE
    );

    -- Index for finding sessions by loop
    CREATE INDEX idx_time_sessions_loop_id ON time_sessions(loop_id);

    -- Index for finding active sessions (where ended_at IS NULL)
    CREATE INDEX idx_time_sessions_active ON time_sessions(loop_id, ended_at)
        WHERE ended_at IS NULL;
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
def core_connection(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    settings = settings or get_settings()
    conn = _connect(settings.core_db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def rag_connection(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    settings = settings or get_settings()
    conn = _connect(settings.rag_db_path)
    _maybe_load_vector_extension(conn, settings)
    try:
        yield conn
    finally:
        conn.close()


def _maybe_load_vector_extension(conn: sqlite3.Connection, settings: Settings) -> None:
    global \
        _VECTOR_EXTENSION_ATTEMPTED, \
        _VECTOR_EXTENSION_AVAILABLE, \
        _VECTOR_BACKEND, \
        _VECTOR_LOAD_ERROR
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
        _VECTOR_LOAD_ERROR = None
    except sqlite3.Error as e:
        _VECTOR_EXTENSION_AVAILABLE = False
        _VECTOR_BACKEND = VectorBackend.NONE
        _VECTOR_LOAD_ERROR = str(e)
        logger.warning(
            "Failed to load SQLite vector extension from '%s': %s. "
            "Vector search will fall back to SQLite/Python mode.",
            extension_path,
            e,
        )
    finally:
        conn.enable_load_extension(False)


def vector_extension_available() -> bool:
    return _VECTOR_EXTENSION_AVAILABLE


def get_vector_backend() -> VectorBackend:
    return _VECTOR_BACKEND


def get_vector_load_error() -> str | None:
    """Return the error message from the last vector extension load attempt, if any."""
    return _VECTOR_LOAD_ERROR


def reset_vector_backend() -> None:
    global \
        _VECTOR_BACKEND, \
        _VECTOR_EXTENSION_AVAILABLE, \
        _VECTOR_EXTENSION_ATTEMPTED, \
        _VECTOR_LOAD_ERROR
    _VECTOR_BACKEND = VectorBackend.NONE
    _VECTOR_EXTENSION_AVAILABLE = False
    _VECTOR_EXTENSION_ATTEMPTED = False
    _VECTOR_LOAD_ERROR = None


def init_core_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with core_connection(settings) as conn:
        ensure_core_schema(conn)


def init_rag_db(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    with rag_connection(settings) as conn:
        _initialize_schema_if_needed(conn, _RAG_SCHEMA, expected_version=RAG_SCHEMA_VERSION)


def init_databases(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    init_core_db(settings)
    init_rag_db(settings)
    with core_connection(settings) as core_conn:
        _assert_schema(core_conn, SCHEMA_VERSION)
    with rag_connection(settings) as rag_conn:
        _assert_schema(rag_conn, RAG_SCHEMA_VERSION)


def get_core_schema_version(settings: Settings | None = None) -> int:
    """Get current core database schema version.

    Args:
        settings: Application settings. Uses global settings if not provided.

    Returns:
        The current schema version number (PRAGMA user_version).
        Returns 0 if database doesn't exist or is uninitialized.
    """
    settings = settings or get_settings()
    if not settings.core_db_path.exists():
        return 0
    with core_connection(settings) as conn:
        return _user_version(conn)


def get_rag_schema_version(settings: Settings | None = None) -> int:
    """Get current RAG database schema version.

    Args:
        settings: Application settings. Uses global settings if not provided.

    Returns:
        The current schema version number (PRAGMA user_version).
        Returns 0 if database doesn't exist or is uninitialized.
    """
    settings = settings or get_settings()
    if not settings.rag_db_path.exists():
        return 0
    with rag_connection(settings) as conn:
        return _user_version(conn)


def record_interaction(
    *,
    endpoint: str,
    request_payload: Dict[str, Any],
    response_payload: Dict[str, Any],
    model: str | None,
    latency_ms: float | None,
    token_estimate: int | None,
    selected_chunks: Iterable[Dict[str, Any]] | None = None,
    tool_calls: Iterable[Dict[str, Any]] | None = None,
    settings: Settings | None = None,
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
    note_id: int | None = None,
    settings: Settings | None = None,
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


def read_note(note_id: int, settings: Settings | None = None) -> Dict[str, Any] | None:
    settings = settings or get_settings()
    with core_connection(settings) as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else None


def purge_expired_idempotency_keys(*, conn: sqlite3.Connection) -> int:
    """Delete expired idempotency keys from the database.

    Args:
        conn: SQLite connection to core database

    Returns:
        Number of deleted rows
    """
    cursor = conn.execute("DELETE FROM idempotency_keys WHERE expires_at < CURRENT_TIMESTAMP")
    conn.commit()
    return cursor.rowcount


def _read_idempotency_row(
    *,
    scope: str,
    idempotency_key: str,
    conn: sqlite3.Connection,
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT request_hash,
               response_status,
               response_body_json,
               datetime(expires_at) < datetime('now') AS is_expired
        FROM idempotency_keys
        WHERE scope = ? AND idempotency_key = ?
        """,
        (scope, idempotency_key),
    ).fetchone()


def _try_claim_expired_idempotency_key(
    *,
    scope: str,
    idempotency_key: str,
    request_hash: str,
    expires_at: str,
    conn: sqlite3.Connection,
) -> bool:
    cursor = conn.execute(
        """
        UPDATE idempotency_keys
        SET request_hash = ?,
            response_status = NULL,
            response_body_json = NULL,
            created_at = CURRENT_TIMESTAMP,
            last_seen_at = CURRENT_TIMESTAMP,
            expires_at = ?
        WHERE scope = ?
          AND idempotency_key = ?
          AND datetime(expires_at) < datetime('now')
        """,
        (request_hash, expires_at, scope, idempotency_key),
    )
    conn.commit()
    return cursor.rowcount == 1


def claim_or_replay_idempotency(
    *,
    scope: str,
    idempotency_key: str,
    request_hash: str,
    expires_at: str,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Claim an idempotency key or retrieve prior response.

    This function implements the claim/replay pattern:
    - If no row exists: insert pending row, return is_new=True
    - If row exists with different hash: raise IdempotencyConflictError
    - If row exists with same hash and response: return replay
    - If row exists with same hash but pending (no response): wait briefly
      for the first caller to finalize and replay that response

    Args:
        scope: Scope identifier (e.g., "http:POST:/loops/capture")
        idempotency_key: Unique key provided by client
        request_hash: Canonical hash of request payload
        expires_at: ISO8601 expiry timestamp
        conn: SQLite connection to core database

    Returns:
        Dict with keys:
        - is_new: True if this is a new claim, False if replay
        - replay: Dict with status_code and response_body if replay, else None

    Raises:
        IdempotencyConflictError: If same key exists with different hash
            or if an in-progress claim does not finalize before timeout
    """
    from .idempotency import IdempotencyConflictError

    purge_expired_idempotency_keys(conn=conn)

    try:
        conn.execute(
            """
            INSERT INTO idempotency_keys
                (scope, idempotency_key, request_hash, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (scope, idempotency_key, request_hash, expires_at),
        )
        conn.commit()
        return {"is_new": True, "replay": None}
    except sqlite3.IntegrityError:
        conn.rollback()

    deadline = time.monotonic() + _IDEMPOTENCY_PENDING_WAIT_SECONDS
    while True:
        row = _read_idempotency_row(
            scope=scope,
            idempotency_key=idempotency_key,
            conn=conn,
        )
        if row is None:
            try:
                conn.execute(
                    """
                    INSERT INTO idempotency_keys
                        (scope, idempotency_key, request_hash, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (scope, idempotency_key, request_hash, expires_at),
                )
                conn.commit()
                return {"is_new": True, "replay": None}
            except sqlite3.IntegrityError:
                conn.rollback()
                continue

        stored_hash = row["request_hash"]
        response_status = row["response_status"]
        response_body_json = row["response_body_json"]
        is_expired = bool(row["is_expired"])

        if is_expired:
            if _try_claim_expired_idempotency_key(
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expires_at=expires_at,
                conn=conn,
            ):
                return {"is_new": True, "replay": None}
            continue

        if stored_hash != request_hash:
            raise IdempotencyConflictError(
                "Idempotency key conflict: "
                f"key '{idempotency_key}' already used with different payload"
            )

        if response_status is not None and response_body_json is not None:
            conn.execute(
                """
                UPDATE idempotency_keys
                SET last_seen_at = CURRENT_TIMESTAMP
                WHERE scope = ? AND idempotency_key = ?
                """,
                (scope, idempotency_key),
            )
            conn.commit()
            return {
                "is_new": False,
                "replay": {
                    "status_code": response_status,
                    "response_body": json.loads(response_body_json),
                },
            }

        if time.monotonic() >= deadline:
            raise IdempotencyConflictError(
                f"Idempotency key '{idempotency_key}' is currently in progress; retry shortly"
            )
        time.sleep(_IDEMPOTENCY_PENDING_POLL_SECONDS)


def finalize_idempotency_response(
    *,
    scope: str,
    idempotency_key: str,
    response_status: int,
    response_body: Mapping[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Store the response for an idempotent request.

    Args:
        scope: Scope identifier
        idempotency_key: Unique key provided by client
        response_status: HTTP status code
        response_body: Response body dictionary
        conn: SQLite connection to core database
    """
    conn.execute(
        """
        UPDATE idempotency_keys
        SET response_status = ?,
            response_body_json = ?,
            last_seen_at = CURRENT_TIMESTAMP
        WHERE scope = ? AND idempotency_key = ?
        """,
        (response_status, json.dumps(response_body), scope, idempotency_key),
    )
    conn.commit()
