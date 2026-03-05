# Demo Script (5–10 minutes)

## Goal
Show that a fresh clone reaches trusted local operation quickly, with deterministic checks.

## Steps
1. Setup
```bash
uv sync --all-groups --all-extras
cp .env.example .env
```
2. Fast confidence gate
```bash
make check-fast
```
Expected: all quality checks pass + fast tests green.

3. Release-grade local gate
```bash
make ci
```
Expected: quality + non-performance tests + packaging checks pass.

4. Runtime smoke
```bash
uv run cloop --help
uv run uvicorn cloop.main:app --reload
```
Visit:
- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/health`

5. Optional exhaustive test pass
```bash
make test-all
```

## Troubleshooting
- If model calls fail, set local model env vars in `.env` (see README).
- If stale config is suspected, clear cache by re-running the command in a fresh shell.
