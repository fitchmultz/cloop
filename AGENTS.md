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
| Scheduler | `src/cloop/scheduler.py` |
| CLI | `src/cloop/cli.py` |
| MCP server | `src/cloop/mcp_server.py` |
| Design/Architecture | `docs/internal/assistant_blueprint.md` |
| Repo templates/workflows | `.github/ISSUE_TEMPLATE/*`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/workflows/*` |
| Public review docs | `docs/architecture.md`, `docs/ci_strategy.md`, `docs/release_readiness_report.md`, `docs/reviewer_validation_checklist.md`, `docs/history_rewrite_plan.md` |

## User Preferences

- Run `make ci` before claiming completion
- Use `uv run` for all Python commands
- Prefer strict typing with Pydantic where valuable
- Treat `make ci` as the public-readiness gate; it includes `secrets-check`, `version-check`, and packaging validation
- Use `make check-fast` for rapid local iteration before running full `make ci`

## Non-Obvious Patterns

- **Testing**: Use `TestClient` with isolated database via `tmp_path`:
  ```python
  monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
  get_settings.cache_clear()
  db.init_databases(get_settings())
  ```
- **Loops**: State machine transitions in `loops/service.py` (inbox → actionable/blocked/scheduled → completed/dropped)
- **Scheduler**: Periodic tasks in `scheduler.py` (daily/weekly reviews, due-soon nudges, stale rescue)
- **SSE**: Streaming utilities in `sse.py` for real-time responses
- **SQLite in tests**: `with sqlite3.connect(...)` does **not** close connections; use `contextlib.closing(sqlite3.connect(...))` or explicit `conn.close()` in fixtures/finalizers.
- **CI test contract**: `make ci` runs quality + tests excluding `performance` + packaging; use `make test-all` for exhaustive marker-inclusive runs.
- **Safe first-run defaults**: `CLOOP_AUTOPILOT_ENABLED` and `CLOOP_SCHEDULER_ENABLED` default to `false`; enable explicitly when validating automation paths.
- **Autopilot + embeddings config**: if `CLOOP_AUTOPILOT_ENABLED=true` and `CLOOP_EMBED_MODEL` points to an unconfigured provider (e.g., `ollama/...` without `CLOOP_OLLAMA_API_BASE`), enrichment now logs a single skip warning (no traceback) and still completes organizer suggestions.
- **Frontend cache behavior**: root HTML injects a version query onto `init.js`, and `/static` serves JS/CSS with `Cache-Control: no-cache`; browser UI verification should still prefer a fresh tab/profile if a session appears to hold stale ES module state.
- **Comments UX**: comment threads are lazy-loaded on expand; collapsed loop cards should show a neutral `Comments` label until opened, not a loading placeholder.
- **Chat UX**: the web chat client is expected to send `include_loop_context=true` and `include_memory_context=true` by default so responses stay grounded in actual loops and user memory.
- **Keyboard shortcut UX**: loop-card actions keep keyboard shortcuts via `aria-keyshortcuts` and button tooltips; avoid visible single-letter suffix badges inside action labels.
- **Loop card composition**: keep cards separated into identity, planning/context, operations, and footer zones; preserve visual grouping before adding more inline controls.
- **Loop card density**: completed, dropped, and stale loops should render in a compact treatment so active work stays spacious while historical items consume less vertical space.
- **Compact card actions**: historical/compact cards should keep only the highest-signal action visible and tuck secondary actions behind a lightweight overflow affordance.
- **Compact card mode**: compact cards default to summary mode with read-only inline fields; require an explicit `Edit` expansion before exposing the full editing/footer surface.
- **Mobile inbox behavior**: on phone-sized widths, the top tab rail should scroll horizontally instead of clipping, and long active-card capture/summary text should start in a collapsed preview with an explicit expand control.
- **Mobile capture behavior**: the quick-capture form should keep raw text, core status toggles, due date, and next action visible; secondary metadata (minutes, effort, project, tags) should collapse behind an explicit `Add details` control on phone-sized widths.
- **Mobile utility buttons**: small filter/footer utility actions should not inherit the blanket full-width mobile button treatment when that makes the UI look broken or detached.
- **Interaction logging**: provider metadata may include non-JSON helper objects (for example LiteLLM usage objects); logging code must sanitize or serialize them safely instead of assuming plain dicts.
