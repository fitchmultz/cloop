# Verification Checklist

Use this checklist to validate the repository on a fresh machine.

## 1) Environment setup

```bash
git clone https://github.com/fitchmultz/cloop.git
cd cloop
uv sync --all-groups --all-extras
cp .env.example .env
```

For a minimal local-only run, set these in `.env`:

```dotenv
CLOOP_LLM_MODEL=ollama/llama3
CLOOP_EMBED_MODEL=ollama/nomic-embed-text
CLOOP_OLLAMA_API_BASE=http://localhost:11434
```

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
```

HTTP server + UI:

```bash
uv run uvicorn cloop.main:app --reload
# open http://127.0.0.1:8000/
# open http://127.0.0.1:8000/docs
# open http://127.0.0.1:8000/health
```

MCP:

```bash
uv run cloop-mcp
```

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
