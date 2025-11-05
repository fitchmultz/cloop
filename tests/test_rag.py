import math
import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, List

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cloop import db
from cloop.db import VectorBackend
from cloop.rag import chunk_text, ingest_paths, retrieve_similar_chunks
from cloop.settings import Settings, VectorSearchMode, get_settings

token_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=1,
    max_size=10,
)


@given(st.lists(token_strategy, min_size=1, max_size=40))
def test_chunk_text_preserves_token_order(tokens: List[str]) -> None:
    text = " ".join(tokens)
    chunks = chunk_text(text, chunk_size=5)
    regenerated = []
    for chunk in chunks:
        regenerated.extend(chunk.split())
    assert regenerated == tokens


def make_settings(tmp_path: Path, *, vector_mode: VectorSearchMode) -> Settings:
    os.environ["CLOOP_DATA_DIR"] = str(tmp_path)
    os.environ["CLOOP_VECTOR_MODE"] = vector_mode.value
    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    db.init_databases(settings)
    return settings


def test_sqlite_vector_mode_matches_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_sqlite = make_settings(tmp_path, vector_mode=VectorSearchMode.SQLITE)

    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")

    def fake_embed_texts(
        chunks: List[str], *, settings: Settings | None = None
    ) -> List[np.ndarray]:
        return [np.ones(4, dtype=np.float32) * (idx + 1) for idx, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed_texts)
    doc = tmp_path / "doc.txt"
    doc.write_text("alpha beta gamma delta epsilon zeta", encoding="utf-8")
    ingest_paths([str(doc)], settings=settings_sqlite)

    sqlite_results = retrieve_similar_chunks("alpha question", top_k=3, settings=settings_sqlite)
    python_settings = replace(settings_sqlite, vector_search_mode=VectorSearchMode.PYTHON)
    python_results = retrieve_similar_chunks("alpha question", top_k=3, settings=python_settings)

    assert [row["id"] for row in sqlite_results] == [row["id"] for row in python_results]
    assert all(
        math.isclose(row_sql["score"], row_py["score"], rel_tol=1e-5)
        for row_sql, row_py in zip(sqlite_results, python_results, strict=True)
    )


def _count_rows(table: str, *, settings: Settings) -> int:
    with db.rag_connection(settings) as conn:
        value = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return int(value)


def test_ingest_skips_unchanged_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "note.txt"
    doc.write_text("alpha beta gamma", encoding="utf-8")

    first = ingest_paths([str(doc)], settings=settings)
    assert first == {"files": 1, "chunks": 1}
    assert _count_rows("chunks", settings=settings) == 1
    assert _count_rows("documents", settings=settings) == 1

    second = ingest_paths([str(doc)], settings=settings)
    assert second == {"files": 0, "chunks": 0}
    assert _count_rows("chunks", settings=settings) == 1
    assert _count_rows("documents", settings=settings) == 1


def test_reindex_forces_reingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)
    calls: List[List[str]] = []

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        calls.append(chunks)
        return [np.ones(3, dtype=np.float32) * (idx + 1) for idx, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "doc.txt"
    doc.write_text("one two three four", encoding="utf-8")

    first = ingest_paths([str(doc)], settings=settings)
    assert first == {"files": 1, "chunks": 1}
    assert len(calls) == 1

    second = ingest_paths([str(doc)], mode="reindex", settings=settings)
    assert second == {"files": 1, "chunks": 1}
    assert len(calls) == 2
    assert _count_rows("chunks", settings=settings) == 1


def test_purge_removes_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "old.txt"
    doc.write_text("obsolete", encoding="utf-8")

    ingest_paths([str(doc)], settings=settings)
    assert _count_rows("documents", settings=settings) == 1

    result = ingest_paths([str(doc)], mode="purge", settings=settings)
    assert result == {"files": 1, "chunks": 1}
    assert _count_rows("documents", settings=settings) == 0
    assert _count_rows("chunks", settings=settings) == 0


def test_sync_purges_missing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    directory = tmp_path / "docs"
    directory.mkdir()
    keep = directory / "keep.txt"
    remove = directory / "remove.txt"
    keep.write_text("persist", encoding="utf-8")
    remove.write_text("temporary", encoding="utf-8")

    ingest_paths([str(directory)], settings=settings)
    assert _count_rows("documents", settings=settings) == 2

    remove.unlink()

    sync_result = ingest_paths([str(directory)], mode="sync", settings=settings)
    assert sync_result == {"files": 1, "chunks": 1}
    assert _count_rows("documents", settings=settings) == 1
    assert _count_rows("chunks", settings=settings) == 1


def test_embeddings_dual_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    vector = np.array([1.0, 2.0, 2.0], dtype=np.float32)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [vector for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "blob.txt"
    doc.write_text("blob storage", encoding="utf-8")

    result = ingest_paths([str(doc)], settings=settings)
    assert result == {"files": 1, "chunks": 1}

    with db.rag_connection(settings) as conn:
        row = conn.execute(
            "SELECT embedding, embedding_blob, embedding_norm FROM chunks"
        ).fetchone()
    assert row is not None
    assert row["embedding_blob"] is not None
    assert len(row["embedding_blob"]) == vector.size * 4
    assert math.isclose(float(row["embedding_norm"]), float(np.linalg.norm(vector)), rel_tol=1e-6)
    assert row["embedding"]


def test_retrieve_prefers_blob_over_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    vector = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [vector for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "dual.txt"
    doc.write_text("dual write", encoding="utf-8")

    ingest_paths([str(doc)], settings=settings)

    with db.rag_connection(settings) as conn:
        conn.execute("UPDATE chunks SET embedding = '[]'")
        conn.commit()

    results = retrieve_similar_chunks("any query", top_k=1, settings=settings)
    assert results
    assert math.isclose(results[0]["score"], 1.0, rel_tol=1e-6)


def test_retrieve_scope_filters_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) * (idx + 1) for idx, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc_keep = tmp_path / "keep.txt"
    doc_skip = tmp_path / "skip.txt"
    doc_keep.write_text("keep scope", encoding="utf-8")
    doc_skip.write_text("skip scope", encoding="utf-8")

    ingest_paths([str(doc_keep), str(doc_skip)], settings=settings)

    scoped = retrieve_similar_chunks("scope", top_k=5, scope="keep.txt", settings=settings)
    assert scoped
    assert all("keep.txt" in row["document_path"] for row in scoped)


def test_retrieve_scope_filters_doc_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc_a = tmp_path / "doc_a.txt"
    doc_b = tmp_path / "doc_b.txt"
    doc_a.write_text("alpha", encoding="utf-8")
    doc_b.write_text("beta", encoding="utf-8")

    ingest_paths([str(doc_a), str(doc_b)], settings=settings)

    with db.rag_connection(settings) as conn:
        row = conn.execute(
            "SELECT id FROM documents WHERE document_path = ?",
            (str(doc_b),),
        ).fetchone()
    assert row is not None
    doc_id = row["id"]

    scoped = retrieve_similar_chunks("beta", top_k=5, scope=f"doc:{doc_id}", settings=settings)
    assert scoped
    assert all(row["document_path"] == str(doc_b) for row in scoped)


def test_vec_backend_hooks_are_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.AUTO)

    vector = np.array([0.25, 0.75], dtype=np.float32)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [vector for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)
    monkeypatch.setattr("cloop.rag.get_vector_backend", lambda: VectorBackend.VEC)

    ensure_calls: List[int] = []
    upsert_calls: List[int] = []
    delete_calls: List[List[int]] = []

    def fake_ensure(conn: sqlite3.Connection, dim: int, backend: VectorBackend) -> None:
        ensure_calls.append(dim)

    def fake_upsert(
        conn: sqlite3.Connection, chunk_id: int, vec: np.ndarray, backend: VectorBackend
    ) -> None:
        upsert_calls.append(chunk_id)

    def fake_delete(conn: sqlite3.Connection, chunk_ids: List[int], backend: VectorBackend) -> None:
        delete_calls.append(chunk_ids)

    def fake_search(
        conn: sqlite3.Connection,
        query: np.ndarray,
        top_k: int,
        backend: VectorBackend,
    ) -> List[dict[str, Any]]:
        row = conn.execute("SELECT * FROM chunks LIMIT 1").fetchone()
        assert row is not None
        chunk = dict(row)
        chunk["score"] = 0.99
        return [chunk]

    monkeypatch.setattr("cloop.rag.ensure_vector_index", fake_ensure)
    monkeypatch.setattr("cloop.rag.upsert_vector", fake_upsert)
    monkeypatch.setattr("cloop.rag.delete_vector_rows", fake_delete)
    monkeypatch.setattr("cloop.rag.vec_backend_search", fake_search)

    doc = tmp_path / "vec.txt"
    doc.write_text("vector enabled", encoding="utf-8")

    ingest_paths([str(doc)], settings=settings)

    assert ensure_calls == [vector.size]
    assert upsert_calls  # at least one chunk stored

    results = retrieve_similar_chunks("integration query", top_k=1, settings=settings)
    assert results and math.isclose(results[0]["score"], 0.99, rel_tol=1e-6)
