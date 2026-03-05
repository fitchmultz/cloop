# Evidence Map

## Production workflow design
- Single local gate (`make ci`) with packaging validation (`twine check`) for release confidence.
- Fast developer gate (`make check-fast`) keeps iteration cost low.
- CI split between PR-fast and deep confidence workflows.

## Reliability and correctness
- Full test suite in repo; dedicated marker strategy for `slow` and `performance` categories.
- Deterministic first-run defaults now disable background automation by default.
- Removed stale `xfail` to restore strict pass/fail signal.

## Safety and security
- Secret/config/version/changelog/header guard scripts run under `make quality`.
- `.env` remains untracked; `.env.example` is source-of-truth and sync-checked.
- Release workflow is explicit and artifact-bound (`dist/*`).

## Developer productivity
- Clear command contract: `check-fast`, `ci`, `test-all`, `test-performance`, `test-cov`.
- Reviewer-oriented docs: architecture, CI strategy, readiness report, and validation checklist.

## Receipts
- Baseline and post-change verification commands/results are recorded in `docs/release_readiness_report.md`.
