# Cloop Architecture Overview

This document is the public architecture summary for how Cloop actually works.
If you are evaluating the repository, pair it with [`docs/reviewer_guide.md`](reviewer_guide.md).
For deeper product-thinking context, see [`docs/internal/assistant_blueprint.md`](internal/assistant_blueprint.md).

## 1) System shape

Cloop is a local-first FastAPI service with three primary interfaces:

- **HTTP API** (FastAPI routes under `src/cloop/routes/*`)
- **CLI** (`src/cloop/cli.py`, `src/cloop/cli_package/*`)
- **MCP server** (`src/cloop/mcp_server.py`, tools in `src/cloop/mcp_tools/*`)

All interfaces converge on shared domain/service/repository logic in `src/cloop/loops/*` and `src/cloop/rag/*`.
Persistent state is local SQLite (`core.db`, `rag.db`), not an external database service.

```mermaid
flowchart LR
  UI[Static Web UI\nsrc/cloop/static] --> API[FastAPI\nsrc/cloop/main.py]
  CLI[CLI\ncloop] --> API
  MCP[MCP Server\ncloop-mcp] --> API

  API --> ROUTES[Routes\nsrc/cloop/routes/*]
  ROUTES --> LOOPS[Loop services\nsrc/cloop/loops/service.py]
  ROUTES --> RAG[RAG services\nsrc/cloop/rag/*]

  LOOPS --> CORE[(core.db)]
  RAG --> RAGDB[(rag.db)]

  LOOPS --> SSE[SSE stream\nsrc/cloop/sse.py]
  LOOPS --> WEBHOOKS[Webhook delivery\nsrc/cloop/webhooks/*]
```

## 2) Core components

### API boundary
- `src/cloop/main.py`: app bootstrap, lifespan, router registration, health endpoint.
- `src/cloop/routes/*`: HTTP request/response wiring and schema mapping.

### Domain logic
- `src/cloop/loops/service.py`: loop lifecycle operations and state transitions.
- `src/cloop/loops/repo.py`: SQL-focused persistence operations.
- `src/cloop/loops/prioritization.py`, `review.py`, `timers.py`, `claims.py`: specialized loop behavior.

### Retrieval + generation
- `src/cloop/rag/*`: ingestion, chunking, embeddings, vector search order, and retrieval composition.
- `src/cloop/llm.py`, `providers.py`, `embeddings.py`: model/provider interaction and resilience policies.

### Real-time/eventing
- `src/cloop/sse.py`: server-sent events fan-out for loop events.
- `src/cloop/webhooks/*`: signed webhook subscriptions and delivery/retry behavior.
- `src/cloop/scheduler.py`: periodic review/nudge routines.

## 3) Data and control flow examples

### Capture a loop (HTTP)
1. Client sends `POST /loops/capture`.
2. Route validates payload via schema.
3. Service layer applies lifecycle rules and writes to `core.db`.
4. Event is emitted to SSE subscribers and webhook pipeline.
5. API returns created loop record.

### Ask with RAG
1. Client ingests documents (`/ingest`) and asks (`/ask`).
2. RAG module loads/chunks/embeds and stores vectors in `rag.db`.
3. Retrieval selects candidate chunks and assembles source context.
4. LLM response is generated with explicit source payload.

### MCP loop mutation
1. MCP tool call maps to loop service operation.
2. Optional idempotency key (`request_id`) guards repeated mutations.
3. Service/repo persist state changes; event stream/webhooks reflect updates.

## 4) Key design decisions and trade-offs

### Local-first data plane
**Decision:** keep data in local SQLite files (`core.db`, `rag.db`).

- **Pros:** easy setup, private-by-default posture, no infrastructure tax.
- **Trade-offs:** single-node scale profile and operational boundaries versus managed DB services.

### Shared service layer across interfaces
**Decision:** API/CLI/MCP reuse the same domain modules.

- **Pros:** consistent behavior and reduced logic drift.
- **Trade-offs:** clearer boundaries are required to avoid route/CLI-specific concerns leaking into shared services.

### Deterministic + assisted workflow model
**Decision:** deterministic lifecycle/prioritization with optional LLM enrichment/autopilot.

- **Pros:** predictable core behavior with optional AI assistance.
- **Trade-offs:** requires explicit confidence thresholds and robust fallbacks when providers fail.

## 5) Operational notes

- **Health:** `GET /health` reports model/storage mode and dependency signals.
- **Local CI gate:** `make ci` (quality, tests, packaging checks).
- **Fast dev gate:** `make check-fast` (quality + fast tests).
- **Release-grade artifacts:** `make dist-check` validates build metadata before release publishing.

## 6) Why the MCP surface matters

The MCP server is a meaningful part of the project, not a sidecar demo.

- It exposes loop operations through a narrow domain-specific tool boundary.
- It reuses the same service/repository logic as the API and CLI.
- It avoids giving agents raw SQL or overly broad host access for common loop workflows.

That makes Cloop a useful reference point for evaluating safe agent-tool integration patterns in a real application, not just a standalone chat/RAG demo.

## 7) Where to go next in code

- API bootstrap: `src/cloop/main.py`
- Settings/config loading: `src/cloop/settings.py`
- Loop lifecycle core: `src/cloop/loops/service.py`
- RAG ingest/retrieval: `src/cloop/rag/*`
- CI and release automation: `.github/workflows/*.yml`
