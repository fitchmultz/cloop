"""CLI command and parser modules.

Purpose:
    Expose CLI components from the cli package.

Responsibilities:
    - Re-export main CLI entry point and parser builder

Non-scope:
    - CLI implementation details (see submodules)
"""

from .main import build_parser, main

__all__ = ["build_parser", "main"]
