.DEFAULT_GOAL := help

.PHONY: help help-all lock-check bridge-lock-check bridge-test frontend-lock-check frontend-contracts frontend-type frontend-test frontend-build frontend-dev reset-local-data cleanup-runtime verify-runtime-clean sync fmt fmt-check lint lint-fix env-sync header-check secrets-check version-check changelog-check smoke-public type quality test-backup-safety test test-all test-fast test-slow test-performance test-cov dist dist-check check-fast check-full check ci run FORCE

UV_RUN := uv run --locked --all-groups
PNPM_BRIDGE := pnpm --dir src/cloop/pi_bridge
PNPM_FRONTEND := pnpm --dir frontend
PYTEST_WORKERS ?= auto
DEFAULT_LOCAL_DATA_DIR := $(CURDIR)/data
RUNTIME_CLEANUP_WRAP := status=0; trap 'status=$$?; $(MAKE) cleanup-runtime >/dev/null; cleanup_status=$$?; if [ $$status -eq 0 ] && [ $$cleanup_status -ne 0 ]; then exit $$cleanup_status; fi; exit $$status' EXIT;

help:
	@printf "%s\n" \
		"Cloop Makefile" \
		"" \
		"Start here:" \
		"  make run                 Start the FastAPI dev server" \
		"  make check-fast          Fast local gate before pushing" \
		"  make ci                  Full local release gate" \
		"" \
		"Common focused checks:" \
		"  make frontend-type       Generate contracts, then TypeScript check" \
		"  make frontend-test       Generate contracts, then run Vitest" \
		"  make frontend-build      Generate contracts, then build frontend" \
		"  make bridge-test         Check pi bridge installability and tests" \
		"  make test-fast           Fast app test suite" \
		"" \
		"Fixes and cleanup:" \
		"  make fmt                 Format Python code" \
		"  make lint-fix            Auto-fix Ruff lint issues" \
		"  make cleanup-runtime     Stop repo-owned dev/test processes" \
		"  make verify-runtime-clean  Check for leaked repo-owned processes" \
		"" \
		"Danger zone:" \
		"  make reset-local-data    Delete and recreate ./data" \
		"" \
		"More:" \
		"  make help-all            Show every maintained target"

help-all:
	@printf "%s\n" \
		"Usage: make <target>" \
		"" \
		"Daily targets:" \
		"  help                    Show beginner-focused command list" \
		"  run                     Run FastAPI locally (uvicorn)" \
		"  check-fast              Run quality + bridge-test + test-fast" \
		"  ci                      Alias for check-full (full local gate)" \
		"  fmt                     Format code with ruff" \
		"  lint-fix                Lint + auto-fix with ruff" \
		"  cleanup-runtime         Stop repo-owned runtime processes and temp browser profiles" \
		"  verify-runtime-clean    Report repo-owned runtime leaks without changing state" \
		"" \
		"Stack-specific targets:" \
		"  frontend-contracts      Generate frontend OpenAPI contracts" \
		"  frontend-type           Generate contracts, then run frontend TypeScript checks" \
		"  frontend-test           Generate contracts, then run frontend Vitest checks" \
		"  frontend-build          Generate contracts, then build the Vite frontend bundle" \
		"  frontend-dev            Generate contracts, then run the Vite frontend dev server" \
		"  bridge-test             Verify pi bridge pnpm lockfile, installability, and tests" \
		"  test-fast               Frontend build/test + backup safety + pytest not slow/performance" \
		"  test                    Frontend build/test + backup safety + pytest not performance" \
		"  test-all                Full pytest suite, including performance marker" \
		"  test-slow               Run only slow-marker tests" \
		"  test-performance        Run only performance-marker tests" \
		"  test-cov                Run tests with coverage report + coverage.xml" \
		"" \
		"Quality and invariant targets:" \
		"  quality                 Run all non-test quality checks" \
		"  lock-check              Verify uv.lock matches pyproject metadata" \
		"  bridge-lock-check       Verify pi bridge pnpm lockfile + installability" \
		"  frontend-lock-check     Verify frontend pnpm lockfile + installability" \
		"  fmt-check               Check formatting without changing files" \
		"  lint                    Lint with ruff" \
		"  env-sync                Check .env.example sync with settings.py" \
		"  header-check            Validate module header sections in src/cloop" \
		"  secrets-check           Scan tracked files for likely secrets" \
		"  version-check           Ensure pyproject version matches runtime version" \
		"  changelog-check         Ensure current version is documented in CHANGELOG.md" \
		"  smoke-public            Smoke test lightweight package/app/backup CLI surfaces" \
		"  type                    Type check with ty" \
		"  test-backup-safety      Run focused destructive backup restore regressions" \
		"" \
		"Release and maintenance targets:" \
		"  sync                    Sync and upgrade Python deps via uv; pnpm locks are separate" \
		"  dist                    Build sdist and wheel artifacts" \
		"  dist-check              Build artifacts and validate metadata with twine" \
		"  check-full              Run full release gate: quality + bridge-test + test + dist-check" \
		"  check                   Alias for check-full" \
		"  reset-local-data        Delete and recreate the default repo-local data directory"

sync:
	uv sync --all-groups --upgrade

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

# Regenerate once per `make` graph: FORCE keeps generated OpenAPI contracts
# aligned with backend route/schema changes while this concrete output still lets
# Make dedupe frontend-type / frontend-build / frontend-test in one invocation.
FRONTEND_CONTRACTS_GEN := $(PNPM_FRONTEND) run generate:contracts
FRONTEND_CONTRACTS_MARKER := frontend/src/generated/types.gen.ts
FRONTEND_OPENAPI_EXPORTER := scripts/export_frontend_openapi.py

FORCE:

$(FRONTEND_CONTRACTS_MARKER): FORCE frontend-lock-check $(FRONTEND_OPENAPI_EXPORTER) frontend/openapi-ts.config.ts frontend/package.json frontend/pnpm-lock.yaml
	$(FRONTEND_CONTRACTS_GEN)

.PHONY: frontend-contracts
frontend-contracts: frontend-lock-check
	$(FRONTEND_CONTRACTS_GEN)

frontend-type: $(FRONTEND_CONTRACTS_MARKER)
	$(PNPM_FRONTEND) run typecheck

frontend-test: $(FRONTEND_CONTRACTS_MARKER)
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(PNPM_FRONTEND) run test

frontend-build: $(FRONTEND_CONTRACTS_MARKER)
	$(PNPM_FRONTEND) run build

frontend-dev: $(FRONTEND_CONTRACTS_MARKER)
	$(PNPM_FRONTEND) run dev

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
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -n $(PYTEST_WORKERS) -m "not performance"

test-all:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -n $(PYTEST_WORKERS)

test-fast: frontend-build frontend-test test-backup-safety
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -n $(PYTEST_WORKERS) -m "not slow and not performance"

test-slow:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -m "slow"

test-performance:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -m "performance"

test-cov:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(UV_RUN) pytest -n $(PYTEST_WORKERS) -m "not performance" --cov=cloop --cov-report=term-missing --cov-report=xml

dist: frontend-build
	rm -rf dist build src/cloop.egg-info
	$(UV_RUN) python -m build --sdist --wheel

dist-check: dist
	$(UV_RUN) twine check dist/*

check-fast:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(MAKE) -j4 RUNTIME_CLEANUP_WRAP= quality bridge-test test-fast

check-full:
	@set -e; $(RUNTIME_CLEANUP_WRAP) $(MAKE) -j4 RUNTIME_CLEANUP_WRAP= quality bridge-test test dist-check

check: check-full

ci: check-full

run:
	$(UV_RUN) uvicorn cloop.main:app --reload
