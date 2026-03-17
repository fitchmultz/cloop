"""Public loop-parser facade.

Purpose:
    Expose the canonical `add_loop_parser()` surface while delegating parser
    implementation details to focused internal modules.

Responsibilities:
    - Re-export the public loop parser builder used by parser factory code
    - Keep the public parser surface stable during internal decomposition
    - Make loop parser ownership discoverable without a monolithic file

Scope:
    - Public loop parser facade only

Non-scope:
    - Internal parser-builder implementations
    - CLI command dispatch

Usage:
    - Import `add_loop_parser()` from here when registering the public CLI tree

Invariants/Assumptions:
    - `add_loop_parser()` remains the canonical public entrypoint
    - Internal parser builders live under `cloop.cli_package.parsers._loop`
    - Dispatch-sensitive destination names are preserved by the internal modules
"""

from __future__ import annotations

from ._loop import add_loop_parser

__all__ = ["add_loop_parser"]
