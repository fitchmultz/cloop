"""
Text chunking operations.

Responsibilities:
- Split text into token-based chunks for embedding

Non-scope:
- Document loading (see loaders.py)
- Embedding generation (see embeddings.py)
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
