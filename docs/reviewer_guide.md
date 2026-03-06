# Reviewer Guide

Use this guide if you are evaluating the repository itself rather than adopting Cloop as a daily tool.

## What Cloop is

Cloop is a local-first FastAPI application for:

- capturing and managing loops/tasks
- ingesting and querying local documents with RAG
- exposing loop operations through a narrow MCP server

The same domain logic is reused across the web UI, CLI, HTTP API, and MCP surface. Data stays in local SQLite files by default.

## Read This First

If you only have a few minutes:

1. [`README.md`](../README.md)
2. [`docs/architecture.md`](architecture.md)
3. [`docs/reviewer_validation_checklist.md`](reviewer_validation_checklist.md)

If you want the operational/quality posture too:

4. [`docs/ci_strategy.md`](ci_strategy.md)
5. [`docs/release_readiness_report.md`](release_readiness_report.md)

## Suggested Evaluation Paths

### 5-minute read

- Confirm the project shape in [`README.md`](../README.md)
- Confirm the interface and storage model in [`docs/architecture.md`](architecture.md)
- Skim the validation commands in [`docs/reviewer_validation_checklist.md`](reviewer_validation_checklist.md)

### 20-minute hands-on pass

1. `uv sync --all-groups --all-extras`
2. `cp .env.example .env`
3. `make check-fast`
4. `uv run uvicorn cloop.main:app --reload`
5. Visit `/`, `/docs`, and `/health`
6. Optionally run `make ci`

### MCP-focused review

- Run `uv run cloop-mcp`
- Inspect exposed tools in [`src/cloop/mcp_server.py`](../src/cloop/mcp_server.py)
- Read the MCP notes in [`docs/architecture.md`](architecture.md) and [`README.md`](../README.md)

## Document Separation

- Public product/project docs:
  - [`README.md`](../README.md)
  - [`docs/architecture.md`](architecture.md)
  - [`docs/ci_strategy.md`](ci_strategy.md)
  - [`docs/reviewer_validation_checklist.md`](reviewer_validation_checklist.md)
  - [`docs/release_readiness_report.md`](release_readiness_report.md)
- Internal design material:
  - [`docs/internal/assistant_blueprint.md`](internal/assistant_blueprint.md)
- Optional demo/enablement material:
  - [`docs/role-evidence/`](role-evidence/)

The internal blueprint is useful for product thinking, but it is not the best first-read if you are judging repo quality or rollout readiness.

## What To Look For

- Shared service logic across UI, CLI, API, and MCP instead of four separate implementations.
- Local-first operational choices: SQLite persistence, no mandatory external control plane, safe first-run defaults.
- Clear verification contract: `make check-fast`, `make ci`, `make test-all`.
- Narrow MCP tool surface instead of exposing raw database access to agents.
- Evidence that docs, tests, and runtime behavior match each other.
