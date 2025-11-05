import os
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from . import typingx


class VectorSearchMode(StrEnum):
    PYTHON = "python"
    SQLITE = "sqlite"
    AUTO = "auto"


class ToolMode(StrEnum):
    MANUAL = "manual"
    LLM = "llm"
    NONE = "none"


class EmbedStorageMode(StrEnum):
    JSON = "json"
    BLOB = "blob"
    DUAL = "dual"


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
    vector_search_mode: VectorSearchMode
    tool_mode_default: ToolMode
    embed_storage_mode: EmbedStorageMode
    openai_api_base: str | None
    openai_api_key: str | None
    ollama_api_base: str | None
    lmstudio_api_base: str | None
    openrouter_api_base: str | None
    stream_default: bool


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

    settings = Settings(
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
        vector_search_mode=_resolve_vector_mode(os.getenv("CLOOP_VECTOR_MODE")),
        tool_mode_default=_resolve_tool_mode(os.getenv("CLOOP_TOOL_MODE")),
        embed_storage_mode=_resolve_embed_storage(os.getenv("CLOOP_EMBED_STORAGE")),
        openai_api_base=os.getenv("CLOOP_OPENAI_API_BASE"),
        openai_api_key=os.getenv("CLOOP_OPENAI_API_KEY"),
        ollama_api_base=os.getenv("CLOOP_OLLAMA_API_BASE"),
        lmstudio_api_base=os.getenv("CLOOP_LMSTUDIO_API_BASE"),
        openrouter_api_base=os.getenv("CLOOP_OPENROUTER_API_BASE"),
        stream_default=_resolve_stream_default(os.getenv("CLOOP_STREAM_DEFAULT")),
    )
    return _validate_settings(settings)


def _resolve_vector_mode(raw: str | None) -> VectorSearchMode:
    value = (raw or VectorSearchMode.PYTHON.value).strip().lower()
    try:
        return VectorSearchMode(value)
    except ValueError as exc:
        raise ValueError(f"Invalid CLOOP_VECTOR_MODE: {raw}") from exc


def _resolve_tool_mode(raw: str | None) -> ToolMode:
    value = (raw or ToolMode.MANUAL.value).strip().lower()
    try:
        return ToolMode(value)
    except ValueError as exc:
        raise ValueError(f"Invalid CLOOP_TOOL_MODE: {raw}") from exc


def _resolve_embed_storage(raw: str | None) -> EmbedStorageMode:
    value = (raw or EmbedStorageMode.DUAL.value).strip().lower()
    typed_value = typingx.as_type(str, value)
    try:
        return EmbedStorageMode(typed_value)
    except ValueError as exc:
        raise ValueError(f"Invalid CLOOP_EMBED_STORAGE: {raw}") from exc


def _resolve_stream_default(raw: str | None) -> bool:
    if raw is None:
        return False
    normalized = raw.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _validate_settings(settings: Settings) -> Settings:
    if (
        settings.vector_search_mode is VectorSearchMode.SQLITE
        and settings.embed_storage_mode is EmbedStorageMode.BLOB
    ):
        raise ValueError("CLOOP_VECTOR_MODE=sqlite requires CLOOP_EMBED_STORAGE of json or dual")
    if settings.tool_mode_default is ToolMode.LLM and settings.stream_default:
        raise ValueError("Streaming default cannot be enabled when default tool mode is llm")
    return settings
