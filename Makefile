.PHONY: help sync fmt fmt-check lint lint-fix type test check ci run

help:
	@printf "%s\n" \
		"Usage: make <target>" \
		"" \
		"Targets:" \
		"  sync       Sync (upgrade) all deps via uv" \
		"  fmt        Format code with ruff" \
		"  fmt-check  Check formatting (no changes)" \
		"  lint       Lint with ruff" \
		"  lint-fix   Lint + auto-fix with ruff" \
		"  type       Type check with ty" \
		"  test       Run tests with pytest" \
		"  check      Run fmt-check, lint, type, test" \
		"  run        Run FastAPI locally (uvicorn)"

sync:
	uv sync --all-groups --upgrade --all-extras

fmt:
	uv run ruff format .

fmt-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

type:
	uv run ty check

test:
	uv run pytest

check: fmt-check lint type test

ci: check

run:
	uv run uvicorn cloop.main:app --reload
