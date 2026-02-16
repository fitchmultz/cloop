# Cloop (Closed Loop)

<!-- AGENTS ONLY: This file is exclusively for AI agents, not humans -->

**Keep this file updated** as you learn project patterns. Follow: concise, index-style, no duplication.

## Goal

Local-first FastAPI service for private chat, RAG, and loop/task management. All data stays in local SQLite files — no external vector database required.

## Where to Find Things

| Topic | Location |
|-------|----------|
| Configuration | `src/cloop/settings.py` |
| API routes | `src/cloop/routes/*.py` |
| Schemas | `src/cloop/schemas/*.py` |
| Loop management | `src/cloop/loops/` |
| RAG | `src/cloop/rag/` |
| Database schema | `src/cloop/db.py` |
| CLI | `src/cloop/cli.py` |
| MCP server | `src/cloop/mcp_server.py` |

## User Preferences

- Run `make ci` before claiming completion
- Use `uv run` for all Python commands
- Prefer strict typing with Pydantic where valuable

## Non-Obvious Patterns

- **Testing**: Use `TestClient` with isolated database via `tmp_path`:
  ```python
  monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
  get_settings.cache_clear()
  db.init_databases(get_settings())
  ```
- **Loops**: State machine transitions in `loops/service.py` (inbox → actionable/blocked/scheduled → completed/dropped)
- **SSE**: Streaming utilities in `sse.py` for real-time responses
