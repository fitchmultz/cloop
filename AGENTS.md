# Cloop (Closed Loop)

Cloop is a local-first FastAPI service for private chat, RAG, and loop/task management.
Your data stays in local SQLite files — no external vector database required.

## Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.14+ |
| Framework | FastAPI |
| Database | SQLite (`core.db`, `rag.db`) |
| Package Manager | `uv` |
| LLM/Embedding | `litellm` |
| Testing | `pytest` + `hypothesis` |
| Linting/Format | `ruff` |
| Type Checking | `ty` |

## Where to Look

| Area | Files |
|------|-------|
| Configuration | `src/cloop/settings.py` |
| API routes | `src/cloop/routes/*.py` |
| Request/response schemas | `src/cloop/schemas/*.py` |
| Loop management | `src/cloop/loops/*.py` |
| RAG (retrieval) | `src/cloop/rag/*.py` |
| Database schema | `src/cloop/db.py` |
| CLI commands | `src/cloop/cli.py` |
| MCP server | `src/cloop/mcp_server.py` |

## Development Commands

```bash
make sync           # Install/upgrade deps
make run            # Run FastAPI server with reload
make check          # Format-check, lint, type-check, tests
make ci             # Full CI gate (sync, format, lint, type-check, test)
```

## Testing Pattern

Use `TestClient` with isolated database via `tmp_path`:

```python
def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return TestClient(app)
```

## Key Concepts

- **Loops**: Tasks with state machine (inbox → actionable/blocked/scheduled → completed/dropped). See `loops/service.py` for transitions.
- **RAG**: Document ingestion → chunking → embedding → retrieval. See `rag/` package.
- **MCP**: Exposes loop operations to external AI agents. See `mcp_server.py`.
