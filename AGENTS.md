# Cloop (Closed Loop): AI Coding Agent Guide

Cloop is a **local-first FastAPI service** that provides private chat, RAG (Retrieval-Augmented Generation), and loop/task management. Your data stays in local SQLite files — no external vector database required.

---

## Project Overview

**What is Cloop?**
- A private knowledge base for documents and personal/professional tasks
- A "loop" represents anything open in your mind: tasks, decisions, things to remember
- The "closed loop" workflow: capture → retrieve → act → confirm → close

**Core Capabilities:**
- **Local chat**: Talk to LLMs via Ollama, LM Studio, or hosted providers (OpenAI, Gemini)
- **Private RAG**: Ingest documents (.txt, .md, .pdf) → chunk → embed → store → retrieve
- **Loop management**: State machine for tasks (inbox → actionable/blocked/scheduled → completed/dropped)
- **MCP server**: Expose loop operations to external AI agents

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.14+ |
| Web Framework | FastAPI |
| Database | SQLite (two databases: `core.db`, `rag.db`) |
| Package Manager | `uv` (no pip) |
| LLM/Embedding | `litellm` (unified API for multiple providers) |
| PDF Parsing | `pypdf` |
| Testing | `pytest` + `hypothesis` (property-based) |
| Linting/Format | `ruff` |
| Type Checking | `ty` |

---

## Project Structure

```
src/cloop/
├── __init__.py
├── main.py              # FastAPI app (cloop.main:app)
├── cli.py               # CLI entrypoint (uv run cloop ...)
├── mcp_server.py        # MCP server entrypoint (uv run cloop-mcp)
├── settings.py          # Environment-driven configuration
├── db.py                # SQLite schema, migrations, connections
├── rag.py               # Document ingestion, chunking, retrieval
├── llm.py               # LLM completions via litellm
├── embeddings.py        # Text embedding via litellm
├── providers.py         # Provider-specific API configuration
├── tools.py             # Tool definitions (read_note, write_note)
├── typingx.py           # I/O validation helpers
├── web.py               # Static file serving (Quick Capture UI)
└── loops/               # Loop/task management module
    ├── __init__.py
    ├── models.py        # LoopStatus, LoopRecord, datetime utils
    ├── repo.py          # Database operations (raw SQL)
    ├── service.py       # Business logic, state transitions
    ├── enrichment.py    # AI-powered loop enrichment
    ├── prioritization.py # Scoring and bucketing algorithms
    └── related.py       # Finding related loops

tests/
├── test_app.py          # API endpoint tests
├── test_db_schema.py    # Database schema tests
├── test_llm.py          # LLM integration tests
├── test_loops.py        # Loop management tests
├── test_rag.py          # RAG/retrieval tests
└── test_settings.py     # Configuration tests

data/
├── core.db              # Loops, notes, interactions
└── rag.db               # Documents, chunks, embeddings
```

---

## Build, Test, and Development Commands

**All commands use `uv` — do not use pip.**

### Setup
```bash
uv sync --all-groups --all-extras    # Install dependencies
cp .env.example .env                 # Create local config
# Edit .env to configure your LLM provider
```

### Development
```bash
make sync           # Install/upgrade all deps
make run            # Run FastAPI server with reload (uvicorn)
make check          # Run format-check, lint, type-check, and tests
```

### Individual Commands
```bash
# Formatting
uv run ruff format .           # Format code
uv run ruff format --check .   # Check formatting (CI)

# Linting
uv run ruff check .            # Lint
uv run ruff check . --fix      # Lint and auto-fix

# Type Checking
uv run ty check                # Type check with ty

# Testing
uv run pytest                  # Run all tests
uv run pytest tests/test_loops.py -v   # Run specific test file
```

### CLI Usage
```bash
# Ingest documents
uv run cloop ingest ./my-docs --mode add

# Query knowledge base (returns JSON with chunks)
uv run cloop ask "What does the onboarding say about PTO?" --k 5

# Capture a loop
uv run cloop capture "Return Amazon package by Friday"

# List inbox
uv run cloop inbox

# Show prioritized next actions
uv run cloop next
```

### MCP Server
```bash
uv run cloop-mcp    # Run MCP server (stdio transport)
```

---

## Configuration

Configuration is **environment-driven** via `.env` file. Key variables:

**Models:**
- `CLOOP_LLM_MODEL`: Chat model (default: `ollama/llama3`)
- `CLOOP_EMBED_MODEL`: Embedding model (default: `ollama/nomic-embed-text`)
- `CLOOP_ORGANIZER_MODEL`: Loop enrichment model (default: `gemini/gemini-3-flash-preview`)

**API Bases:**
- `CLOOP_OLLAMA_API_BASE`: Required for Ollama (e.g., `http://localhost:11434`)
- `CLOOP_OPENAI_API_KEY`: Required for OpenAI models
- `CLOOP_GOOGLE_API_KEY`: Required for Gemini models

**Storage:**
- `CLOOP_DATA_DIR`: Directory for databases (default: `./data`)
- `CLOOP_CORE_DB_PATH`: Override core.db location
- `CLOOP_RAG_DB_PATH`: Override rag.db location

**RAG Behavior:**
- `CLOOP_VECTOR_MODE`: `python` (default), `sqlite`, or `auto`
- `CLOOP_EMBED_STORAGE`: `json`, `blob`, or `dual` (default: `dual`)
- `CLOOP_DEFAULT_TOP_K`: Chunks to retrieve (default: 5)
- `CLOOP_CHUNK_SIZE`: Chunk size in tokens (default: 800)
- `CLOOP_MAX_FILE_SIZE_MB`: Maximum file size for ingestion in MB (default: 50)

**Tools:**
- `CLOOP_TOOL_MODE`: `manual`, `llm`, or `none` (default: `manual`)
- `CLOOP_STREAM_DEFAULT`: Enable streaming by default (default: `false`)

See `.env.example` for full list.

---

## Coding Style & Conventions

- **Python 3.14 only** — use modern features (match/case, typed dicts, etc.)
- **Line length**: 100 characters
- **Types**: Explicit type annotations required; prefer immutable state (frozen dataclasses)
- **Enums**: Use `enum.StrEnum` for runtime flags — no "stringly-typed" options
- **I/O Boundaries**: Validate/coerce using `cloop.typingx` helpers at HTTP, DB, env, CLI boundaries

**Example patterns:**
```python
from dataclasses import dataclass
from enum import StrEnum

class VectorMode(StrEnum):
    PYTHON = "python"
    SQLITE = "sqlite"

@dataclass(frozen=True, slots=True)
class Settings:
    chunk_size: int

# Validation at boundary
@typingx.validate_io()
def process_data(value: str) -> dict[str, Any]:
    ...
```

---

## Database Architecture

### Two Database Design

**`core.db`** — Application state:
- `loops`: Tasks with status, priorities, due dates, metadata
- `projects`: Named projects for organizing loops
- `tags` / `loop_tags`: Tagging system (normalized to lowercase)
- `loop_events`: Audit log of all loop changes
- `loop_suggestions`: AI-generated enrichment suggestions
- `loop_embeddings`: Vector embeddings for semantic loop search
- `notes`: Simple key-value notes (tools)
- `interactions`: Request/response logging

**`rag.db`** — Document storage:
- `documents`: File metadata (path, mtime, sha256)
- `chunks`: Document chunks with embeddings (JSON and/or BLOB)
- Virtual tables `vec_chunks` / `vss_chunks`: Optional SQLite vector extensions

### Schema Migrations

Core database has versioned migrations in `db.py` (`_CORE_MIGRATIONS` dict). RAG database uses simple version check.

```python
SCHEMA_VERSION: int = 9      # core.db version
RAG_SCHEMA_VERSION: int = 1  # rag.db version
```

---

## API Endpoints

**Health:**
- `GET /health` — Configuration and storage status

**Chat & RAG:**
- `POST /chat` — Chat completion (optionally with tools); `?stream=true` for SSE
- `POST /ingest` — Ingest files/folders into RAG
- `GET /ask` — RAG question answering with sources

**Loop Management:**
- `POST /loops/capture` — Create new loop
- `GET /loops` — List loops (default: open status)
- `GET /loops/{id}` — Get single loop
- `PATCH /loops/{id}` — Update loop fields
- `POST /loops/{id}/close` — Close loop (completed/dropped)
- `POST /loops/{id}/status` — Transition status
- `POST /loops/{id}/enrich` — Request AI enrichment
- `GET /loops/next` — Prioritized "Next 5" buckets
- `GET /loops/export` — Export all loops
- `POST /loops/import` — Import loops

**Static:**
- `GET /` — Quick Capture UI (HTML form)

---

## Loop State Machine

```
         ┌─────────┐
         │  INBOX  │
         └────┬────┘
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
┌───────┐ ┌───────┐ ┌──────────┐
│ACTION │ │BLOCKED│ │SCHEDULED │
│ -ABLE │ │       │ │          │
└───┬───┘ └───┬───┘ └────┬─────┘
    │         │          │
    └─────────┴──────────┘
              │
              ▼
       ┌─────────────┐
       │  COMPLETED  │
       │   DROPPED   │
       └──────┬──────┘
              │
              ▼
         (can reopen
          to any state)
```

**Status transitions are validated** — see `_ALLOWED_TRANSITIONS` in `loops/service.py`.

---

## Vector Search Architecture

Three retrieval modes controlled by `CLOOP_VECTOR_MODE`:

1. **`python`** (default): Load embeddings into memory, compute cosine similarity in Python
2. **`sqlite`**: Use SQLite JSON extraction for dot product computation
3. **`auto`**: Try SQLite vector extensions first (`sqlite-vec` or `vss0`), fallback to SQLite, then Python

**Optional extensions** (loaded if `CLOOP_SQLITE_VECTOR_EXTENSION` is set):
- `sqlite-vec` (vec0 virtual table)
- `sqlite-vss` (vss0 virtual table)

**Embedding storage modes** (`CLOOP_EMBED_STORAGE`):
- `json`: Store as JSON text (readable, slower)
- `blob`: Store as binary blob (compact, faster)
- `dual`: Store both (default; maximum compatibility)

---

## Testing Guidelines

**Frameworks:** `pytest` + `hypothesis`

**Test organization:**
- Unit tests in `tests/test_*.py`
- Use `TestClient` from FastAPI for endpoint tests
- Use `tmp_path` fixture with `monkeypatch` to isolate database state
- Clear settings cache between tests: `get_settings.cache_clear()`

**Property-based testing:**
- Use `hypothesis` for parsing, validation, and retrieval logic
- Example: `test_chunk_text_preserves_token_order` verifies chunking invariants

**Test pattern for FastAPI:**
```python
def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return TestClient(app)
```

---

## MCP (Model Context Protocol) Server

The `cloop-mcp` command exposes loop operations to AI agents:

- `loop.create` — Capture new loop
- `loop.update` — Update loop fields
- `loop.close` — Close loop
- `loop.list` — List loops by status
- `loop.search` — Text search loops
- `loop.snooze` — Snooze until date
- `loop.enrich` — AI enrichment
- `project.list` — List projects

---

## Security & Configuration

- **Never commit secrets** in `.env`; use `.env.example` for documented defaults
- **Local data** lives under `data/` by default; treat DB files as sensitive
- **API keys** are passed via environment variables only
- **No CORS** configured by default — runs on localhost only

---

## Common Tasks for Agents

### Adding a new loop field
1. Add to `loops/models.py` (`LoopRecord` dataclass)
2. Add to schema in `db.py` (new migration in `_CORE_MIGRATIONS`)
3. Add to `loops/repo.py` (`_ALLOWED_UPDATE_FIELDS`, `_row_to_record`)
4. Add to `main.py` request/response models
5. Add to export/import in `loops/service.py`

### Adding a new API endpoint
1. Define Pydantic request/response models in `main.py`
2. Implement endpoint function with proper error handling
3. Add test in `tests/test_app.py`
4. Update CLI if applicable in `cli.py`

### Modifying retrieval logic
1. Edit `rag.py` — check `_select_retrieval_order()` for path selection
2. Test with both `VectorSearchMode.PYTHON` and `VectorSearchMode.SQLITE`
3. Update `test_rag.py` with property-based or example tests

---

## Dependencies to Know

- **litellm**: Unified LLM API (OpenAI, Anthropic, Gemini, Ollama, etc.)
- **pypdf**: PDF text extraction
- **numpy**: Vector operations
- **pydantic**: Request/response validation
- **FastAPI**: Web framework
- **mcp**: Model Context Protocol SDK
