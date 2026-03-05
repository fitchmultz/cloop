# Contributing to Cloop

Thanks for contributing to Cloop.

## Development setup

1. Clone the repository.
2. Install dependencies:

   ```bash
   uv sync --all-groups --all-extras
   ```

3. Create your local environment file:

   ```bash
   cp .env.example .env
   ```

4. Fill `.env` with your local provider settings. Never commit secrets.

## Fast feedback loop (recommended during development)

```bash
make check-fast
```

This runs all quality checks plus the fast test subset (`not slow and not performance`).

## Full local CI gate (release-grade)

```bash
make ci
```

This runs formatting, linting, env/header/secret/version/changelog checks, typing,
full tests, and packaging metadata validation (`twine check`).

## Branch and commit conventions

Use focused branches and commits to keep history reviewer-friendly.

- Branch naming:
  - `feat/<short-topic>`
  - `fix/<short-topic>`
  - `docs/<short-topic>`
  - `chore/<short-topic>`
- Commit style (recommended):
  - `feat: ...`
  - `fix: ...`
  - `docs: ...`
  - `chore: ...`

## Test markers and CI intent

Cloop uses pytest markers to control CI cost and runtime:

- `slow`: tests with deliberate timing windows (`sleep`) or long-running behavior
- `performance`: query/perf-oriented regression checks

Helpful commands:

```bash
make test-fast
make test-slow
make test-performance
make test-cov
```

## Pull requests

Please keep PRs focused and include:

- What changed and why
- How to verify (`make check-fast` and/or `make ci`)
- Any migration or compatibility notes
- Docs updates when command/API/UI behavior changes

## Security

If you discover a vulnerability, do **not** open a public issue.
Follow the process in [SECURITY.md](SECURITY.md).

## Community standards

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
