# Cookbook Pattern: Two-Tier Verification Without Losing Confidence

## Problem
Teams need quick PR feedback but still require deep release confidence.

## Pattern
Use three explicit local commands and map CI to them directly:
- `make check-fast`: quality + fast tests
- `make ci`: release-grade gate without heavyweight performance marker
- `make test-performance` / `make test-all`: explicit deep runs

## Why it works
- Keeps PR latency and resource use bounded.
- Preserves confidence by keeping heavy checks first-class, just separated.
- Makes reviewer expectations explicit and reproducible.

## Safe defaults
- Background automation off by default (`autopilot`, `scheduler`) to reduce first-run surprise behavior.

## Trade-offs
- Excluding performance tests from release gate can miss regressions earlier; mitigated by dedicated nightly/manual performance job.
- Requires documentation discipline to avoid command/CI drift.

## Adoption checklist
1. Define marker taxonomy (`slow`, `performance`, etc.).
2. Wire command contract in Makefile.
3. Mirror command contract in CI workflows.
4. Mirror the same contract in reviewer docs.
5. Re-verify periodically with end-to-end command runs.
