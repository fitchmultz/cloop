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

import cloop.rag
from cloop import db
from cloop.db import VectorBackend
from cloop.loops.errors import ValidationError
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
    get_settings.cache_clear()
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
    assert first == {"files": 1, "chunks": 1, "failed_files": []}
    assert _count_rows("chunks", settings=settings) == 1
    assert _count_rows("documents", settings=settings) == 1

    second = ingest_paths([str(doc)], settings=settings)
    assert second == {"files": 0, "chunks": 0, "failed_files": []}
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
    assert first == {"files": 1, "chunks": 1, "failed_files": []}
    assert len(calls) == 1

    second = ingest_paths([str(doc)], mode="reindex", settings=settings)
    assert second == {"files": 1, "chunks": 1, "failed_files": []}
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
    assert result == {"files": 1, "chunks": 1, "failed_files": []}
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
    assert sync_result == {"files": 1, "chunks": 1, "failed_files": []}
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
    assert result == {"files": 1, "chunks": 1, "failed_files": []}

    with db.rag_connection(settings) as conn:
        row = conn.execute(
            "SELECT embedding, embedding_blob, embedding_norm FROM chunks"
        ).fetchone()
    assert row is not None
    assert row["embedding_blob"] is not None
    assert len(row["embedding_blob"]) == vector.size * 4
    assert math.isclose(float(row["embedding_norm"]), float(np.linalg.norm(vector)), rel_tol=1e-6)
    assert row["embedding"]


def test_embedding_norm_persisted_for_json_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOOP_EMBED_STORAGE", "json")
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    vector = np.array([3.0, 4.0, 0.0], dtype=np.float32)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [vector for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "json.txt"
    doc.write_text("json storage", encoding="utf-8")

    result = ingest_paths([str(doc)], settings=settings)
    assert result == {"files": 1, "chunks": 1, "failed_files": []}

    with db.rag_connection(settings) as conn:
        row = conn.execute("SELECT embedding_blob, embedding_norm FROM chunks").fetchone()
    assert row is not None
    assert row["embedding_blob"] is None
    assert math.isclose(float(row["embedding_norm"]), float(np.linalg.norm(vector)), rel_tol=1e-6)


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


def test_retrieve_raises_on_embedding_dimension_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    vector = np.ones(3, dtype=np.float32)

    def ingest_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [vector for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", ingest_embed)

    doc = tmp_path / "drift.txt"
    doc.write_text("drift guard", encoding="utf-8")

    ingest_paths([str(doc)], settings=settings)

    with db.rag_connection(settings) as conn:
        conn.execute("UPDATE chunks SET embedding_dim = ?", (vector.size + 1,))
        conn.commit()

    def query_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [vector]

    monkeypatch.setattr("cloop.rag.embed_texts", query_embed)

    with pytest.raises(RuntimeError) as excinfo:
        retrieve_similar_chunks("guard", top_k=1, settings=settings)
    assert "embedding_dim mismatch" in str(excinfo.value)


def test_retrieve_raises_on_embedding_model_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    vector = np.ones(2, dtype=np.float32)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [vector for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "model.txt"
    doc.write_text("model guard", encoding="utf-8")

    ingest_paths([str(doc)], settings=settings)

    alternate = replace(settings, embed_model="new-model")

    with pytest.raises(RuntimeError) as excinfo:
        retrieve_similar_chunks("guard", top_k=1, settings=alternate)
    assert "Stored embed_model" in str(excinfo.value)


def test_alignment_check_handles_corrupted_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that corrupted metadata doesn't crash but logs appropriately."""
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    vector = np.ones(2, dtype=np.float32)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [vector for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "corrupt.txt"
    doc.write_text("test content", encoding="utf-8")

    ingest_paths([str(doc)], settings=settings)

    # Corrupt the metadata with invalid JSON
    with db.rag_connection(settings) as conn:
        conn.execute("UPDATE chunks SET metadata = ?", ("not valid json{",))
        conn.commit()

    # Should not raise, should silently skip alignment check
    results = retrieve_similar_chunks("test", top_k=1, settings=settings)
    # Results should still work, just without alignment check
    assert results is not None


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


def test_ingest_rejects_oversized_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that files exceeding max_file_size_mb are rejected."""
    # Set a small max file size for testing (1 MB)
    monkeypatch.setenv("CLOOP_MAX_FILE_SIZE_MB", "1")
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    # Create a file slightly over the limit (1.1 MB)
    oversized_file = tmp_path / "oversized.txt"
    oversized_file.write_text("x" * (1_100_000), encoding="utf-8")

    # Attempt to ingest - should raise ValueError
    with pytest.raises(ValueError) as excinfo:
        ingest_paths([str(oversized_file)], settings=settings)

    assert "File too large" in str(excinfo.value)
    assert "oversized.txt" in str(excinfo.value)
    assert "1 MB" in str(excinfo.value)  # Should mention the limit


def test_ingest_accepts_files_under_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that files under max_file_size_mb are accepted."""
    # Set a 5 MB limit
    monkeypatch.setenv("CLOOP_MAX_FILE_SIZE_MB", "5")
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    # Create a file well under the limit (100 KB)
    small_file = tmp_path / "small.txt"
    small_file.write_text("x" * 100_000, encoding="utf-8")

    # Should succeed without error
    result = ingest_paths([str(small_file)], settings=settings)
    assert result == {"files": 1, "chunks": 1, "failed_files": []}


def test_ingest_file_at_exact_limit_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that files exactly at max_file_size_mb are accepted (boundary test)."""
    # Set a 1 MB limit
    monkeypatch.setenv("CLOOP_MAX_FILE_SIZE_MB", "1")
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    # Create a file exactly at the limit (1 MB = 1,048,576 bytes)
    exact_file = tmp_path / "exact.txt"
    exact_file.write_text("x" * 1_048_576, encoding="utf-8")

    # Should succeed without error (limit is > not >=)
    result = ingest_paths([str(exact_file)], settings=settings)
    assert result == {"files": 1, "chunks": 1, "failed_files": []}


def test_ingest_zero_byte_files_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that zero-byte files are allowed through the size check."""
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    # Create an empty file
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("", encoding="utf-8")

    # Should succeed - empty files pass size check and are processed
    # (chunk_text produces one empty chunk for empty content)
    result = ingest_paths([str(empty_file)], settings=settings)
    assert result == {"files": 1, "chunks": 1, "failed_files": []}


def test_retrieve_raises_on_invalid_doc_scope_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed doc: scope should raise ValidationError, not return empty."""
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "test.txt"
    doc.write_text("test content", encoding="utf-8")

    ingest_paths([str(doc)], settings=settings)

    with pytest.raises(ValidationError) as excinfo:
        retrieve_similar_chunks("test", top_k=5, scope="doc:notanumber", settings=settings)
    assert "scope" in str(excinfo.value)
    assert "integer" in str(excinfo.value).lower()


def test_retrieve_valid_doc_scope_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid doc:ID scope should work correctly."""
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

    chunks = retrieve_similar_chunks("beta", top_k=5, scope=f"doc:{doc_id}", settings=settings)
    assert len(chunks) > 0


def test_retrieve_raises_on_empty_doc_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty doc: scope should raise ValidationError."""
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    doc = tmp_path / "test.txt"
    doc.write_text("test content", encoding="utf-8")

    ingest_paths([str(doc)], settings=settings)

    with pytest.raises(ValidationError) as excinfo:
        retrieve_similar_chunks("test", top_k=5, scope="doc:", settings=settings)
    assert "scope" in str(excinfo.value)


def test_ensure_vector_index_logs_warning_on_sqlite_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that a warning is logged when vector index creation fails."""
    import logging
    from unittest.mock import MagicMock

    caplog.set_level(logging.WARNING)

    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.AUTO)
    db.init_databases(settings)

    fake_conn = MagicMock()
    fake_conn.execute.side_effect = sqlite3.Error("simulated index creation failure")

    from cloop.rag import ensure_vector_index

    ensure_vector_index(fake_conn, dim=128, backend=VectorBackend.VEC)

    assert any(
        "Failed to create vec_chunks index" in record.message
        and "simulated index creation failure" in record.message
        for record in caplog.records
        if record.levelno == logging.WARNING
    )


def test_ingest_reports_failed_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that files that fail to load are reported in failed_files."""
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("valid content", encoding="utf-8")

    failing_file = tmp_path / "failing.txt"
    failing_file.write_text("this will fail", encoding="utf-8")

    valid_file2 = tmp_path / "valid2.txt"
    valid_file2.write_text("more content", encoding="utf-8")

    original_load = cloop.rag.load_document

    def mock_load_document(path: Path) -> str:
        if path.name == "failing.txt":
            raise ValueError("Simulated PDF parse error")
        return original_load(path)

    monkeypatch.setattr("cloop.rag.load_document", mock_load_document)

    result = ingest_paths(
        [str(valid_file), str(failing_file), str(valid_file2)],
        settings=settings,
    )

    assert result["files"] == 2
    assert result["chunks"] == 2
    assert len(result["failed_files"]) == 1
    assert result["failed_files"][0]["path"] == str(failing_file)
    assert "Simulated PDF parse error" in result["failed_files"][0]["error"]


def test_ingest_reports_multiple_failed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that multiple file failures are all reported in failed_files."""
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    def fake_embed(chunks: List[str], *, settings: Settings | None = None) -> List[np.ndarray]:
        return [np.ones(3, dtype=np.float32) for _ in chunks]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)

    valid_file = tmp_path / "valid.txt"
    valid_file.write_text("valid content", encoding="utf-8")

    failing_file1 = tmp_path / "failing1.txt"
    failing_file1.write_text("this will fail", encoding="utf-8")

    failing_file2 = tmp_path / "failing2.txt"
    failing_file2.write_text("this will also fail", encoding="utf-8")

    failing_pdf = tmp_path / "failing.pdf"
    failing_pdf.write_text("fake pdf content", encoding="utf-8")

    original_load = cloop.rag.load_document

    def mock_load_document(path: Path) -> str:
        if path.name in ("failing1.txt", "failing2.txt"):
            raise ValueError(f"Error in {path.name}")
        if path.name == "failing.pdf":
            raise PermissionError("Permission denied")
        return original_load(path)

    monkeypatch.setattr("cloop.rag.load_document", mock_load_document)

    result = ingest_paths(
        [str(valid_file), str(failing_file1), str(failing_file2), str(failing_pdf)],
        settings=settings,
    )

    assert result["files"] == 1
    assert result["chunks"] == 1
    assert len(result["failed_files"]) == 3

    failed_paths = {f["path"] for f in result["failed_files"]}
    assert str(failing_file1) in failed_paths
    assert str(failing_file2) in failed_paths
    assert str(failing_pdf) in failed_paths

    # Check error types are included in messages
    error_messages = " ".join(f["error"] for f in result["failed_files"])
    assert "ValueError:" in error_messages
    assert "PermissionError:" in error_messages


def test_ingest_reports_all_files_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that complete batch failure is properly reported."""
    settings = make_settings(tmp_path, vector_mode=VectorSearchMode.PYTHON)

    failing_file1 = tmp_path / "failing1.txt"
    failing_file1.write_text("content 1", encoding="utf-8")

    failing_file2 = tmp_path / "failing2.txt"
    failing_file2.write_text("content 2", encoding="utf-8")

    def mock_load_document(path: Path) -> str:
        raise OSError(f"Cannot read file: {path.name}")

    monkeypatch.setattr("cloop.rag.load_document", mock_load_document)

    result = ingest_paths(
        [str(failing_file1), str(failing_file2)],
        settings=settings,
    )

    assert result["files"] == 0
    assert result["chunks"] == 0
    assert len(result["failed_files"]) == 2

    failed_paths = {f["path"] for f in result["failed_files"]}
    assert str(failing_file1) in failed_paths
    assert str(failing_file2) in failed_paths

    for failed in result["failed_files"]:
        assert "OSError:" in failed["error"]
