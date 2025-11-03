from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    core_db_path: Path
    rag_db_path: Path
    llm_model: str
    embed_model: str
    default_top_k: int
    chunk_size: int
    llm_timeout: float
    ingest_timeout: float
    embedding_timeout: float
    sqlite_vector_extension: str | None


def _resolve_path(value: str | None, default: Path, *, create_parent: bool = True) -> Path:
    path = Path(value).expanduser().resolve() if value else default.resolve()
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    root_dir = Path(os.getenv("CLOOP_ROOT_DIR", Path.cwd())).resolve()
    default_data_dir = Path(os.getenv("CLOOP_DATA_DIR", root_dir / "data")).resolve()
    default_data_dir.mkdir(parents=True, exist_ok=True)

    core_db_path = _resolve_path(os.getenv("CLOOP_CORE_DB_PATH"), default_data_dir / "core.db")
    rag_db_path = _resolve_path(os.getenv("CLOOP_RAG_DB_PATH"), default_data_dir / "rag.db")

    return Settings(
        root_dir=root_dir,
        core_db_path=core_db_path,
        rag_db_path=rag_db_path,
        llm_model=os.getenv("CLOOP_LLM_MODEL", "ollama/llama3"),
        embed_model=os.getenv("CLOOP_EMBED_MODEL", "ollama/nomic-embed-text"),
        default_top_k=int(os.getenv("CLOOP_DEFAULT_TOP_K", "5")),
        chunk_size=int(os.getenv("CLOOP_CHUNK_SIZE", "800")),
        llm_timeout=float(os.getenv("CLOOP_LLM_TIMEOUT", "30.0")),
        ingest_timeout=float(os.getenv("CLOOP_INGEST_TIMEOUT", "60.0")),
        embedding_timeout=float(os.getenv("CLOOP_EMBED_TIMEOUT", "30.0")),
        sqlite_vector_extension=os.getenv("CLOOP_SQLITE_VECTOR_EXTENSION"),
    )
