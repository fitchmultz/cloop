# Public Release Checklist

Use this checklist before changing repository visibility to public.

## Security readiness

- [ ] Rotate/revoke any credentials that have ever been committed or shared.
- [ ] Verify `.env` and secret files are not tracked (`git ls-files .env` should return nothing).
- [ ] Run `uv run python scripts/check_secrets.py` and confirm `OK`.
- [ ] Confirm `make ci` passes on current `main`.

## Commit history hygiene

- [ ] Inspect commit history for noisy/internal-only commits: `git log --oneline --decorate`.
- [ ] If secret material ever existed in history, scrub history before public launch (for example with `git filter-repo`) and force-push cleaned history.
- [ ] Squash/reword low-signal commit messages into reviewer-friendly narrative commits when practical.

## Documentation and UX polish

- [ ] README links, badges, and setup steps all work from a clean clone.
- [ ] `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, and `LICENSE` exist and are current.
- [ ] Static web UI loads and keyboard navigation works for major paths.

## Reproducibility checks

- [ ] Fresh clone test: `uv sync --all-groups --all-extras && make ci`.
- [ ] CLI smoke test: `uv run cloop --help`.
- [ ] Server smoke test: `uv run uvicorn cloop.main:app --reload`.

## GitHub repository settings

- [ ] Add repository description and topics.
- [ ] Ensure branch protections and required checks are configured.
- [ ] Enable security alerts and private vulnerability reporting.
- [ ] Draft first release notes from `CHANGELOG.md`.
