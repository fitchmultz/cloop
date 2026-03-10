"""Shared RAG ask orchestration tests.

Purpose:
    Verify the shared retrieval-plus-answer flow used by HTTP and CLI RAG ask
    entrypoints.

Responsibilities:
    - Test no-knowledge fallback behavior
    - Test answer generation against ingested content
    - Test chunk sanitization and source shaping

Non-scope:
    - HTTP transport behavior
    - CLI argument parsing
    - Streaming SSE behavior

Invariants/Assumptions:
    - Tests run against isolated temporary databases
    - Mock LLM responses return `mock-response`
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cloop import db
from cloop.rag import NO_KNOWLEDGE_MESSAGE, answer_question, ingest_paths, prepare_ask_context
from cloop.settings import Settings, get_settings


def _setup_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _mock_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_embed(chunks: list[str], *, settings: Settings | None = None) -> list[np.ndarray]:
        return [np.ones(3, dtype=np.float32) * (index + 1) for index, _ in enumerate(chunks)]

    monkeypatch.setattr("cloop.rag.embed_texts", fake_embed)
    monkeypatch.setattr("cloop.rag.search.embed_texts", fake_embed)


def _mock_answer_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat_completion(
        messages: list[dict[str, str]], *, settings: Settings
    ) -> tuple[str, dict[str, float | str]]:
        return "mock-response", {"model": settings.llm_model, "latency_ms": 8.0}

    monkeypatch.setattr("cloop.rag.ask_orchestration.chat_completion", fake_chat_completion)


def test_answer_question_without_knowledge_returns_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ingested content should produce the shared no-knowledge fallback."""
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    result = answer_question(
        question="What do I know?",
        top_k=5,
        scope=None,
        settings=settings,
    )

    assert result.answer == NO_KNOWLEDGE_MESSAGE
    assert result.chunks == []
    assert result.sources == []
    assert result.model is None


def test_prepare_ask_context_sanitizes_chunks_and_formats_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepared ask context should not leak embeddings and should expose sources."""
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)

    doc = tmp_path / "doc.txt"
    doc.write_text("FastAPI is a modern web framework.", encoding="utf-8")
    ingest_paths([str(doc)], settings=settings)

    prepared = prepare_ask_context(
        question="web framework",
        top_k=5,
        scope=None,
        settings=settings,
    )

    assert prepared.has_knowledge is True
    assert prepared.chunks
    assert prepared.sources
    assert prepared.token_estimate > 0
    for chunk in prepared.chunks:
        assert "embedding_blob" not in chunk
    for source in prepared.sources:
        assert "document_path" in source
        assert "chunk_index" in source


def test_answer_question_returns_shared_answer_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shared non-streaming ask flow should return answer, sources, and model metadata."""
    settings = _setup_settings(tmp_path, monkeypatch)
    _mock_embeddings(monkeypatch)
    _mock_answer_generation(monkeypatch)

    doc = tmp_path / "faq.txt"
    doc.write_text("FastAPI helps build APIs quickly.", encoding="utf-8")
    ingest_paths([str(doc)], settings=settings)

    result = answer_question(
        question="What does FastAPI help build?",
        top_k=5,
        scope=None,
        settings=settings,
    )

    assert result.answer == "mock-response"
    assert result.model == "mock-llm"
    assert result.chunks
    assert result.sources
