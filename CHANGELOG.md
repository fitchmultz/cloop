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
- README and CONTRIBUTING now document architecture, CI strategy, and local validation workflows.

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
