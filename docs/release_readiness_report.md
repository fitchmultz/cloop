# Release Readiness Notes

Date: 2026-03-05

This document records the main public-release hardening work that was completed and the verification that supports it. It is intentionally operational in tone: the goal is to preserve what changed and what was checked, not to sell the repository.

## Why this pass happened

The project already had solid implementation depth, but the public-facing repo needed a cleaner first-run experience, clearer validation commands, and tighter alignment between documentation, defaults, and local release gates.

## Material changes preserved

### Safer first-run defaults

- `CLOOP_AUTOPILOT_ENABLED` now defaults to `false`
- `CLOOP_SCHEDULER_ENABLED` now defaults to `false`
- `.env.example` reflects those defaults

This makes a fresh clone more predictable and avoids background automation starting implicitly.

### Clearer local validation contract

The command surface was clarified so contributors and operators can tell which checks are fast and which are exhaustive:

- `make check-fast`: quick local confidence gate
- `make ci`: release-grade local gate
- `make test-all`: exhaustive marker-inclusive test run
- `make test-cov`: coverage over the release-grade scope
- `make test-performance`: heavyweight performance run

### Cleaner test signal

- a stale `xfail` was removed so core test output no longer reports `XPASS`
- test isolation was improved for enrichment/provider configuration

### Public docs reshaped around normal project use

- architecture, CI strategy, security, and validation docs were added or clarified
- internal design material was moved under `docs/internal/`
- optional demo material was removed from the primary public path

## Verification history

The following commands were used during the release-hardening passes:

```bash
uv sync --all-groups --all-extras
make check-fast
make ci
make test-all
```

Clean-clone validation was also exercised during the hardening work:

```bash
git clone <repo> <tmp>
uv sync --all-groups --all-extras
cp .env.example .env
make check-fast
make ci
make test-all
```

## Current release gate

- local release gate: `make ci`
- gate contents: formatting, linting, type checks, config/security/version/changelog checks, non-performance tests, packaging build, `twine check`

## Remaining risks

1. Some time-sensitive tests still rely on `sleep()`, which is acceptable but not ideal.
2. Coverage is reported but not enforced by a numeric threshold.
3. Public-history cleanup remains a separate concern if any secret or sensitive content ever existed in private history.

## Suggested release checklist

Use these documents together before a public release:

- [`README.md`](../README.md)
- [`docs/architecture.md`](architecture.md)
- [`docs/ci_strategy.md`](ci_strategy.md)
- [`docs/verification_checklist.md`](verification_checklist.md)
- [`docs/public_release_checklist.md`](public_release_checklist.md)
