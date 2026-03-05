# Operational Readiness Checklist

## Configuration
- [ ] `.env.example` reflects all non-sensitive settings (`scripts/check_env_sync.py`).
- [ ] `.env` is not tracked (`git ls-files .env` returns nothing).
- [ ] Safe defaults validated (`autopilot` and `scheduler` disabled unless explicitly enabled).

## Validation gates
- [ ] `make check-fast` passes.
- [ ] `make ci` passes.
- [ ] `make test-all` passes before major releases.

## Security and supply chain
- [ ] `uv run python scripts/check_secrets.py` passes.
- [ ] `uv sync --all-groups --all-extras` succeeds from clean clone.
- [ ] Release artifacts pass metadata validation (`twine check dist/*`).

## Runtime behavior
- [ ] CLI help works: `uv run cloop --help`.
- [ ] Server starts and health endpoint responds.
- [ ] API docs UI loads (`/docs`, `/openapi.json`).

## Rollout and rollback notes
- Rollout: tag release after `make ci` + manual smoke checks.
- Rollback: revert to previous tag and re-publish release artifacts.
- If defaults changed, call out behavior change in release notes.
