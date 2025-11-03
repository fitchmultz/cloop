# Cloop LLM Service

Local-first FastAPI API that wraps LiteLLM for chat plus a lightweight RAG workflow backed by SQLite.

## Quickstart
- Install `uv` and ensure Python 3.14 is available.
- Copy `.env.example` to `.env` and tweak any paths or model names.
- Sync dependencies: `uv sync --dev`.
- Run the API: `uv run uvicorn cloop.main:app --reload`.

- `POST /chat`: send chat messages; optionally include a `tool_call` to read or write notes stored in `core.db`. Pass `tool_mode=llm` for automatic tool use or `stream=true` for Server-Sent Events.
- `POST /ingest`: provide local file paths (`txt`, `md`, `pdf`) to chunk, embed, and persist under `rag.db`. Supports modes `add`, `reindex`, `purge`, and `sync`.
- `GET /ask`: RAG question answering. Accepts `k`, `scope` (substring or `doc:<id>`), and `stream=true` for SSE responses. The payload includes `sources` identifying cited chunks.
- `GET /health`: readiness probe that reports configured model, vector backend, and database paths.

### CLI

`uv run cloop ingest <paths...>` and `uv run cloop ask "question" [--k 5] [--scope ...]` expose the same primitives without running the HTTP service. Output is JSON for easy piping.

All interactions are logged inside the `interactions` table with request, response, model, latency, and selected chunks for reproducibility.

## Environment
Key variables:
- `CLOOP_LLM_MODEL` / `CLOOP_EMBED_MODEL`: LiteLLM model aliases.
- `CLOOP_DATA_DIR`: folder where `core.db` and `rag.db` are created; override with `CLOOP_CORE_DB_PATH` / `CLOOP_RAG_DB_PATH` if needed.
- `CLOOP_TOOL_MODE`: default tool orchestration (`manual`, `llm`, or `none`).
- `CLOOP_VECTOR_MODE`: `python` (default), `sqlite`, or `auto`; `sqlite` uses an in-database cosine plan, `auto` prefers SQLite/vec backends when available.
- `CLOOP_SQLITE_VECTOR_EXTENSION`: optional path to a compiled SQLite extension.
- `CLOOP_EMBED_STORAGE`: `json`, `blob`, or `dual` (default) to control embedding persistence.
- `CLOOP_STREAM_DEFAULT`: enable SSE responses by default when set truthy.
- Provider routing knobs:
  - `CLOOP_OPENAI_API_BASE`, `CLOOP_OPENAI_API_KEY`
  - `CLOOP_OLLAMA_API_BASE`
  - `CLOOP_LMSTUDIO_API_BASE`
  - `CLOOP_OPENROUTER_API_BASE`
- Standard LiteLLM credentials (e.g., `LITELLM_API_KEY`) unlock hosted providers.

## Development
- Type check: `uv run basedpyright`.
- Lint/format: `uv run ruff check .`.
- Tests: `uv run pytest` (includes property-based checks via Hypothesis).

The MVP intentionally avoids auth, background jobs, external vector stores, and Docker. Extend the FastAPI app and the SQLite schema as the next iteration demands.
