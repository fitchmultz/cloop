.PHONY: help lock-check bridge-lock-check bridge-test sync fmt fmt-check lint lint-fix env-sync header-check secrets-check version-check changelog-check type quality test test-all test-fast test-slow test-performance test-cov dist dist-check check-fast check-full check ci run

UV_RUN := uv run --locked
NPM_BRIDGE := npm --prefix src/cloop/pi_bridge

help:
	@printf "%s\n" \
		"Usage: make <target>" \
		"" \
		"Targets:" \
		"  sync            Sync (upgrade) all deps via uv" \
		"  lock-check      Verify uv.lock matches pyproject metadata" \
		"  bridge-lock-check Verify pi bridge package-lock + installability" \
		"  bridge-test     Run Node bridge tests" \
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
		"  test            Run CI release suite (exclude performance marker)" \
		"  test-all        Run full pytest suite (includes performance marker)" \
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

lock-check:
	uv lock --check

bridge-lock-check:
	test -f src/cloop/pi_bridge/package-lock.json
	$(NPM_BRIDGE) ci

bridge-test: bridge-lock-check
	$(NPM_BRIDGE) test

fmt:
	$(UV_RUN) ruff format .

fmt-check:
	$(UV_RUN) ruff format --check .

lint:
	$(UV_RUN) ruff check .

lint-fix:
	$(UV_RUN) ruff check . --fix

env-sync:
	$(UV_RUN) python scripts/check_env_sync.py

header-check:
	$(UV_RUN) python scripts/check_headers.py

secrets-check:
	$(UV_RUN) python scripts/check_secrets.py

version-check:
	$(UV_RUN) python scripts/check_version_sync.py

changelog-check:
	$(UV_RUN) python scripts/check_changelog_sync.py

type:
	$(UV_RUN) ty check

quality: lock-check bridge-lock-check fmt-check lint env-sync header-check secrets-check version-check changelog-check type

test:
	$(UV_RUN) pytest -m "not performance"

test-all:
	$(UV_RUN) pytest

test-fast:
	$(UV_RUN) pytest -m "not slow and not performance"

test-slow:
	$(UV_RUN) pytest -m "slow"

test-performance:
	$(UV_RUN) pytest -m "performance"

test-cov:
	$(UV_RUN) pytest -m "not performance" --cov=cloop --cov-report=term-missing --cov-report=xml

dist:
	rm -rf dist build src/cloop.egg-info
	$(UV_RUN) python -m build --sdist --wheel

dist-check: dist
	$(UV_RUN) twine check dist/*

check-fast: quality bridge-test test-fast

check-full: quality bridge-test test dist-check

check: check-full

ci: check-full

run:
	$(UV_RUN) uvicorn cloop.main:app --reload
