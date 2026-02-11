"""
Shared utilities for RAG operations.

Responsibilities:
- Scope filtering and parsing
- Embedding dimension and model validation

Non-scope:
- Search logic (see search.py)
- Document CRUD (see documents.py)
"""

import json
import logging
from typing import Any, Dict, List

from ..db import rag_connection
from ..loops.errors import ValidationError
from ..settings import Settings
from ..typingx import escape_like_pattern

logger = logging.getLogger(__name__)


def _filter_rows_by_scope(rows: List[Dict[str, Any]], scope: str) -> List[Dict[str, Any]]:
    if not scope:
        return rows
    scope = scope.strip()
    if scope.startswith("doc:"):
        doc_id = _parse_doc_scope(scope)
        return [row for row in rows if int(row.get("doc_id") or 0) == doc_id]
    return [row for row in rows if scope in str(row.get("document_path", ""))]


def _assert_embedding_dimension_consistency(
    *, settings: Settings, expected_dim: int, scope: str | None
) -> None:
    with rag_connection(settings) as conn:
        if scope and scope.startswith("doc:"):
            doc_id = _parse_doc_scope(scope)
            rows = conn.execute(
                "SELECT DISTINCT embedding_dim FROM chunks WHERE doc_id = ?",
                (doc_id,),
            ).fetchall()
        elif scope:
            escaped_scope = escape_like_pattern(scope)
            rows = conn.execute(
                "SELECT DISTINCT embedding_dim FROM chunks WHERE document_path LIKE ? ESCAPE '\\'",
                (f"%{escaped_scope}%",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT DISTINCT embedding_dim FROM chunks").fetchall()
    dims = {int(row[0]) for row in rows}
    if not dims:
        return
    if len(dims) != 1 or expected_dim not in dims:
        raise RuntimeError(
            f"embedding_dim mismatch: query={expected_dim}, db={sorted(dims)}; "
            "re-ingest with the current embed model"
        )


def _assert_embedding_model_alignment(*, settings: Settings) -> None:
    with rag_connection(settings) as conn:
        row = conn.execute("SELECT metadata FROM chunks LIMIT 1").fetchone()
    if not row:
        return
    try:
        metadata = json.loads(row["metadata"] or "{}")
    except json.JSONDecodeError:
        logger.debug("Chunk metadata is not valid JSON, skipping model alignment check")
        return
    except (TypeError, KeyError) as e:
        logger.warning("Unexpected error parsing chunk metadata: %s", e)
        return
    stored = metadata.get("embed_model")
    if stored and stored != settings.embed_model:
        raise RuntimeError(
            f"Stored embed_model={stored} != configured={settings.embed_model}; re-ingest required"
        )


def _parse_doc_scope(scope: str) -> int:
    """Parse 'doc:ID' format scope and return the integer ID.

    Raises:
        ValidationError: If scope starts with 'doc:' but ID is not a valid integer.
    """
    if not scope.startswith("doc:"):
        raise ValidationError("scope", "doc scope must start with 'doc:'")
    id_part = scope.split(":", 1)[1]
    if not id_part:
        raise ValidationError("scope", "doc:ID requires integer ID after colon")
    try:
        return int(id_part)
    except ValueError:
        raise ValidationError("scope", f"doc:ID requires integer ID, got: {id_part}") from None
