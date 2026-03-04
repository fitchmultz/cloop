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

## Local quality gate

Run the same gate expected before merge/release:

```bash
make ci
```

This runs formatting checks, linting, env/header/secret/version checks, typing, and tests.

## Coding standards

- Use `uv run` for Python tooling commands.
- Keep strict typing (`ty`) and Ruff checks green.
- Add tests for behavior changes and regressions.
- Update user-facing docs when command/API/UI behavior changes.

## Pull requests

Please keep PRs focused and include:

- What changed and why
- How to verify (`make ci`, manual checks)
- Any migration or compatibility notes

## Security

If you discover a vulnerability, do **not** open a public issue.
Follow the process in [SECURITY.md](SECURITY.md).

## Community standards

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
