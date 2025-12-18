# Repository Guidelines

## Project Structure & Module Organization

- `src/cloop/`: library + FastAPI app and CLI entrypoints.
  - `main.py`: FastAPI app (`cloop.main:app`) used by `make run`.
  - `cli.py`: `cloop` CLI (`uv run cloop ...`) for ingestion and querying.
  - `db.py`, `rag.py`, `embeddings.py`, `llm.py`: storage, retrieval, embedding, and model integrations.
  - `settings.py`: environment-driven configuration (see `.env.example`).
- `tests/`: pytest suite (`tests/test_*.py`).
- `data/`: default local SQLite location (e.g., `core.db`, `rag.db`).

## Build, Test, and Development Commands

Python is managed via `pyproject.toml` + `uv` (no `pip`).

- `make sync`: install/upgrade all deps (`uv sync --all-groups --upgrade --all-extras`)
- `make run`: run the local API server (`uv run uvicorn cloop.main:app --reload`)
- `make check`: run format-check, lint, type-check, and tests (recommended before PRs)
- Direct equivalents:
  - `uv run ruff format .` / `uv run ruff check .`
  - `uv run ty check`
  - `uv run pytest`

## Coding Style & Naming Conventions

- Python 3.14 only (match `requires-python` in `pyproject.toml`).
- Formatting/linting: Ruff (`line-length = 100`, target `py314`).
- Prefer explicit types and immutable state (e.g., frozen dataclasses).
- At I/O boundaries (HTTP, DB rows, env, CLI), validate/coerce using `cloop.typingx` helpers
  (e.g., `typingx.as_type(T)` or `@typingx.validate_io(...)`).
- Use `enum.StrEnum` for runtime flags (avoid “stringly-typed” options).

## Testing Guidelines

- Frameworks: `pytest` + `hypothesis`.
- Naming: add tests in `tests/test_*.py`; keep unit tests close to the module behavior they cover.
- Prefer property-based tests for tricky parsing/validation/retrieval logic and assert invalid states
  fail construction/validation.

## Commit & Pull Request Guidelines

- Commits: use imperative, sentence-case subjects (e.g., `Refactor retrieval ordering`).
- PRs: include a short problem statement, what changed, and how to verify (commands + any sample
  requests). Link relevant issues and update `README.md`/`.env.example` when behavior or config
  changes.

## Security & Configuration Tips

- Don’t commit secrets in `.env`; use `.env.example` for documented defaults.
- Local data lives under `data/` by default; treat DB files as sensitive project artifacts.
