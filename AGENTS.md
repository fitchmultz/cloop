## Must-Know Workflow for Codex CLI Agents

- Keep it simple; never repeat yourself. Python is managed via `pyproject.toml` + `uv`. No `pip`.
- Work in Python 3.14 (match `pyproject.toml`). Always use `uv` commands: `uv sync --all-groups --upgrade --all-extras`, `uv run <tool>`.
- 3.14 annotations: **don’t** use `from __future__ import annotations`; evaluation is deferred by default (PEP 649/749).
- Follow executable-spec first (TDD/ATDD): write or update a failing test/spec before coding, then red→green→refactor.
- Keep changes small (trunk-based mindset). Run the guardrails on every iteration:  
  1. `uv run ty check`  
  2. `uv run ruff format .` (if formatting needed)  
  3. `uv run ruff check .`  
  4. `uv run pytest`
- Prefer property-based tests (e.g., Hypothesis) to cover edge cases when behavior is non-trivial.
- Log findings from tooling/tests and strengthen specs when failures expose gaps; mutation testing is the follow-up once the suite is green.
- Prefer dataclasses (frozen, slots, kw_only) for internal state; no mutable defaults.
- At every I/O boundary (HTTP, DB rows, env, CLI), call `typingx.as_type(T)` or wrap functions with `@typingx.validate_io(...)`.
- Replace string flags with **`enum.StrEnum`** (or `Literal` if type-only); brand IDs with `NewType`.
- Use `Protocol` for pluggable components; mark overrides with **`typing.override`**.
- Return immutable data (`tuple`, frozen DTOs) unless mutation is required.
- Use `match` + **`typing.assert_never()`** to make exhaustiveness explicit.
- Prefer `Mapping`/`Sequence` in signatures; avoid leaking concrete types.
- Tests must assert that illegal states are unrepresentable (construction/validation fails).
