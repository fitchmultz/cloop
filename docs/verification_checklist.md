# Verification Checklist

Use this checklist to validate the repository on a fresh machine.

## 1) Environment setup

```bash
git clone https://github.com/fitchmultz/cloop.git
cd cloop
uv sync --all-groups --all-extras
npm ci --prefix src/cloop/pi_bridge
cp .env.example .env
```

For a minimal local-only run, set these in `.env`:

```dotenv
CLOOP_PI_MODEL=zai/glm-5
CLOOP_PI_ORGANIZER_MODEL=zai/glm-5
CLOOP_EMBED_MODEL=ollama/nomic-embed-text
CLOOP_OLLAMA_API_BASE=http://localhost:11434
```

Cloop passes `CLOOP_PI_MODEL` and `CLOOP_PI_ORGANIZER_MODEL` straight through to pi.
If you prefer a different selector, common project-preferred alternatives are
`kimi-coding/k2p5` and `openai-codex/gpt-5.4`, but any selector available from
`pi --list-models` is valid.

Use `pi --list-models` to confirm the selectors available in your authenticated pi installation.
If bridge startup, auth, or model-availability checks fail, use [`docs/ai_runtime.md`](ai_runtime.md) as the runtime troubleshooting reference.

`CLOOP_AUTOPILOT_ENABLED` and `CLOOP_SCHEDULER_ENABLED` default to `false` for first-run determinism.

## 2) Local development gates

Fast, developer-friendly gate:

```bash
make check-fast
```

Full release-grade gate (CI-equivalent local command):

```bash
make ci
```

Exhaustive all-markers local run (includes `performance` tests):

```bash
make test-all
```

Coverage report:

```bash
make test-cov
```

## 3) Runtime smoke checks

CLI:

```bash
uv run cloop --help
uv run cloop loop list --status open --limit 5
uv run cloop loop semantic-search "buy groceries before the weekend" --status all
uv run cloop loop relationship queue --status all
uv run cloop loop relationship review --loop 1 --status all
uv run cloop review relationship-action list
uv run cloop review relationship-session list
uv run cloop review enrichment-action list
uv run cloop review enrichment-session list
uv run cloop plan session list
uv run cloop loop bulk enrich --query "status:open" --dry-run
uv run cloop chat "What should I focus on today?" --include-loop-context --no-stream
uv run cloop memory create "User prefers dark mode" --category preference --priority 40
uv run cloop memory search "dark mode"
uv run cloop suggestion list --pending
uv run cloop clarification list --loop-id 1
```

Bridge runtime:

```bash
npm test --prefix src/cloop/pi_bridge
uv run pytest tests/test_ai_bridge_runtime.py tests/test_llm.py tests/test_llm_failures.py
```

HTTP server + UI:

```bash
uv run uvicorn cloop.main:app --reload
# open http://127.0.0.1:8000/
# open http://127.0.0.1:8000/docs
# open http://127.0.0.1:8000/health
# confirm bridge_name / bridge_version / bridge_protocol are populated when pi bridge is healthy
```

Review-tab smoke checklist:
- Create a planning session from the Review tab and confirm the workspace shows:
  - plan-generated timestamp / freshness cue
  - current checkpoint success criteria
  - focus-loop cards
  - execution-history output summaries after a checkpoint runs
- If a checkpoint creates a saved review session, confirm the adjacent relationship/enrichment workspace can pick it up without reloading the app.
- Confirm the Review support sidebar still explains the plan → execute → review → refresh flow.

MCP:

```bash
uv run cloop-mcp
```

Confirm your MCP client discovers grounded chat (`chat.complete`), direct memory tools (`memory.list`, `memory.search`, `memory.get`, `memory.create`, `memory.update`, `memory.delete`), semantic loop search (`loop.semantic_search`), relationship-review tools (`loop.relationship_review`, `loop.relationship_queue`, `loop.relationship_confirm`, `loop.relationship_dismiss`), saved review workflow tools (`review.relationship_action.*`, `review.relationship_session.*`, `review.enrichment_action.*`, `review.enrichment_session.*`), planning workflow tools (`plan.session.*`), both retrieval tools (`rag.ask`, `rag.ingest`), suggestion review tools (`suggestion.list`, `suggestion.get`, `suggestion.apply`, `suggestion.reject`), clarification tools (`clarification.list`, `clarification.answer`, `clarification.answer_many`), and the rest of the loop tool set.

Also confirm the MCP client surfaces rich tool descriptions for `chat.complete`, `plan.session.*`, and `review.*` so operators can see Args/Returns/examples guidance during tool discovery.

## 4) CI workflow intent check

- PR-fast workflow: `.github/workflows/ci.yml`
  - quality checks + fast tests (`not slow and not performance`)
- Full workflow: `.github/workflows/ci_full.yml`
  - release gate on `main` (`make ci`, excludes `performance` marker), nightly schedule, coverage artifact, dedicated performance tests (nightly/manual)
- Release workflow: `.github/workflows/release.yml`
  - tag-triggered release with full gate and artifact publishing

## 5) Security and metadata checks

```bash
uv run python scripts/check_secrets.py
uv run python scripts/check_env_sync.py
uv run python scripts/check_version_sync.py
uv run python scripts/check_changelog_sync.py
```
