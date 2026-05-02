# Local CI Performance Notes

Purpose: record the measured local CI gate, profiling observations, and safe runtime improvements for the canonical developer validation loop.

## Canonical gate

Selected command: `make ci`.

Rationale: the root `Makefile` defines `ci` as an alias for `check-full`, the help text labels it as the local CI gate, project guidance asks agents to run `make ci`, and release/full workflow checks also use `make ci`. The full gate runs quality checks, bridge tests, frontend build/tests, Python tests excluding only the explicit `performance` marker, and packaging metadata checks.

## Measurement protocol

- Machine: same local workstation, same repo checkout.
- Cache protocol: warm local dependency/build caches; no intentional cache deletion between comparable runs.
- Timing tool: `/usr/bin/time -p` wall-clock `real` seconds.
- Baseline command: `/usr/bin/time -p make ci` before optimization.
- Final command: `/usr/bin/time -p make ci` after optimization.

## Baseline

| Run | Command | Status | Wall time |
| --- | --- | --- | ---: |
| 1 | `make ci` | pass (`1384 passed, 7 deselected`) | 142.68s |

Initial profiling showed the Python pytest phase dominated runtime: `pytest -m "not performance" --durations=25` passed in 123.62s wall time with 1384 selected tests. The slowest individual tests were timeout/retry and subprocess CLI coverage, including two embedding timeout tests at about 15s each and the subprocess CLI lifecycle roundtrip at about 12s.

## Optimization applied

- Added `pytest-xdist` to the locked dev dependencies.
- Changed broad local pytest Make targets (`test`, `test-fast`, `test-all`, `test-cov`) to run the same selected tests in parallel with `pytest -n $(PYTEST_WORKERS)`.
- Added `PYTEST_WORKERS ?= auto` so local developers can override worker count without editing the Makefile.
- Preserved `test-backup-safety` as an explicit prerequisite of `test` and `test-fast` so destructive backup restore regressions stay in both the full and fast local gates.

No markers, coverage thresholds, lint/type rules, ignores, skips, `xfail`, `only`, or failure-masking behavior were added.

## Validation and measurements

| Run | Command | Status | Wall time |
| --- | --- | --- | ---: |
| Historical targeted | `make test` | pass (`215` frontend tests, `1384` main Python tests) | 70.50s |
| Historical final 1 | `make ci` | pass (`1384 passed, 7 deselected`) | 71.56s |
| Historical final 2 | `make ci` | pass (`1384 passed, 7 deselected`) | 130.77s |
| Historical final 3 | `make ci` | pass (`1384 passed, 7 deselected`) | 73.48s |
| Historical final 4 | `make ci` | pass (`1384 passed, 7 deselected`) | 94.68s |
| Current verification | `make ci` | pass (`32` focused backup tests, `215` frontend tests, `1384` main Python tests, package checks) | not timed |

Historical final median across four full-gate runs: 84.08s. The second historical final run was an outlier, but still passed with identical test selection.

A direct Python-test comparison also passed with xdist: `uv run --with pytest-xdist --all-groups pytest -n auto -m "not performance"` completed in 47.45s wall time with `1384 passed`.

Historical baseline-to-final-median improvement: `((142.68 - 84.08) / 142.68) * 100 = 41.07%`. Current `test` and `test-fast` semantics intentionally preserve the explicit focused backup safety prerequisite, so current wall time includes that extra safety signal.

## Signal preservation notes

- Python test selection is unchanged except execution is distributed across workers.
- Frontend build and Vitest remain part of `test`, `test-fast`, and therefore `make ci`.
- Quality, bridge, packaging, and twine metadata checks remain part of `make ci`.
- `test-backup-safety` remains explicit in `test` and `test-fast`; the broader pytest selection also covers backup tests that are not excluded by marker filters.

## Remaining bottlenecks

- The xdist suite is still bounded by deliberately slow timeout/retry and subprocess CLI tests.
- Further safe gains likely require replacing real sleeps/timeouts with injectable deterministic clocks or tighter test-only retry policies while preserving production behavior.
- Packaging still copies a large source/static tree, but it overlaps with the parallel gate and remains a distinct release signal.
