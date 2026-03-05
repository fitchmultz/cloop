.PHONY: help sync fmt fmt-check lint lint-fix env-sync header-check secrets-check version-check changelog-check type quality test test-fast test-slow test-performance test-cov dist dist-check check-fast check-full check ci run

help:
	@printf "%s\n" \
		"Usage: make <target>" \
		"" \
		"Targets:" \
		"  sync            Sync (upgrade) all deps via uv" \
		"  fmt             Format code with ruff" \
		"  fmt-check       Check formatting (no changes)" \
		"  lint            Lint with ruff" \
		"  lint-fix        Lint + auto-fix with ruff" \
		"  env-sync        Check .env.example sync with settings.py" \
		"  header-check    Validate module header sections in src/cloop" \
		"  secrets-check   Scan tracked files for likely secrets" \
		"  version-check   Ensure pyproject version matches runtime version" \
		"  changelog-check Ensure current version is documented in CHANGELOG.md" \
		"  type            Type check with ty" \
		"  quality         Run all non-test quality checks" \
		"  test            Run full pytest suite" \
		"  test-fast       Run PR-fast suite (exclude slow/performance markers)" \
		"  test-slow       Run only slow-marker tests" \
		"  test-performance Run only performance-marker tests" \
		"  test-cov        Run tests with coverage report + coverage.xml" \
		"  dist            Build sdist and wheel artifacts" \
		"  dist-check      Build artifacts and validate metadata with twine" \
		"  check-fast      Run quality + test-fast (recommended during development)" \
		"  check-full      Run full release gate (quality + test + dist-check)" \
		"  check           Alias for check-full" \
		"  ci              Alias for check-full (local CI gate)" \
		"  run             Run FastAPI locally (uvicorn)"

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

changelog-check:
	uv run python scripts/check_changelog_sync.py

type:
	uv run ty check

quality: fmt-check lint env-sync header-check secrets-check version-check changelog-check type

test:
	uv run pytest

test-fast:
	uv run pytest -m "not slow and not performance"

test-slow:
	uv run pytest -m "slow"

test-performance:
	uv run pytest -m "performance"

test-cov:
	uv run pytest --cov=cloop --cov-report=term-missing --cov-report=xml

dist:
	rm -rf dist build
	uv run python -m build --sdist --wheel

dist-check: dist
	uv run twine check dist/*

check-fast: quality test-fast

check-full: quality test dist-check

check: check-full

ci: check-full

run:
	uv run uvicorn cloop.main:app --reload
