"""Shared test helper functions for Cloop test modules.

Purpose:
    Provide small reusable helpers for test-only parsing and assertions.

Responsibilities:
    - Parse command output produced by CLI tests.
    - Keep repeated helper logic out of feature-specific test modules.

Non-scope:
    - Application fixtures, database setup, or feature-specific assertions.

Usage:
    Import directly from tests that need helper functions.

Invariants/Assumptions:
    - Helpers operate only on pytest-captured output or in-memory test data.
    - The helpers do not mutate application state.
"""

from __future__ import annotations

import json
from typing import Any


def last_json_from_stdout(capsys: Any) -> Any:
    """Return the final JSON object written to captured stdout."""
    captured = capsys.readouterr()
    lines = captured.out.strip().split("\n")
    for index in range(len(lines) - 1, -1, -1):
        candidate = "\n".join(lines[index:])
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return json.loads(captured.out)
