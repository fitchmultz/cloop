"""Text embedding generation via litellm.

Purpose:
    Generate vector embeddings for text chunks using configurable LLM providers.

Responsibilities:
    - Call litellm.embedding() with provider-specific kwargs
    - Return numpy arrays for vector similarity operations

Non-scope:
    - Document chunking (see rag/chunking.py)
    - Vector storage (see db.py)

Entrypoint:
    - embed_texts(texts, settings) -> List[np.ndarray]
"""

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
    for idx, item in enumerate(cast(Iterable[Dict[str, Any]], data)):
        embedding_values = item.get("embedding")
        if not isinstance(embedding_values, list):
            actual_type = type(embedding_values).__name__
            raise ValueError(
                f"invalid_embedding_format: item {idx} has embedding of type "
                f"{actual_type}, expected list"
            )
        vectors.append(np.array(embedding_values, dtype=np.float32))
    return vectors
