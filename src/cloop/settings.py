import os
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

_DOTENV_LOADED = False


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


@dataclass(frozen=True, slots=True)
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
    google_api_key: str | None
    ollama_api_base: str | None
    lmstudio_api_base: str | None
    openrouter_api_base: str | None
    stream_default: bool
    organizer_model: str
    organizer_timeout: float
    autopilot_enabled: bool
    autopilot_autoapply_min_confidence: float
    max_file_size_mb: int
    # Prioritization settings
    prioritization_due_window_hours: float
    prioritization_due_soon_hours: float
    prioritization_quick_win_minutes: int
    prioritization_high_leverage_threshold: float
    # Priority weights for scoring
    priority_weight_due: float
    priority_weight_urgency: float
    priority_weight_importance: float
    priority_weight_time_penalty: float
    priority_weight_activation_penalty: float
    # Related loop settings
    related_similarity_threshold: float
    related_max_candidates: int
    # Idempotency settings
    idempotency_ttl_seconds: int
    idempotency_max_key_length: int
    # Webhook settings
    webhook_max_retries: int
    webhook_retry_base_delay: float
    webhook_retry_max_delay: float
    webhook_timeout_seconds: float
    webhook_heartbeat_interval: float


def _resolve_path(value: str | None, default: Path, *, create_parent: bool = True) -> Path:
    path = Path(value).expanduser().resolve() if value else default.resolve()
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_dotenv(root_dir: Path) -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    dotenv_path = root_dir / ".env"
    if not dotenv_path.exists():
        return
    _DOTENV_LOADED = True
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if (value.startswith("'") and value.endswith("'")) or (
            value.startswith('"') and value.endswith('"')
        ):
            value = value[1:-1]
        os.environ[key] = value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv(Path.cwd())
    root_dir = Path(os.getenv("CLOOP_ROOT_DIR", Path.cwd())).resolve()
    if root_dir != Path.cwd():
        _load_dotenv(root_dir)
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
        google_api_key=os.getenv("CLOOP_GOOGLE_API_KEY") or os.getenv("LITELLM_API_KEY"),
        ollama_api_base=os.getenv("CLOOP_OLLAMA_API_BASE"),
        lmstudio_api_base=os.getenv("CLOOP_LMSTUDIO_API_BASE"),
        openrouter_api_base=os.getenv("CLOOP_OPENROUTER_API_BASE"),
        stream_default=_resolve_bool(os.getenv("CLOOP_STREAM_DEFAULT")),
        organizer_model=os.getenv("CLOOP_ORGANIZER_MODEL", "gemini/gemini-3-flash-preview"),
        organizer_timeout=float(os.getenv("CLOOP_ORGANIZER_TIMEOUT", "20.0")),
        autopilot_enabled=_resolve_bool(os.getenv("CLOOP_AUTOPILOT_ENABLED", "true")),
        autopilot_autoapply_min_confidence=float(
            os.getenv("CLOOP_AUTOPILOT_AUTOAPPLY_MIN_CONFIDENCE", "0.85")
        ),
        max_file_size_mb=int(os.getenv("CLOOP_MAX_FILE_SIZE_MB", "50")),
        prioritization_due_window_hours=float(
            os.getenv("CLOOP_PRIORITIZATION_DUE_WINDOW_HOURS", "72.0")
        ),
        prioritization_due_soon_hours=float(
            os.getenv("CLOOP_PRIORITIZATION_DUE_SOON_HOURS", "48.0")
        ),
        prioritization_quick_win_minutes=int(
            os.getenv("CLOOP_PRIORITIZATION_QUICK_WIN_MINUTES", "15")
        ),
        prioritization_high_leverage_threshold=float(
            os.getenv("CLOOP_PRIORITIZATION_HIGH_LEVERAGE_THRESHOLD", "0.7")
        ),
        priority_weight_due=float(os.getenv("CLOOP_PRIORITY_WEIGHT_DUE", "1.0")),
        priority_weight_urgency=float(os.getenv("CLOOP_PRIORITY_WEIGHT_URGENCY", "0.7")),
        priority_weight_importance=float(os.getenv("CLOOP_PRIORITY_WEIGHT_IMPORTANCE", "0.9")),
        priority_weight_time_penalty=float(os.getenv("CLOOP_PRIORITY_WEIGHT_TIME_PENALTY", "0.2")),
        priority_weight_activation_penalty=float(
            os.getenv("CLOOP_PRIORITY_WEIGHT_ACTIVATION_PENALTY", "0.3")
        ),
        related_similarity_threshold=float(os.getenv("CLOOP_RELATED_SIMILARITY_THRESHOLD", "0.78")),
        related_max_candidates=int(os.getenv("CLOOP_RELATED_MAX_CANDIDATES", "1000")),
        idempotency_ttl_seconds=int(os.getenv("CLOOP_IDEMPOTENCY_TTL_SECONDS", "86400")),
        idempotency_max_key_length=int(os.getenv("CLOOP_IDEMPOTENCY_MAX_KEY_LENGTH", "255")),
        # Webhook settings
        webhook_max_retries=int(os.getenv("CLOOP_WEBHOOK_MAX_RETRIES", "5")),
        webhook_retry_base_delay=float(os.getenv("CLOOP_WEBHOOK_RETRY_BASE_DELAY", "2.0")),
        webhook_retry_max_delay=float(os.getenv("CLOOP_WEBHOOK_RETRY_MAX_DELAY", "300.0")),
        webhook_timeout_seconds=float(os.getenv("CLOOP_WEBHOOK_TIMEOUT_SECONDS", "30.0")),
        webhook_heartbeat_interval=float(os.getenv("CLOOP_WEBHOOK_HEARTBEAT_INTERVAL", "30.0")),
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
    try:
        return EmbedStorageMode(value)
    except ValueError as exc:
        raise ValueError(f"Invalid CLOOP_EMBED_STORAGE: {raw}") from exc


def _resolve_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
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
    if not 0.0 <= settings.autopilot_autoapply_min_confidence <= 1.0:
        raise ValueError("CLOOP_AUTOPILOT_AUTOAPPLY_MIN_CONFIDENCE must be between 0 and 1")
    if settings.related_max_candidates < 1:
        raise ValueError("CLOOP_RELATED_MAX_CANDIDATES must be at least 1")
    if settings.idempotency_ttl_seconds < 1:
        raise ValueError("CLOOP_IDEMPOTENCY_TTL_SECONDS must be at least 1")
    if settings.idempotency_max_key_length < 16:
        raise ValueError("CLOOP_IDEMPOTENCY_MAX_KEY_LENGTH must be at least 16")
    for weight_name in [
        "priority_weight_due",
        "priority_weight_urgency",
        "priority_weight_importance",
        "priority_weight_time_penalty",
        "priority_weight_activation_penalty",
    ]:
        weight = getattr(settings, weight_name)
        if weight < 0:
            raise ValueError(f"CLOOP_{weight_name.upper()} must be non-negative")
    # Validate webhook settings
    if settings.webhook_max_retries < 0:
        raise ValueError("CLOOP_WEBHOOK_MAX_RETRIES must be non-negative")
    if settings.webhook_retry_base_delay <= 0:
        raise ValueError("CLOOP_WEBHOOK_RETRY_BASE_DELAY must be positive")
    if settings.webhook_retry_max_delay < settings.webhook_retry_base_delay:
        raise ValueError("CLOOP_WEBHOOK_RETRY_MAX_DELAY must be >= CLOOP_WEBHOOK_RETRY_BASE_DELAY")
    if settings.webhook_timeout_seconds <= 0:
        raise ValueError("CLOOP_WEBHOOK_TIMEOUT_SECONDS must be positive")
    if settings.webhook_heartbeat_interval <= 0:
        raise ValueError("CLOOP_WEBHOOK_HEARTBEAT_INTERVAL must be positive")
    return settings
