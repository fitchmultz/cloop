"""Canonical RAG database bootstrap schema.

Purpose:
    Hold the bootstrap SQL for the retrieval-augmented generation database
    used for documents and chunks.

Responsibilities:
    - Define the fresh-install RAG schema in one canonical SQL script
    - Keep document/chunk table declarations version-aligned with the RAG schema version
    - Avoid duplicating bootstrap SQL across runtime modules

Non-scope:
    - Core database tables or incremental core migrations
    - SQL execution, connection management, or embedding logic

Scope:
    - Static RAG bootstrap SQL only
    - No runtime orchestration or stateful behavior

Usage:
    Imported by `cloop.db` when initializing a fresh RAG database.

Invariants/Assumptions:
    - The bootstrap schema matches `RAG_SCHEMA_VERSION`
    - Fresh installs should not require replaying migrations
"""

# ruff: noqa: E501

from __future__ import annotations

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

__all__ = ["_RAG_SCHEMA"]
