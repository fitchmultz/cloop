# AGENTS.md

## Purpose

Cloop is a local-first FastAPI service for private chat, RAG, loop/task management, web UI, CLI, scheduler, and MCP tools. Data stays in local SQLite files by default; no external vector database is required.

This file tells coding agents how to make safe, verifiable repo changes. Keep it repo-specific and concise.

## Repository map

| Area | Canonical paths |
|---|---|
| Settings and env contract | `src/cloop/settings.py`, `.env.example` |
| FastAPI app and routes | `src/cloop/main.py`, `src/cloop/routes/` |
| Loop state/read/write services | `src/cloop/loops/`, especially `read_service.py`, `write_ops.py`, `serialization.py`, `claim_state.py` |
| Loop HTTP route helpers | `src/cloop/routes/loops/_common.py` |
| Capture/enrichment/review/planning | `src/cloop/loops/capture_orchestration.py`, `enrichment_orchestration.py`, `enrichment_review.py`, `relationship_review.py`, `review_workflows.py`, `planning_workflows.py` |
| Continuity and working sets | `src/cloop/storage/continuity_store.py`, `src/cloop/routes/loops/continuity.py`, `src/cloop/loops/working_sets.py`, `src/cloop/routes/loops/working_sets.py` |
| RAG and embeddings | `src/cloop/rag_execution.py`, `src/cloop/rag/ask_orchestration.py`, `src/cloop/embedding_providers.py`, `src/cloop/litellm_retry.py`, `src/cloop/embeddings.py` |
| Chat and generative runtime | `src/cloop/chat_orchestration.py`, `src/cloop/chat_execution.py`, `src/cloop/llm.py`, `src/cloop/ai_bridge/`, `src/cloop/pi_bridge/` |
| Tool facade and internals | `src/cloop/tools.py`, `src/cloop/_tools/` |
| DB facade and internals | `src/cloop/db.py`, `src/cloop/_db/`, `src/cloop/storage/` |
| Backup facade and internals | `src/cloop/backup.py`, `src/cloop/_backup/` |
| Scheduler facade and internals | `src/cloop/scheduler.py`, `src/cloop/_scheduler/`, `src/cloop/storage/scheduler_store.py`, `src/cloop/storage/_scheduler_store/` |
| CLI and MCP | `src/cloop/cli.py`, `src/cloop/cli_package/`, `src/cloop/mcp_server.py`, `src/cloop/mcp_tools/` |
| Frontend source | `frontend/src/`, `frontend/index.html`, `frontend/public/sw.js` |
| Frontend generated contracts | `frontend/src/generated/` from `scripts/export_frontend_openapi.py` |
| Served frontend build | `src/cloop/static/dist/` |
| Public docs | `README.md`, `docs/architecture.md`, `docs/ai_runtime.md`, `docs/roadmap.md`, `docs/verification_checklist.md`, `docs/release.md` |

## Operating rules

- Prefer one canonical path. Do not add duplicate service layers, workflows, storage code, or transport-specific copies when a shared module exists.
- Preserve transport parity: HTTP, CLI, MCP, and web flows should reuse the same orchestration contracts for the same capability.
- Keep Python responsible for loop state, storage, tools, routing, and deterministic mutations. Generative chat/organizer calls go through the pi bridge; embeddings stay on the LiteLLM-compatible embedding path.
- Use `uv run` or existing `make` targets for Python commands. Do not introduce another Python package manager.
- Use `pnpm --dir frontend` and `pnpm --dir src/cloop/pi_bridge` for Node work. Keep lockfile changes explicit.
- Python runtime policy is 3.14+. Frontend runtime evidence is in `frontend/package.json` (`node >=25.8.2`, `pnpm@11.0.9`).
- Ask the user only when the next step would change product behavior materially, overwrite unknown user work, require credentials/secrets, or choose between incompatible designs. Otherwise proceed, state assumptions, and verify.
- Stop searching when repo evidence identifies the canonical owner and the change scope is clear. Do not inventory the whole repo for a localized change.
- Stop planning and implement when the plan has a clear owner path, validation command, and rollback boundary.
- Do not run destructive commands such as `make reset-local-data`, database wipes, restore operations, or mass deletes unless the task explicitly requires them.

## Setup and commands

Use commands from `Makefile`, `pyproject.toml`, and `frontend/package.json`.

```bash
uv sync --all-groups
pnpm --dir src/cloop/pi_bridge install --frozen-lockfile
pnpm --dir frontend install --frozen-lockfile
```

Start with the maintained command guide:

```bash
make help                 # beginner-focused start-here list
make help-all             # complete maintained target list
```

Most work uses these gates:

```bash
make run                  # uvicorn local app
make check-fast           # fast development gate: quality + bridge tests + fast tests
make ci                   # full local release gate: quality + bridge tests + tests + dist-check
make cleanup-runtime      # stop repo-owned long-running runtime processes
make verify-runtime-clean # report runtime leaks
```

Use narrower stack-specific targets from `make help-all` while iterating, then run the broadest practical gate before done.

## Coding conventions

- Python: keep strict, typed, Pydantic-backed contracts where valuable. Ruff line length is 100; target is `py314`.
- Tests using FastAPI should isolate DB state with `tmp_path`, `CLOOP_DATA_DIR`, `get_settings.cache_clear()`, and `db.init_databases(get_settings())`.
- SQLite tests must close connections explicitly; `with sqlite3.connect(...)` alone is not enough. Use `contextlib.closing(...)` or `conn.close()` in finalizers.
- Loop mutations should use shared idempotency helpers: HTTP through `run_idempotent_loop_route`, MCP through `run_idempotent_tool_mutation`.
- Loop route errors should use structured helpers in `src/cloop/routes/loops/_common.py` instead of ad-hoc plain-string `HTTPException` details.
- Import public facades from `src/cloop/db.py`, `tools.py`, `backup.py`, `scheduler.py`, and `storage/scheduler_store.py` unless editing their internals.
- Frontend source is strict TypeScript under `frontend/src/`; do not reintroduce raw JavaScript modules or temporary `allowJs`.
- Frontend shell/routing state lives in `frontend/src/shell.ts`; review UX in `frontend/src/review-workspace.ts`; command palette in `frontend/src/command-palette.ts` and `command-palette-ranking.ts`; continuity recommendation/recovery in `continuity-follow-through.ts`, `continuity-recommendations.ts`, and `continuity-recovery.ts`.
- Generated frontend contracts are regenerated by `make frontend-contracts` or frontend make targets. If API schemas change, update generated contracts and served/static build artifacts when packaging or runtime behavior depends on them.
- Update docs when commands, APIs, env vars, user-visible behavior, setup, release, or architecture contracts change.
- Dependency changes must update the relevant manifest and lockfile together (`pyproject.toml` + `uv.lock`, frontend `package.json` + `pnpm-lock.yaml`, or pi bridge package files). Prefer maintained libraries over bespoke code.

## Validation and done criteria

Done means:

- The requested behavior or document change is complete.
- Relevant source, tests, generated files, docs, and lockfiles are consistent.
- No repo-owned runtime processes or temp profiles are left behind.
- Validation was run, or a clear blocker is reported.

Validation rules:

- Documentation-only changes: at minimum confirm `AGENTS.md`/docs are readable; run no destructive commands.
- Python-only changes: run focused `uv run --locked --all-groups pytest ...` when possible, then `make check-fast` or explain why not.
- Frontend changes: run `make frontend-type` plus `make frontend-test` or `make frontend-build` as relevant. For meaningful UI/UX changes, inspect the rendered UI with `agent-browser` and capture evidence.
- Cross-stack or release-impacting changes: run `make ci` before claiming completion when practical.
- If validation fails, triage the failure. Fix failures caused by the change. If unrelated or environment-blocked, report the failing command, key output, and why it is outside the change.
- If long-running tooling was started (`uvicorn`, `vite`, `cloop-scheduler`, pi bridge, browser automation, Playwright, etc.), run `make cleanup-runtime` and/or `make verify-runtime-clean` before done.

## Planning and large changes

- Use a short execution plan for multi-file, cross-stack, migration, or behavior-changing work. Include scope, canonical owner paths, validation, and rollback/cleanup notes.
- Use `docs/roadmap.md` for durable product roadmap updates. Prefer larger end-to-end slices that combine tightly coupled contract, storage, transport, and policy work; do not split one churn-prone lane into micro-items unless the cuts are independent.
- Do not create a large new planning file unless the task asks for it or the repo already has an active plan for that work.

## Security and side effects

- Never commit secrets. Keep `.env` local; align public env docs through `.env.example` and `src/cloop/settings.py`.
- `make ci` includes `secrets-check`; run it or `make secrets-check` for changes that touch config, docs examples, auth, or env handling.
- Safe first-run defaults: `CLOOP_AUTOPILOT_ENABLED=false` and `CLOOP_SCHEDULER_ENABLED=false`. Enable automation only for explicit validation or user-requested behavior.
- Local data lives under `data/` by default. Do not reset, migrate destructively, restore backups, or modify user data without explicit scope.
- For GitHub PR automation, create PRs ready for review rather than draft when automation should run; merge only after checks are green and nothing is still running.

## Progress updates and handoff

- For tool-heavy or multi-step work, give brief progress updates after meaningful milestones: what was found, what changed, what is being validated.
- Final handoff should list changed files, validation commands and results, known failures/blockers, and any follow-up risks.
- Do not end with permission-seeking offers when a clear low-risk next step remains; take the step or report the blocker.

## Updating this file

- Keep this file concise, current, and repo-specific.
- Add nested `AGENTS.md` or `AGENTS.override.md` only for subdirectories with materially different commands, stacks, conventions, or safety constraints.
- Remove stale paths and commands when code moves. Prefer exact commands from `Makefile`, package manifests, CI, or docs over guesses.
- Use `MUST`/`NEVER` only for true invariants; write decision rules for judgment calls.
