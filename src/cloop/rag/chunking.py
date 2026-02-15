"""Text chunking operations for RAG documents.

Purpose:
    Split text into token-based chunks for embedding and retrieval.

Responsibilities:
    - Tokenize text using whitespace splitting
    - Create fixed-size overlapping chunks

Non-scope:
    - Document loading (see loaders.py)
    - Embedding generation (see embeddings.py)

Entrypoint:
    - chunk_text(text, chunk_size) -> List[str]
"""

import re
from typing import List


def chunk_text(text: str, *, chunk_size: int) -> List[str]:
    tokens = re.split(r"\s+", text.strip())
    if not tokens:
        return []
    chunks = []
    for idx in range(0, len(tokens), chunk_size):
        chunk_tokens = tokens[idx : idx + chunk_size]
        chunks.append(" ".join(chunk_tokens))
    return chunks
