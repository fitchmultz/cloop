.PHONY: help lock-check bridge-lock-check bridge-test frontend-lock-check frontend-contracts frontend-type frontend-test frontend-build frontend-dev reset-local-data cleanup-runtime verify-runtime-clean sync fmt fmt-check lint lint-fix env-sync header-check secrets-check version-check changelog-check smoke-public type quality test-backup-safety test test-all test-fast test-slow test-performance test-cov dist dist-check check-fast check-full check ci run

UV_RUN := uv run --locked
PNPM_BRIDGE := pnpm --dir src/cloop/pi_bridge
PNPM_FRONTEND := pnpm --dir frontend
DEFAULT_LOCAL_DATA_DIR := $(CURDIR)/data
RUNTIME_CLEANUP_WRAP := status=0; trap 'status=$$?; $(MAKE) cleanup-runtime >/dev/null; cleanup_status=$$?; if [ $$status -eq 0 ] && [ $$cleanup_status -ne 0 ]; then exit $$cleanup_status; fi; exit $$status' EXIT;

help:
	@printf "%s\n" \
		"Usage: make <target>" \
		"" \
		"Targets:" \
		"  sync            Sync (upgrade) all deps via uv" \
		"  lock-check      Verify uv.lock matches pyproject metadata" \
		"  bridge-lock-check Verify pi bridge pnpm lockfile + installability" \
		"  bridge-test     Run Node bridge tests" \
		"  frontend-lock-check Verify frontend pnpm lockfile + installability" \
		"  frontend-contracts Generate frontend OpenAPI contracts" \
		"  frontend-type   Run frontend TypeScript checks" \
		"  frontend-test   Run frontend Vitest checks" \
		"  frontend-build  Build the Vite frontend bundle" \
		"  frontend-dev    Run the Vite frontend dev server" \
		"  reset-local-data Delete and recreate the default repo-local data directory" \
		"  cleanup-runtime Stop repo-owned runtime processes and remove orphaned temp browser profiles" \
		"  verify-runtime-clean Report repo-owned runtime leaks without changing state" \
		"  fmt             Format code with ruff" \
		"  fmt-check       Check formatting (no changes)" \
		"  lint            Lint with ruff" \
		"  lint-fix        Lint + auto-fix with ruff" \
		"  env-sync        Check .env.example sync with settings.py" \
		"  header-check    Validate module header sections in src/cloop" \
		"  secrets-check   Scan tracked files for likely secrets" \
		"  version-check   Ensure pyproject version matches runtime version" \
		"  changelog-check Ensure current version is documented in CHANGELOG.md" \
		"  smoke-public    Smoke test lightweight package/app/backup CLI surfaces" \
		"  type            Type check with ty" \
		"  quality         Run all non-test quality checks" \
		"  test-backup-safety Run focused destructive backup restore regressions" \
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
	test -f src/cloop/pi_bridge/pnpm-lock.yaml
	$(PNPM_BRIDGE) install --frozen-lockfile

bridge-test: bridge-lock-check
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(PNPM_BRIDGE) test

frontend-lock-check:
	test -f frontend/package.json
	test -f frontend/pnpm-lock.yaml
	$(PNPM_FRONTEND) install --frozen-lockfile

frontend-contracts: frontend-lock-check
	$(PNPM_FRONTEND) generate:contracts

frontend-type: frontend-contracts
	$(PNPM_FRONTEND) typecheck

frontend-test: frontend-contracts
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(PNPM_FRONTEND) test

frontend-build: frontend-contracts
	$(PNPM_FRONTEND) build

frontend-dev: frontend-contracts
	$(PNPM_FRONTEND) dev

reset-local-data:
	rm -rf $(DEFAULT_LOCAL_DATA_DIR)
	mkdir -p $(DEFAULT_LOCAL_DATA_DIR)
	@printf "Reset local repo data directory: %s\n" "$(DEFAULT_LOCAL_DATA_DIR)"

cleanup-runtime:
	$(UV_RUN) python scripts/cleanup_runtime.py --clean

verify-runtime-clean:
	$(UV_RUN) python scripts/cleanup_runtime.py --check

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

smoke-public:
	$(UV_RUN) python scripts/check_public_surfaces.py

type:
	$(UV_RUN) ty check

quality: lock-check bridge-lock-check frontend-type fmt-check lint env-sync header-check secrets-check version-check changelog-check smoke-public type

test-backup-safety:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest tests/test_backup.py -q

test: frontend-build frontend-test test-backup-safety
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -m "not performance"

test-all:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest

test-fast: frontend-build frontend-test test-backup-safety
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -m "not slow and not performance"

test-slow:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -m "slow"

test-performance:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -m "performance"

test-cov:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -m "not performance" --cov=cloop --cov-report=term-missing --cov-report=xml

dist: frontend-build
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
