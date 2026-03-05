# Release Readiness Report (Public-Release Takeover)

Date: 2026-03-05

## Objective

Make Cloop read like an intentional public project with reproducible onboarding, deterministic quality gates, and explicit evidence for skeptical reviewers.

## Phase 0 Baseline (evidence-first)

Executed from a clean working tree on 2026-03-05:

```bash
uv sync --all-groups --all-extras
make check-fast
make ci
```

Observed results before takeover edits:
- `make check-fast`: PASS (`1048 passed, 21 deselected, 1 xpassed`)
- `make ci`: PASS (`1069 passed, 1 xpassed` + packaging/twine checks passed)
- Guard scripts: all PASS (`check_env_sync`, `check_headers`, `check_secrets`, `check_version_sync`, `check_changelog_sync`)

## Prioritized backlog from baseline

### P0
- No active build/test failures.
- No secret leaks detected by current tracked-file scanner.

### P1
- Reviewer-friction mismatch: safe-first-run docs suggested disabling autopilot/scheduler, but runtime defaults were still `true`.
- CI contract mismatch risk: docs framed `performance` tests as isolated from the release gate, while `make ci` implicitly included them.
- Non-zero signal noise: stale `xfail` now produced `XPASS` in core app tests.

### P2
- Improve evidence packaging for public reviewers (demo/workshop/checklist artifacts in one place).

## What changed in this takeover pass

### 1) Safe-by-default first run (P1)
Updated defaults to avoid surprise background automation on a fresh clone:
- `src/cloop/settings.py`
  - `CLOOP_AUTOPILOT_ENABLED` default changed `true -> false`
  - `CLOOP_SCHEDULER_ENABLED` default changed `true -> false`
- `.env.example`
  - `CLOOP_AUTOPILOT_ENABLED=false`
  - `CLOOP_SCHEDULER_ENABLED=false`
  - comments clarified safe-first-run behavior
- Added regression test in `tests/test_settings.py`:
  - `test_defaults_disable_background_automation`
- Hardened test isolation in `tests/conftest.py` by explicitly forcing `CLOOP_AUTOPILOT_ENABLED=false` in shared temp-dir fixture.
- Hardened enrichment tests against host-env drift by setting `CLOOP_ORGANIZER_MODEL=mock-organizer` in `tests/test_loop_enrichment.py`.

### 2) CI/test contract clarity + resource discipline (P1)
Aligned local gate semantics with documented CI strategy:
- `Makefile`
  - `test` now runs `pytest -m "not performance"`
  - added `test-all` for explicit exhaustive runs (includes all markers)
  - `test-cov` now mirrors release-gate scope (`not performance`)
  - help text updated accordingly
- `README.md`, `docs/ci_strategy.md`, `docs/reviewer_validation_checklist.md`
  - updated to reflect:
    - `make ci` = release-grade gate excluding `performance`
    - `make test-all` = exhaustive all-markers run
    - `make test-cov` = coverage over release-gate scope
    - `make test-performance` = dedicated heavy suite path

### 3) Removed stale expected-failure marker (P1)
- `tests/test_app.py`
  - removed obsolete `xfail` from static files serving test
  - this eliminates `XPASS` noise and converts behavior to normal pass/fail signal

### 4) Documentation consistency hardening (P1)
- `docs/internal/assistant_blueprint.md` now reflects `autopilot_enabled: bool = False`.

### 5) Public reviewer evidence package (P2)
Added `docs/role-evidence/`:
- `evidence-map.md`
- `demo-script.md`
- `workshop-outline.md`
- `cookbook-guide.md`
- `operational-readiness-checklist.md`

## Verification after edits

Executed on 2026-03-05:

```bash
make check-fast
# 1050 passed, 21 deselected in 46.83s

make ci
# 1064 passed, 7 deselected in 57.22s
# dist build + twine checks: PASSED

make test-all
# 1071 passed in 59.76s
```

Outcome summary:
- all quality checks pass,
- release gate now passes with no `XPASS`,
- exhaustive marker-inclusive suite is available via explicit command.

## Skeptical reviewer simulation (clean clone)

Executed a clean-clone simulation in a temporary directory with fresh dependency sync:

```bash
git clone <repo> <tmp>
uv sync --all-groups --all-extras
cp .env.example .env
make check-fast
make ci
make test-all
```

Result: PASS (`TRUE_CLONE_RETEST_OK`).

Important finding during this simulation:
- Initial run exposed two enrichment tests that were implicitly relying on host provider env vars.
- Fixed by explicitly setting organizer model test env in `tests/test_loop_enrichment.py`.
- Re-ran full clean-clone simulation after fix: PASS.

## CI matrix and runtime profile

### PR required (`.github/workflows/ci.yml`)
- `make quality`
- `make test-fast`
- Resource controls: timeout bounds, matrix max-parallel=2, stale-run cancellation
- Target profile: fast deterministic signal (typically single-digit to low double-digit minutes depending cache)

### Main/nightly/manual (`.github/workflows/ci_full.yml`)
- `make ci` (quality + non-performance tests + dist checks)
- compatibility fast matrix (3.11/3.12)
- `make test-cov` artifact (excluding `performance`)
- dedicated `make test-performance` on nightly/manual

### Release (`.github/workflows/release.yml`)
- dependency sync
- `make ci`
- artifact publishing (`dist/*`)

## Remaining risks

1. Some slow/time-sensitive tests still rely on `sleep()` (isolated by marker strategy, but not fully refactored to injected clocks yet).
2. Coverage threshold is reported but not enforced by numeric policy gate.
3. Public history cleanup is still optional/manual; see `docs/history_rewrite_plan.md`.

## Public-readiness verdict

Current state is release-ready for public visibility:
- deterministic fast PR gate,
- explicit heavy-test isolation strategy,
- safe-first-run defaults,
- clean test signal (no stale `XPASS`),
- reproducible local CI commands and reviewer-facing evidence package.
