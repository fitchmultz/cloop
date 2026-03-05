# Public Release Checklist

Use this checklist before changing repository visibility to public.

## Security readiness

- [ ] Verify `.env` and secret files are not tracked (`git ls-files .env` should return nothing).
- [ ] Run `uv run python scripts/check_secrets.py` and confirm `OK`.
- [ ] Confirm `make ci` passes on current `main`.
- [ ] If a secret was exposed outside trusted private history, rotate/revoke it before publication.
- [ ] If a secret only existed in private local history, ensure history was scrubbed before publication and document a follow-up rotation plan.

## Commit history hygiene

- [ ] Inspect commit history for noisy/internal-only commits: `git log --oneline --decorate`.
- [ ] If secret material ever existed in history, scrub history before public launch (for example with `git filter-repo`) and force-push cleaned history.
- [ ] Reword/squash low-signal commit messages into reviewer-friendly narrative commits when practical.

## Documentation and UX polish

- [ ] README links, badges, and setup steps all work from a clean clone.
- [ ] `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `LICENSE`, and GitHub issue/PR templates are current.
- [ ] Static web UI loads and keyboard navigation works for major paths.
- [ ] API docs endpoints (`/docs`, `/redoc`, `/openapi.json`) load successfully.

## Reproducibility checks

- [ ] Fresh clone test: `uv sync --all-groups --all-extras && make ci`.
- [ ] Fast developer gate: `make check-fast`.
- [ ] Exhaustive marker-inclusive run before release cut: `make test-all`.
- [ ] CLI smoke test: `uv run cloop --help`.
- [ ] Server smoke test: `uv run uvicorn cloop.main:app --reload`.

## GitHub repository settings

- [ ] Add repository description and topics.
- [ ] Ensure branch protections and required checks are configured (PR-fast workflow checks only).
- [ ] Verify full/nightly workflow is active for post-merge deep checks.
- [ ] Enable security alerts and private vulnerability reporting.
- [ ] Confirm release workflow works by publishing a test tag on a non-production branch or fork.
- [ ] Draft first release notes from `CHANGELOG.md`.
- [ ] Verify `docs/role-evidence/` is current for external reviewer walkthroughs.
