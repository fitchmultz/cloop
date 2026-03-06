# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Full CI workflow split with separate PR-fast (`ci.yml`) and main/nightly (`ci_full.yml`) gates.
- Coverage command and artifact pipeline (`make test-cov`, `coverage.xml` upload in full CI).
- Explicit exhaustive test target (`make test-all`) for all-marker verification.
- Role evidence pack for external reviewer walkthroughs (`docs/role-evidence/`).
- Public-facing architecture and readiness docs:
  - `docs/architecture.md`
  - `docs/reviewer_validation_checklist.md`
  - `docs/release_readiness_report.md`

### Changed
- CI resource controls now include job timeouts and constrained matrix parallelism.
- Makefile now exposes explicit fast/full quality targets (`quality`, `check-fast`, `check-full`).
- `make ci` now runs non-performance tests by default; performance checks remain explicit via `make test-performance`.
- `make test-cov` now mirrors release-gate scope by excluding `performance` tests.
- Test suite now supports marker-based selection (`slow`, `performance`) for predictable PR runtimes.
- Test fixtures default to `CLOOP_SCHEDULER_ENABLED=false` to reduce background timing side effects.
- Runtime defaults now disable autopilot and scheduler unless explicitly enabled.
- Removed stale app static-files `xfail` marker to eliminate `XPASS` noise from core test output.
- Enrichment tests now pin organizer model env to avoid host-environment provider-key leakage in clean clones.
- Autopilot enrichment now downgrades embed-provider misconfiguration errors to a clear warning without traceback spam, while preserving organizer suggestion completion.
- README and CONTRIBUTING now document architecture, CI strategy, and local validation workflows.
- Web UI now renders RAG answers visibly, exposes an explicit completion confirm action, shows original captured text when autopilot rewrites titles, and uses clearer import/export labels.
- Comments UI now treats loading as a lazy-open state instead of showing permanent placeholder text on every loop card.
- `/healthz` now mirrors `/health`, and static JS/CSS assets are served with `no-cache` headers to reduce stale frontend bundles after UI changes.
- Chat UI now requests loop and memory context by default, and backend chat guidance now pushes the model toward concrete loop-aware recommendations instead of generic productivity advice.
- Chat interaction logging now tolerates provider `usage` objects that are not plain JSON, preventing non-stream `/chat` failures with real provider metadata.
- SSE loop refresh handling now avoids redundant extra fetches on each event.
- Loop-card keyboard shortcuts now live in `aria-keyshortcuts`/tooltips instead of visible suffix glyphs, so action labels render cleanly during browser use.
- Loop cards now use clearer identity/planning/operations/footer zones with denser, more legible visual grouping for dogfooding-heavy inbox use.
- Completed, dropped, and stale loops now render in a compact card treatment to reduce inbox height without sacrificing scanability.
- Compact cards now collapse secondary footer actions behind a lightweight `More` affordance so historical items keep a tighter primary row.
- Compact cards now start in read-only summary mode and require an explicit `Edit` expansion before showing the full editing/footer surface.
- Mobile tab navigation now scrolls horizontally instead of clipping off-screen tabs, and long active-card capture text now starts as a collapsed preview with an explicit expand/collapse control.
- Mobile quick capture now collapses secondary metadata behind an `Add details` control so the inbox starts higher on the screen, and small filter/footer utility buttons no longer stretch into awkward full-width pills on phone-sized widths.
- Public docs now separate the primary reviewer path from internal blueprint material more clearly, add a dedicated reviewer guide, and soften optional demo/workshop artifacts so they do not read like required “portfolio evidence.”

## [0.1.0] - 2026-03-04

### Added
- Initial public-ready FastAPI + CLI + static web UI implementation.
- Local-first loop lifecycle management and deterministic prioritization model.
- RAG ingestion/retrieval with SQLite-backed chunk/document storage.
- MCP server exposing loop/task management tool surface.
- Webhooks + SSE event delivery for loop lifecycle updates.

### Changed
- Python support policy standardized at 3.11+ with synchronized runtime/package version checks.
- Repository metadata and onboarding baseline established (license, contribution/security policy, release docs).
- Release packaging validation integrated into local CI (`build` + `twine check`).

### Security
- Secret scanning gate added for tracked files (`scripts/check_secrets.py`).
- Public release checklist and scrub guidance added for private-history secret incidents.
- `.gitignore` hardened for env files, local databases, generated artifacts, and agent/tool state.

### Developer Experience
- Local CI command surface consolidated under `make` targets with deterministic checks.
- Header, environment, version, and changelog sync checks added for maintainability guardrails.
