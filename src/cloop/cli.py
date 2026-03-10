"""Cloop CLI entrypoint.

Purpose:
    Expose the public parser builder and main entrypoint for the packaged CLI.

Responsibilities:
    - Re-export `build_parser` for parser construction
    - Re-export `main` for command execution
    - Provide the `python -m cloop.cli` module entrypoint

Non-scope:
    - Individual command handler implementations
    - Backward-compatibility aliases for test monkeypatching
    - CLI runtime orchestration details

Invariants/Assumptions:
    - Command handlers live under `cloop.cli_package.*`
    - This module stays a thin public entrypoint surface
"""

from __future__ import annotations

from cloop.cli_package.main import build_parser, main

__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
