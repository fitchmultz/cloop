from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, cast

import litellm
import numpy as np

from .providers import resolve_provider_kwargs
from .settings import Settings, get_settings


def embed_texts(
    texts: Sequence[str],
    *,
    settings: Settings | None = None,
) -> List[np.ndarray]:
    if not texts:
        return []
    settings = settings or get_settings()
    provider_kwargs = resolve_provider_kwargs(settings.embed_model, settings)
    response = cast(
        Dict[str, Any],
        litellm.embedding(
            model=settings.embed_model,
            input=list(texts),
            timeout=int(settings.embedding_timeout),
            **provider_kwargs,
        ),
    )
    vectors: List[np.ndarray] = []
    data = response.get("data", [])
    for item in cast(Iterable[Dict[str, Any]], data):
        embedding_values = item.get("embedding")
        if isinstance(embedding_values, list):
            vectors.append(np.array(embedding_values, dtype=np.float32))
    return vectors


def cosine_similarities(
    query: np.ndarray,
    embeddings: Iterable[np.ndarray],
) -> np.ndarray:
    vectors = list(embeddings)
    if not vectors:
        return np.array([])
    matrix = np.stack(vectors)
    query_norm = query / (np.linalg.norm(query) + 1e-12)
    matrix_norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12
    normalized = matrix / matrix_norms
    return normalized @ query_norm
