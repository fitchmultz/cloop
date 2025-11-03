## Must-Know Workflow for Codex CLI Agents

- Keep it simple; never repeat yourself. Python is managed via `pyproject.toml` + `uv`. No `pip`.
- Work in Python 3.13 (match `pyproject.toml`). Always use `uv` commands: `uv sync --dev`, `uv run <tool>`.
- Follow executable-spec first (TDD/ATDD): write or update a failing test/spec before coding, then red→green→refactor.
- Keep changes small (trunk-based mindset). Run the guardrails on every iteration:  
  1. `uv run basedpyright`  
  2. `uv run ruff format .` (if formatting needed)  
  3. `uv run ruff check .`  
  4. `uv run pytest`
- Prefer property-based tests (e.g., Hypothesis) to cover edge cases when behavior is non-trivial.
- Log findings from tooling/tests and strengthen specs when failures expose gaps; mutation testing is the follow-up once the suite is green.
