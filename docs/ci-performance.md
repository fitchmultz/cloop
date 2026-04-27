# Local CI performance profile

## Canonical gate

`make ci` is the canonical local CI gate. It is an alias for `check-full`, which runs quality checks, bridge tests, the non-performance release pytest suite, frontend checks, and package build/metadata validation. This matches the full GitHub workflow's local gate step, but the local command remains the source of truth for developer and agent validation.

## Measurement protocol

- Machine/repo: local checkout on this machine, same working tree except for the measured CI-loop changes.
- Cache protocol: warm local dependency caches and existing lockfiles; no dependency upgrades; same local `.venv`/pnpm store protocol before and after.
- Timing tool: `/usr/bin/time -p` around the full command.
- Baseline command: `make ci` before optimization.
- Final command: exact same `make ci` after optimization.

## Baseline

| Run | Command | Result | Wall time |
| --- | --- | --- | --- |
| 1 | `/usr/bin/time -p make ci` | Pass | 441.89s |

Major observed phases from isolated target profiling:

| Target | Wall time | Notes |
| --- | ---: | --- |
| `make quality` | 29.82s | lock checks, bridge/frontend lock checks, frontend typecheck, ruff, custom scripts, ty |
| `make bridge-test` | 7.00s | bridge lock check + Node bridge tests |
| `make test` | 214.63s | frontend build/test, backup safety subset, full non-performance pytest suite |
| `make dist-check` | 20.79s | frontend build dependency, Python sdist/wheel build, twine metadata check |

The original `check-full` dependency list executed these independent branches serially, so package build/metadata validation, bridge tests, quality checks, and pytest/frontend work could not overlap.

## Changes

- `check-full` and `check-fast` now dispatch their independent validation branches through one recursive `make -j4` graph.
  - This preserves all existing targets and dependencies.
  - Make still deduplicates shared prerequisites such as frontend contract generation/build within the subgraph.
  - Per-target runtime cleanup wrappers are disabled inside the parallel submake and replaced by a single outer cleanup trap, avoiding cleanup races while retaining leak cleanup for the gate.
- Frontend Vitest no longer passes `--passWithNoTests`.
  - The suite currently has 33 test files / 215 tests, so this preserves the existing signal and removes a failure-hiding flag if tests are accidentally excluded in the future.

## Final measurements

| Run | Command | Result | Wall time |
| --- | --- | --- | --- |
| 1 | `/usr/bin/time -p make ci` | Pass: 1384 pytest passed, 7 performance tests deselected; frontend/bridge/package checks passed | 162.83s |
| 2 | `/usr/bin/time -p make ci` | Pass: 1384 pytest passed, 7 performance tests deselected; frontend/bridge/package checks passed | 185.64s |

Final median wall time for the two comparable confirmation runs: 174.24s.

Improvement against the 441.89s baseline: `((441.89 - 174.24) / 441.89) * 100 = 60.6%`.

## Validation-signal preservation

No tests, lint rules, type checks, build checks, lock checks, packaging checks, coverage thresholds, or quality scripts were removed. The same canonical `make ci` target still runs:

- `quality`
- `bridge-test`
- `test`
- `dist-check`

The only validation-semantic change strengthens the frontend test command by requiring Vitest to find tests instead of accepting an empty suite.

## Remaining bottlenecks

- The Python non-performance pytest suite remains the longest single branch, at roughly 2.3-2.6 minutes inside the final gate.
- Several CLI subprocess tests and retry/backoff tests are the largest individual pytest costs. They can likely be optimized safely by reducing test-only retry waits and avoiding repeated subprocess cold starts, but those changes need narrower root-cause work to avoid changing production retry behavior or CLI coverage.
- Pytest process-level parallelism with `pytest-xdist` was investigated but not adopted in this pass because it would require adding a dependency and resolving isolation/overhead behavior. The Make-level concurrency already exceeds the requested 25% target without changing test execution semantics.
