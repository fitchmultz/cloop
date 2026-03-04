.PHONY: help sync fmt fmt-check lint lint-fix env-sync header-check secrets-check version-check type test check ci run

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
		"  env-sync   Check .env.example sync with settings.py" \
		"  secrets-check Scan tracked files for likely secrets" \
		"  version-check Ensure pyproject version matches runtime version" \
		"  check      Run fmt-check, lint, env-sync, header-check, secrets-check, version-check, type, test" \
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

env-sync:
	uv run python scripts/check_env_sync.py

header-check:
	uv run python scripts/check_headers.py

secrets-check:
	uv run python scripts/check_secrets.py

version-check:
	uv run python scripts/check_version_sync.py

type:
	uv run ty check

test:
	uv run pytest

check: fmt-check lint env-sync header-check secrets-check version-check type test

ci: check

run:
	uv run uvicorn cloop.main:app --reload
