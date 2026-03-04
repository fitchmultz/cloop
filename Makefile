.PHONY: help sync fmt fmt-check lint lint-fix env-sync header-check secrets-check version-check changelog-check type test dist dist-check check ci run

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
		"  changelog-check Ensure current version is documented in CHANGELOG.md" \
		"  dist       Build sdist and wheel artifacts" \
		"  dist-check Build artifacts and validate metadata with twine" \
		"  check      Run fmt-check, lint, env-sync, header-check, secrets-check, version-check, changelog-check, type, test, dist-check" \
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

changelog-check:
	uv run python scripts/check_changelog_sync.py

type:
	uv run ty check

test:
	uv run pytest

dist:
	rm -rf dist build
	uv run python -m build --sdist --wheel

dist-check: dist
	uv run twine check dist/*

check: fmt-check lint env-sync header-check secrets-check version-check changelog-check type test dist-check

ci: check

run:
	uv run uvicorn cloop.main:app --reload
