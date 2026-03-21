# Cloop (Closed Loop)

<!-- AGENTS ONLY: This file is exclusively for AI agents, not humans -->

**Keep this file updated** as you learn project patterns. Follow: concise, index-style, no duplication.

## Goal

Local-first FastAPI service for private chat, RAG, and loop/task management. All data stays in local SQLite files — no external vector database required.

## Where to Find Things

| Topic | Location |
|-------|----------|
| Configuration | `src/cloop/settings.py` |
| Generative AI bridge runtime | `src/cloop/ai_bridge/`, `src/cloop/pi_bridge/` |
| Shared grounded chat preparation/execution | `src/cloop/chat_orchestration.py`, `src/cloop/chat_execution.py` |
| Shared RAG ask/ingest execution | `src/cloop/rag_execution.py`, `src/cloop/rag/ask_orchestration.py` |
| Shared enrichment orchestration | `src/cloop/loops/enrichment_orchestration.py` |
| Shared enrichment review flows | `src/cloop/loops/enrichment_review.py` |
| Shared relationship review flows | `src/cloop/loops/relationship_review.py` |
| Shared saved review actions + sessions | `src/cloop/loops/review_workflows.py` |
| Shared planning workflows | `src/cloop/loops/planning_workflows.py` |
| Shared direct memory management | `src/cloop/memory_management.py`, `src/cloop/storage/memory_store.py` |
| Backup/restore facade + internals | `src/cloop/backup.py`, `src/cloop/_backup/` |
| LLM/manual tool executors + registry | `src/cloop/tools.py`, `src/cloop/_tools/` |
| Shared semantic loop search + similarity indexing | `src/cloop/loops/read_service.py`, `src/cloop/loops/similarity.py` |
| Embedding-provider resolution | `src/cloop/embedding_providers.py`, `src/cloop/litellm_retry.py`, `src/cloop/embeddings.py` |
| CLI loop parser tree | `src/cloop/cli_package/parsers/loop.py`, `src/cloop/cli_package/parsers/_loop/` |
| API routes | `src/cloop/routes/*.py` |
| Schemas | `src/cloop/schemas/*.py` |
| Loop management | `src/cloop/loops/` |
| RAG | `src/cloop/rag/` |
| Database schema + infra DB wiring | `src/cloop/db.py`, `src/cloop/_db/` |
| Feature-owned persistence stores | `src/cloop/storage/` |
| Scheduler storage facade + internals | `src/cloop/storage/scheduler_store.py`, `src/cloop/storage/_scheduler_store/` |
| Scheduler runtime facade + internals | `src/cloop/scheduler.py`, `src/cloop/_scheduler/` |
| CLI | `src/cloop/cli.py` |
| MCP server | `src/cloop/mcp_server.py` |
| Design/Architecture | `docs/architecture.md` |
| Frontend source workspace | `frontend/` |
| Frontend operator shell + state navigation | `frontend/src/shell.ts`, `frontend/index.html`, `frontend/src/styles/operator.css` |
| Frontend shared rerun/refresh affordances | `frontend/src/executable-rerun.ts`, `frontend/src/operator-action-cards.ts`, `frontend/src/continuity-follow-through.ts` |
| Frontend browser-global PWA runtime | `frontend/src/pwa.ts`, `frontend/public/sw.js` |
| Built frontend assets served by FastAPI | `src/cloop/static/dist/`, `src/cloop/web.py` |
| Product roadmap | `docs/roadmap.md` |
| Repo templates/workflows | `.github/ISSUE_TEMPLATE/*`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/workflows/*` |
| Public docs | `docs/architecture.md`, `docs/roadmap.md`, `docs/ci_strategy.md`, `docs/verification_checklist.md`, `docs/release.md` |

## User Preferences

- Run `make ci` before claiming completion
- Use `uv run` for all Python commands
- Prefer strict typing with Pydantic where valuable
- Treat `make ci` as the public-readiness gate; it includes `secrets-check`, `version-check`, and packaging validation
- Use `make check-fast` for rapid local iteration before running full `make ci`
- Runtime/toolchain policy is now Python 3.14+ only; align local env, docs, and workflow references to 3.14 when touching versioned setup
- CI and release workflows use locked `uv` installs with a pinned `uv` CLI version; keep lockfile drift explicit instead of letting runners resolve live
- Frontend work surfaces are now fully owned by strict TypeScript under `frontend/src/surfaces/*.ts`; do not reintroduce raw JavaScript modules or temporary `allowJs` support
- When Cloop needs explicit pi selector defaults, keep `src/cloop/settings.py`, `.env.example`, local `.env` guidance, and public docs aligned on the current project preference order (`zai/glm-5`, then `kimi-coding/k2p5`, then `openai-codex/gpt-5.4`) and the current selector-resolution contract (comma-separated ordered preferences plus `CLOOP_PI_SELECTOR_MODE={fallback|exact}`); still allow any pi-supported selector override

## Non-Obvious Patterns

- **Testing**: Use `TestClient` with isolated database via `tmp_path`:
  ```python
  monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
  get_settings.cache_clear()
  db.init_databases(get_settings())
  ```
- **Loops**: State machine transitions in `loops/service.py` (inbox → actionable/blocked/scheduled → completed/dropped)
- **Loop reads**: canonical query/read entrypoints live in `src/cloop/loops/read_service.py`; HTTP, CLI, MCP, and tool read paths should import that module directly instead of routing basic reads through `loops/service.py`.
- **Saved views + templates**: canonical owners are `src/cloop/loops/views.py` and `src/cloop/loops/template_management.py`; avoid reintroducing generic service wrappers for those concerns.
- **Bulk enrichment**: selected-loop and query-driven enrichment preview/execution now belong in `src/cloop/loops/enrichment_orchestration.py`; HTTP, CLI, MCP, and web flows should reuse that module instead of open-coding loop-by-loop enrichment loops or query-target selection.
- **Scheduler**: `src/cloop/scheduler.py` is a dedicated process entrypoint (`cloop-scheduler`), not an app-lifespan background task.
- **SSE**: Streaming utilities in `sse.py` for real-time responses
- **SQLite in tests**: `with sqlite3.connect(...)` does **not** close connections; use `contextlib.closing(sqlite3.connect(...))` or explicit `conn.close()` in fixtures/finalizers.
- **CI test contract**: `make ci` runs quality + tests excluding `performance` + packaging; use `make test-all` for exhaustive marker-inclusive runs.
- **Safe first-run defaults**: `CLOOP_AUTOPILOT_ENABLED` and `CLOOP_SCHEDULER_ENABLED` default to `false`; enable explicitly when validating automation paths.
- **Autopilot + embeddings config**: if `CLOOP_AUTOPILOT_ENABLED=true` and `CLOOP_EMBED_MODEL` points to an unconfigured provider (e.g., `ollama/...` without `CLOOP_OLLAMA_API_BASE`), enrichment now logs a single skip warning (no traceback) and still completes organizer suggestions.
- **Frontend source of truth**: Vite + strict TypeScript tooling lives under `frontend/`, and `src/cloop/static/dist/` is the only packaged/served frontend runtime.
- **Frontend shell routing**: the operator-first state navigation and workspace aggregator live in `frontend/src/shell.ts`, using hash-based deep links (`#operator`, `#do/loop/:id`, `#plan/session/:id`, `#decide/{relationship|enrichment}/:id`, `#recall/{chat|memory|rag}`) with typed surface activation instead of hidden-tab bridging.
- **Capture / do / recall source of truth**: the non-review work surfaces now bootstrap from `frontend/src/surfaces/bootstrap.ts`, while the shell-facing launch contracts live in `frontend/src/surface-runtime.ts`; keep new work there instead of reintroducing secondary entrypoints.
- **Operator action-card source of truth**: typed shell-only card contracts live in `frontend/src/contracts-ui.ts`, rendering helpers live in `frontend/src/operator-action-cards.ts`, and the operator workspace should express planning/review/recall handoffs through that shared card model instead of ad-hoc summary markup.
- **Review workspace source of truth**: the redesigned decision workspace for planning, relationship review, enrichment review, and hygiene cohorts lives in `frontend/src/review-workspace.ts`, while shared rerun/refresh card contracts and execution live in `frontend/src/executable-rerun.ts`; keep review UX there instead of reintroducing bespoke refresh buttons or per-surface rerun payloads.
- **Shared frontend runtime helpers**: modal/dialog behavior, merge-modal runtime, loop selection state, and bulk-bar DOM sync now live in `frontend/src/modals.ts`, `frontend/src/duplicates.ts`, `frontend/src/selection-state.ts`, and `frontend/src/bulk-actions.ts`; all surfaces should import those modules directly.
- **Working-set source of truth**: durable working-set and focus-mode backend orchestration live in `src/cloop/loops/working_sets.py` with HTTP routes in `src/cloop/routes/loops/working_sets.py`, while the operator-shell rendering/integration lives in `frontend/src/shell.ts`; keep working-set UX there instead of reviving localStorage-only pinning.
- **Working-set session route**: the first-class resume target is the shell-owned `#working-set/:id` session surface; continuity cards, command-palette launches, and working-set cards should reopen that session instead of guessing a single anchor item.
- **Command-palette source of truth**: the keyboard-first command model, ranking, and quick-action execution live in `frontend/src/command-palette.ts` and `frontend/src/command-palette-ranking.ts`; extend those modules instead of scattering ad-hoc hotkeys or one-off shell action launchers.
- **Local data reset**: `make reset-local-data` is the canonical way to wipe and recreate the default repo-local `data/` directory when a developer wants a clean SQLite state.
- **Frontend cache behavior**: FastAPI now serves the built Vite shell from `src/cloop/static/dist/`; hashed `/static/assets/*` files should be immutable, while root HTML, service worker, and mutable static files stay `no-cache`. Browser UI verification should still prefer a fresh tab/profile if a session appears to hold stale ES module state.
- **Comments UX**: comment threads are lazy-loaded on expand; collapsed loop cards should show a neutral `Comments` label until opened, not a loading placeholder.
- **Idempotent mutations**: shared prepare/replay/finalize flow now lives in `src/cloop/idempotency_flow.py`; MCP tools should layer on `src/cloop/mcp_tools/_idempotency.py` instead of reimplementing claim/replay logic.
- **Mutation helpers**: loop HTTP routes should use `src/cloop/routes/loops/_common.py::run_idempotent_loop_route`, and MCP mutations should use `src/cloop/mcp_tools/_mutation.py::run_idempotent_tool_mutation` to avoid hand-rolled replay/finalize code.
- **Mutation commit contract**: the shared HTTP/MCP mutation helpers own the outer commit for successful non-replay mutations; transport callers should not depend on follow-up commits outside those helpers.
- **Loop serialization + claim state**: canonical loop payload shaping lives in `src/cloop/loops/serialization.py`; active-claim expiry/serialization rules live in `src/cloop/loops/claim_state.py`.
- **Route response builders**: shared loop route model conversion helpers live in `src/cloop/routes/loops/_common.py` (bulk previews, saved views, templates, nested comments); prefer those over repeating inline Pydantic construction.
- **Loop route error payloads**: prefer the structured helpers in `src/cloop/routes/loops/_common.py` for empty-field validation and claim/not-found mapping instead of ad-hoc plain-string `HTTPException` details.
- **Timer pagination**: `src/cloop/loops/timers.py::list_time_sessions` now returns both paginated sessions and a real `total_count`; route code should not derive totals from the current page length.
- **Comment mutations**: `src/cloop/loops/comments.py` commits exactly once after the full comment write + loop event insert + webhook queue succeeds; do not reintroduce intermediate commits in that flow.
- **Bulk mutations**: `src/cloop/loops/bulk.py` should delegate single-item update/close/snooze behavior to the shared mutation helpers in `src/cloop/loops/write_ops.py`; do not fork those business rules back into bulk-specific copies.
- **Storage ownership**: notes, memory, interaction logging, idempotency, and scheduler state belong under `src/cloop/storage/*`; `src/cloop/db.py` should stay infra-only.
- **DB facade boundary**: `src/cloop/db.py` is the canonical public DB surface, while schema SQL/constants, migration helpers, connection helpers, and vector-extension state now live under `src/cloop/_db/`; callers should keep importing the facade instead of reaching into `_db` directly.
- **Capture orchestration**: shared capture/template/recurrence/enrichment setup lives in `src/cloop/loops/capture_orchestration.py`; HTTP, CLI, and MCP capture entrypoints should delegate there instead of maintaining parallel capture flows.
- **Enrichment review orchestration**: suggestion listing/get/apply/reject plus clarification listing/answering belong in `src/cloop/loops/enrichment_review.py`, while answer-plus-rerun conversational refinement belongs in `src/cloop/loops/enrichment_orchestration.py`; HTTP routes, web UI, CLI, and MCP should reuse those modules instead of inventing transport-specific clarification payloads, rerun sequences, or duplicate answer rows.
- **Direct memory orchestration**: direct memory list/search/get/create/update/delete now belong in `src/cloop/memory_management.py`; HTTP routes, web UI, CLI, MCP, and memory tool executors should reuse that module instead of talking to `storage/memory_store.py` directly or inventing transport-specific memory validation.
- **Semantic loop search orchestration**: first-class semantic loop search belongs in `src/cloop/loops/read_service.py::semantic_search_loops`, while canonical loop embedding source text/hash upkeep belongs in `src/cloop/loops/similarity.py`; HTTP, web UI, CLI, and MCP should reuse that contract instead of embedding/scoring loops in transport code.
- **Relationship review orchestration**: duplicate/related review, queueing, confirm/dismiss decisions, and merge-resolution state now belong in `src/cloop/loops/relationship_review.py`; HTTP routes, web UI, CLI, and MCP should reuse that module instead of inventing transport-specific similarity or relationship-state logic.
- **Saved review workflows**: durable review action presets, filtered review sessions, cursor preservation, explicit session refresh, and session-scoped relationship/enrichment review execution now belong in `src/cloop/loops/review_workflows.py`; transports should reuse `/loops/review/*`, `cloop review *`, and `review.*` instead of rebuilding ad-hoc queue state.
- **Planning workflows**: checkpointed AI-native planning sessions, grounded plan refresh, broader deterministic checkpoint execution (loops, query-bulk mutations, saved views/templates, saved review sessions), rollback/provenance metadata, and execution history now belong in `src/cloop/loops/planning_workflows.py`; transports should reuse `/loops/planning/*`, the Review-tab planning workspace, `cloop plan session *`, and `plan.session.*` instead of inventing transport-local workflow state.
- **Planning execution handoff**: canonical planning execution payloads should expose `summary`, `follow_up_resources`, `launch_surfaces`, and `rollback_cues`; HTTP, CLI, MCP, and web should relay or render those fields directly instead of re-deriving created review sessions, views, templates, or undo hints client-side.
- **Saved review-session handoff**: if a planning checkpoint creates a saved relationship/enrichment review session, treat that session as the next queue and open it through the existing `src/cloop/loops/review_workflows.py` transport/state paths instead of a planning-specific fork.
- **RAG execution orchestration**: shared retrieval ingest/ask execution and interaction logging now live in `src/cloop/rag_execution.py`, while retrieval + prompt + answer shaping live in `src/cloop/rag/ask_orchestration.py`; HTTP, CLI, and MCP retrieval flows should reuse those modules instead of forking behavior by transport.
- **Chat execution orchestration**: shared grounded chat preparation lives in `src/cloop/chat_orchestration.py`, and shared execution/logging lives in `src/cloop/chat_execution.py`; HTTP, CLI, and MCP chat flows should reuse those modules instead of rebuilding tool handling, response shaping, or interaction logging per transport.
- **Tool facade boundary**: `src/cloop/tools.py` is the canonical public tool surface, while tool executors/definitions/registry helpers now live under `src/cloop/_tools/`; callers should keep importing the facade instead of reaching into `_tools` directly.
- **Backup facade boundary**: `src/cloop/backup.py` is the canonical public backup surface, while manifesting/archive/restore/inventory/verification internals now live under `src/cloop/_backup/`; callers should keep importing the facade instead of reaching into `_backup` directly.
- **Scheduler facade boundary**: `src/cloop/scheduler.py` is the canonical public scheduler surface, while cadence/task/runtime/CLI internals now live under `src/cloop/_scheduler/`; callers should keep importing the facade instead of reaching into `_scheduler` directly.
- **Scheduler storage facade boundary**: `src/cloop/storage/scheduler_store.py` is the canonical public scheduler storage surface, while focused task-run/schedule/push internals now live under `src/cloop/storage/_scheduler_store/`; internal scheduler runtime modules should import those focused internals instead of regrowing the facade or open-coding scheduler SQL.
- **CLI runtime**: loop-adjacent CLI handlers should centralize connection handling, expected exception mapping, and output/render orchestration through `src/cloop/cli_package/_runtime.py` instead of open-coding `with db.core_connection(...)` and per-command stderr/exit-code trees.
- **Loop parser facade boundary**: `src/cloop/cli_package/parsers/loop.py` is the canonical public loop-parser entrypoint, while focused parser builders now live under `src/cloop/cli_package/parsers/_loop/`; parser registration should keep importing the facade.
- **MCP runtime**: keep FastMCP decorator/error-wrapping helpers in `src/cloop/mcp_tools/_runtime.py`; `src/cloop/mcp_server.py` should stay focused on server assembly.
- **MCP operator docs**: docstrings on `chat.complete`, `plan.session.*`, and `review.*` are part of the operator-facing surface; keep Args/Returns/examples rich and aligned with README/workflow docs when those tools change.
- **Generative runtime boundary**: pi owns chat/organizer generation through the local bridge (`src/cloop/ai_bridge/`, `src/cloop/pi_bridge/`), but Python remains the source of truth for loop state, tool execution, routing, and storage.
- **Pi tool-round budgets**: use per-surface settings from `src/cloop/settings.py::PiToolBudgetSurface` (`chat`, `planning`, `enrichment`, `rag`, `mutation`) instead of reviving one repo-wide max-round default; `src/cloop/llm.py` callers should always pass an explicit surface.
- **Read-only alternate strategies**: bounded retry/fallback behavior for read-only chat/planning/enrichment/RAG now lives in `src/cloop/llm.py`; preserve `generation_strategy`, `alternate_strategy_used`, `strategy_reason`, and ordered `strategy_attempts` through transport/logging layers, and keep `mutation` flows single-path.
- **Chat tool outcomes**: the canonical chat contract now uses ordered `tool_results`, while `tool_result` is only a transitional first-result alias; new transport, frontend, and logging logic should consume the plural field.
- **Embedding split**: embeddings stay on the LiteLLM-compatible path (`embedding_providers.py`, `litellm_retry.py`, `embeddings.py`) even after the pi cutover; do not mix generative bridge assumptions into embedding code.
- **Chat UX**: the web chat client is expected to send `include_loop_context=true` and `include_memory_context=true` by default so responses stay grounded in actual loops and user memory.
- **Public docs split**: keep `README.md`, `docs/architecture.md`, `docs/roadmap.md`, `docs/verification_checklist.md`, and `docs/release.md` as the primary external path.
- **Keyboard shortcut UX**: loop-card actions keep keyboard shortcuts via `aria-keyshortcuts` and button tooltips; avoid visible single-letter suffix badges inside action labels.
- **Loop card composition**: keep cards separated into identity, planning/context, operations, and footer zones; preserve visual grouping before adding more inline controls.
- **Loop card density**: completed, dropped, and stale loops should render in a compact treatment so active work stays spacious while historical items consume less vertical space.
- **Compact card actions**: historical/compact cards should keep only the highest-signal action visible and tuck secondary actions behind a lightweight overflow affordance.
- **Compact card mode**: compact cards default to summary mode with read-only inline fields; require an explicit `Edit` expansion before exposing the full editing/footer surface.
- **Mobile inbox behavior**: on phone-sized widths, the top tab rail should scroll horizontally instead of clipping, and long active-card capture/summary text should start in a collapsed preview with an explicit expand control.
- **Mobile capture behavior**: the quick-capture form should keep raw text, core status toggles, due date, and next action visible; secondary metadata (minutes, effort, project, tags) should collapse behind an explicit `Add details` control on phone-sized widths.
- **Mobile utility buttons**: small filter/footer utility actions should not inherit the blanket full-width mobile button treatment when that makes the UI look broken or detached.
- **Interaction logging**: provider metadata may include non-JSON helper objects (for example LiteLLM usage objects); logging code must sanitize or serialize them safely instead of assuming plain dicts.
