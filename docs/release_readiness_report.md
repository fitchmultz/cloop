# Release Readiness Report (Public Review Hardening)

Date: 2026-03-05

## Current state summary

- **Stack:** FastAPI service + Python CLI + static web UI, local SQLite (`core.db`, `rag.db`).
- **Primary entrypoints:**
  - API: `uv run uvicorn cloop.main:app --reload`
  - CLI: `uv run cloop ...`
  - MCP: `uv run cloop-mcp`
- **Quality gates:** `make check-fast` (developer), `make ci` (release-grade).
- **Workflows:** PR-fast CI, full main/nightly CI, and tag-based release workflow.

## Top 10 risks found and what changed

1. **CI ran full tests redundantly across jobs (resource-heavy).**  
   **Change:** split PR-fast vs full CI; removed duplicate PR full-test execution.

2. **No explicit CI timeout bounds (hung runs could stall pipelines).**  
   **Change:** added `timeout-minutes` to CI and release jobs.

3. **No explicit fast vs slow/perf test strategy.**  
   **Change:** introduced pytest markers (`slow`, `performance`) and dedicated Make targets.

4. **Known slow tests always ran in PR path.**  
   **Change:** marked timer/claim/backup timing tests as `slow`; query-performance suite as `performance`.

5. **SQLite connection lifecycle produced intermittent `ResourceWarning` noise in long runs.**  
   **Change:** fixed test fixtures to close yielded SQLite connections, replaced `with sqlite3.connect(...)` usage with explicit closing semantics, and hardened `db._connect()` to close on setup failure.

6. **Background scheduler side effects increased potential test noise.**  
   **Change:** test fixtures now default scheduler off for deterministic test behavior.

7. **No first-class coverage command/artifact path.**  
   **Change:** added `make test-cov` + coverage job with artifact upload in full CI.

8. **Architecture context was diffuse (internal blueprint only).**  
   **Change:** added concise external architecture doc (`docs/architecture.md`).

9. **Reviewer validation commands were scattered.**  
   **Change:** added single validation checklist (`docs/reviewer_validation_checklist.md`).

10. **CI strategy rationale was implicit.**  
   **Change:** added explicit CI summary doc (`docs/ci_strategy.md`) with runtime/resource intent.

## Before/after developer experience notes

### Before
- PR checks were heavier than necessary.
- No explicit command boundary between fast and full verification.
- Intermittent SQLite resource warnings could distract from signal.
- Harder to explain architecture and CI behavior quickly to reviewers.

### After
- Clear split: `make check-fast` for iteration, `make ci` for release confidence.
- PR CI favors deterministic speed; full suites moved to main/nightly/manual contexts.
- Coverage runs are clean (no SQLite resource-warning noise) and produce artifacts.
- Architecture, CI strategy, and reviewer validation flow are documented and linked.

## Remaining known issues and next steps

1. **Sleep-based slow tests still exist (now isolated by markers).**  
   Next: replace with clock injection/time-freezing where feasible.

2. **Coverage threshold enforcement is not yet policy-gated.**  
   Next: decide baseline threshold and enforce in CI once stable.

3. **Commit history still includes legacy internal cadence commits.**  
   Next: because repo is private, execute the documented scrub + rewrite flow in `docs/history_rewrite_plan.md` before visibility change.

4. **No containerized deployment profile is documented.**  
   Next: optional `Dockerfile` + deployment smoke docs if deployment portability is required.

## Public readiness verdict

The repository now presents as intentional, maintained, and production-conscious:

- reproducible setup,
- explicit fast/full validation strategy,
- bounded CI resource usage,
- clear architecture and reviewer docs,
- release-grade local gate with packaging checks,
- secret and metadata guardrails in place.
