# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Repository secret scanning gate (`scripts/check_secrets.py`) wired into `make ci`.
- Security policy documentation (`SECURITY.md`).
- Public-repo hygiene checks and tracked-artifact cleanup.

### Changed
- `.gitignore` expanded to cover env files, generated artifacts, local tooling state, and SQLite files.
- README security guidance and local CI guidance improved.

## [0.1.0] - 2026-03-04

### Added
- Initial public-ready FastAPI + CLI + static web UI implementation.
- Local-first loop lifecycle management, RAG ingestion/retrieval, and MCP server support.
