# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cloop (Closed Loop) is a local-first AI knowledge base and loop management system. It combines:
- **Private RAG**: Ingest documents → chunk → embed → store in SQLite → retrieve context
- **Loop management**: Capture tasks/threads ("loops") with AI-powered enrichment via Gemini
- **MCP server**: Expose loop operations to MCP-capable clients

Data lives in local SQLite files (`core.db` for loops/notes, `rag.db` for documents/chunks).

## Build and Development Commands

```bash
# Install/upgrade dependencies
make sync                    # uv sync --all-groups --upgrade --all-extras

# Run development server
make run                     # uv run uvicorn cloop.main:app --reload

# Quality checks (run before PRs)
make check                   # fmt-check + lint + type + test

# Individual checks
uv run ruff format .         # Format code
uv run ruff check .          # Lint
uv run ty check              # Type check
uv run pytest                # Run all tests
uv run pytest tests/test_loops.py -k test_name  # Single test
```

## CLI Usage

```bash
uv run cloop ingest ./docs          # Ingest documents
uv run cloop ask "question" --k 5   # RAG query
uv run cloop capture "task text" --tz-offset-min -420
uv run cloop inbox                  # List inbox loops
uv run cloop next                   # Get prioritized loops
uv run cloop-mcp                    # Run MCP server (stdio)
```

## Architecture

### Module Structure

- `src/cloop/main.py`: FastAPI app with all HTTP endpoints
- `src/cloop/cli.py`: CLI entrypoint (`cloop` command)
- `src/cloop/mcp_server.py`: MCP server entrypoint (`cloop-mcp` command)
- `src/cloop/settings.py`: Environment-driven config (frozen dataclass)
- `src/cloop/db.py`: SQLite connection management, schema migrations, CRUD
- `src/cloop/rag.py`: Document ingestion, chunking, retrieval
- `src/cloop/embeddings.py`: Embedding generation via litellm
- `src/cloop/llm.py`: LLM completions and tool calling via litellm
- `src/cloop/typingx.py`: Runtime type helpers (`as_type`, `validate_io` decorator)

### Loops Subsystem (`src/cloop/loops/`)

- `models.py`: Domain types (`LoopStatus`, `LoopRecord`, datetime helpers)
- `repo.py`: Raw SQL queries for loops, tags, projects, events
- `service.py`: Business logic (capture, update, transition, search, next)
- `enrichment.py`: Gemini-powered auto-enrichment with confidence gating
- `prioritization.py`: Deterministic priority scoring and bucket assignment
- `related.py`: Embedding-based loop similarity and linking

### Loop State Machine

```
inbox → actionable/blocked/scheduled → completed/dropped
```

Transitions are validated in `service._ALLOWED_TRANSITIONS`. Closed loops can reopen.

### Enrichment Flow

1. Loop captured → `enrichment_state=pending`
2. Background task calls Gemini with structured prompt
3. Response parsed into `LoopSuggestion` (title, tags, next_action, etc.)
4. Fields auto-applied only if `confidence >= CLOOP_AUTOPILOT_AUTOAPPLY_MIN_CONFIDENCE`
5. User edits lock fields (`user_locks`) preventing AI overwrites

### Data Storage

- **core.db**: `notes`, `loops`, `projects`, `tags`, `loop_tags`, `loop_events`, `loop_suggestions`, `loop_embeddings`, `interactions`
- **rag.db**: `documents`, `chunks` (with optional vector extension support)

Schema version tracked via `PRAGMA user_version`. Migrations in `db._CORE_MIGRATIONS`.

## Coding Conventions

- Python 3.14 only
- Ruff formatting (line-length 100)
- Prefer frozen dataclasses and `enum.StrEnum` for type safety
- At I/O boundaries, use `typingx.as_type(T)` or `@typingx.validate_io()` decorator
- All datetime handling via `loops/models.py` helpers (always UTC internally)

## Key Environment Variables

```bash
CLOOP_LLM_MODEL=ollama/llama3           # Chat model
CLOOP_EMBED_MODEL=ollama/nomic-embed-text
CLOOP_ORGANIZER_MODEL=gemini/gemini-3-flash-preview  # Loop enrichment
CLOOP_AUTOPILOT_AUTOAPPLY_MIN_CONFIDENCE=0.85
CLOOP_OLLAMA_API_BASE=http://localhost:11434
CLOOP_GOOGLE_API_KEY=...                # Required for Gemini enrichment
```

## Testing

- Framework: pytest + hypothesis
- Tests in `tests/test_*.py`
- Property-based tests encouraged for parsing/validation logic
