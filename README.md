# Cloop: Your Private, Local-First AI Knowledge Base

Cloop turns a folder of documents into a private, searchable knowledge base on your machine.
Ingest local files into a lightweight SQLite database, then ask questions with answers grounded in
the exact chunks that were retrieved.

No Docker. No external vector database. Your data stays in local SQLite files (`core.db`, `rag.db`).

## Features

- **Local chat**: Talk to an LLM using local runtimes (Ollama / LM Studio) or hosted providers.
- **Private RAG**: Recursively ingest files → chunk → embed → store in SQLite → retrieve relevant context.
- **No heavy infrastructure**: Pure Python + SQLite; optional SQLite vector extensions if you have them.
- **CLI + API**: Use it from the terminal or run a local HTTP server.
- **Persistent “memory”**: Optional `read_note` / `write_note` tools backed by `core.db`.
- **Streaming (SSE)**: Stream `/chat` and `/ask` responses when enabled.

Supported file types for ingestion: `.txt`, `.md`, `.markdown`, `.pdf`.

## Installation

### Prerequisites

- Python 3.14+
- `uv` (recommended): https://docs.astral.sh/uv/

### Setup

```bash
uv sync --all-groups --all-extras
cp .env.example .env
```

Then edit `.env` to point at your model runtime (see Configuration).

## Quick Start (CLI)

Ingest a folder of documents:

```bash
uv run cloop ingest ./my-docs
```

Retrieve the most relevant chunks for a question:

```bash
uv run cloop ask "What does the onboarding process say about PTO?" --k 5
```

Notes:

- `cloop ask` prints JSON (question + retrieved chunks) for easy piping and inspection.
- For a full LLM-generated answer grounded in those chunks, run the server and use `/ask`.

## Running the Server

Start the local service:

```bash
uv run uvicorn cloop.main:app --reload
```

Endpoints:

- `POST /chat`: chat completion (optionally with tools); `?stream=true` for SSE streaming.
- `POST /ingest`: ingest local files/folders into `rag.db`.
- `GET /ask`: RAG question answering; returns an answer plus `sources` pointing at the retrieved chunks.
- `GET /health`: shows current model + storage configuration.

Example requests:

```bash
curl -X POST http://127.0.0.1:8000/ingest \
  -H 'content-type: application/json' \
  -d '{"paths":["./my-docs"],"mode":"add","recursive":true}'

curl 'http://127.0.0.1:8000/ask?q=What%20is%20Cloop%3F&k=5'
```

## Configuration

Cloop reads configuration from environment variables (a `.env` file works well).

### Choose your models

- `CLOOP_LLM_MODEL`: chat model (default: `ollama/llama3`)
- `CLOOP_EMBED_MODEL`: embedding model used for RAG (default: `ollama/nomic-embed-text`)

### Local models (recommended)

Ollama:

- `CLOOP_OLLAMA_API_BASE` (required when using `ollama/...`, e.g. `http://localhost:11434`)

LM Studio:

- `CLOOP_LMSTUDIO_API_BASE` (e.g. `http://localhost:1234/v1`)

### Hosted providers

OpenAI-compatible:

- `CLOOP_OPENAI_API_KEY` (required for `CLOOP_LLM_MODEL` values like `gpt-...` / `openai/...`)
- `CLOOP_OPENAI_API_BASE` (optional; for compatible gateways)

OpenRouter:

- `CLOOP_OPENROUTER_API_BASE` (optional; for OpenRouter routing)

### Where your data lives

- `CLOOP_DATA_DIR`: directory for `core.db` and `rag.db` (default: `./data`)
- `CLOOP_CORE_DB_PATH`, `CLOOP_RAG_DB_PATH`: override individual DB paths

### RAG behavior

- `CLOOP_DEFAULT_TOP_K`: number of chunks to retrieve (default: `5`)
- `CLOOP_CHUNK_SIZE`: chunk size in tokens/words-ish units (default: `800`)
- `CLOOP_VECTOR_MODE`: `python` (default), `sqlite`, or `auto`
- `CLOOP_EMBED_STORAGE`: `json`, `blob`, or `dual` (default: `dual`)
  - Note: `CLOOP_VECTOR_MODE=sqlite` requires `CLOOP_EMBED_STORAGE=json` or `dual`.
- `CLOOP_SQLITE_VECTOR_EXTENSION`: optional path to a SQLite vector extension, if you have one.

### Tools (“memory” notes)

- `CLOOP_TOOL_MODE`: `manual`, `llm`, or `none` (default: `manual`)
  - `manual`: you must send a `tool_call` to `/chat` (e.g., `read_note`, `write_note`)
  - `llm`: the model can call tools automatically
  - `none`: tools disabled
- `CLOOP_STREAM_DEFAULT`: set to `true` to stream by default (note: streaming is disallowed when tool mode is `llm`)

## Development

- `make sync` (upgrade deps), `make check` (format-check, lint, type, tests)
