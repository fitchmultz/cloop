# CI Strategy and Resource Controls

This repository uses a two-tier CI model to balance fast feedback with deep confidence.

## PR required checks (`.github/workflows/ci.yml`)

Intended for deterministic, fast feedback on every pull request.

Runs:
- `make quality` (format/lint/type + config/security/version/changelog checks)
- `make test-fast` on Python 3.14

Runtime and resource controls:
- Job-level timeouts (`timeout-minutes`)
- Matrix `max-parallel: 2` to avoid runner saturation
- Concurrency cancellation for superseded runs

Typical runtime target:
- ~6–12 minutes depending on cache state

## Full confidence checks (`.github/workflows/ci_full.yml`)

Runs on:
- push to `main`
- nightly schedule
- manual dispatch

Runs:
- `make ci` (release-grade gate: quality + tests excluding `performance` + packaging checks) on Python 3.14
- fast validation tests on Python 3.14
- coverage job (`make test-cov`, excludes `performance`) with `coverage.xml` artifact upload
- performance-marker tests on nightly/manual events via dedicated `performance` job

Runtime and resource controls:
- Job-level timeouts on all jobs
- Matrix `max-parallel: 2`
- Concurrency cancellation for stale runs

Typical runtime target:
- `full_gate`: ~12–25 minutes
- `compatibility_fast`: ~4–8 minutes each matrix leg
- `coverage`: ~8–15 minutes
- `performance` (nightly/manual): variable, intentionally isolated from release gate and PR gate

## Release checks (`.github/workflows/release.yml`)

Runs on semver tag pushes (`v*.*.*`) and manual dispatch.

Runs:
- dependency sync
- `make ci`
- GitHub Release creation with `dist/*` artifacts

Resource controls:
- Job timeout (`timeout-minutes: 45`)

## Local command mapping

- Fast PR-equivalent local run: `make check-fast`
- Full release-grade local run: `make ci`
- Exhaustive all-markers local run: `make test-all`
- Coverage local run: `make test-cov`
- Performance-only local run: `make test-performance`
