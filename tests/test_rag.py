from __future__ import annotations

import math
import os
from dataclasses import replace
from pathlib import Path
from typing import List

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from cloop import db
from cloop.rag import chunk_text, ingest_paths, retrieve_similar_chunks
from cloop.settings import Settings, get_settings

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


def make_settings(tmp_path: Path, *, vector_mode: str) -> Settings:
    os.environ["CLOOP_DATA_DIR"] = str(tmp_path)
    os.environ["CLOOP_VECTOR_MODE"] = vector_mode
    get_settings.cache_clear()  # type: ignore[attr-defined]
    settings = get_settings()
    db.init_databases(settings)
    return settings


def test_sqlite_vector_mode_matches_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_sqlite = make_settings(tmp_path, vector_mode="sqlite")

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
    python_settings = replace(settings_sqlite, vector_search_mode="python")
    python_results = retrieve_similar_chunks("alpha question", top_k=3, settings=python_settings)

    assert [row["id"] for row in sqlite_results] == [row["id"] for row in python_results]
    assert all(
        math.isclose(row_sql["score"], row_py["score"], rel_tol=1e-5)
        for row_sql, row_py in zip(sqlite_results, python_results, strict=True)
    )
