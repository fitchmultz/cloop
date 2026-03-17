"""Public CLI entrypoint orchestration for Cloop.

Purpose:
    Provide the packaged `cloop` parser builder and main entrypoint while
    keeping parser construction and command dispatch in focused helper modules.

Responsibilities:
    - Expose the canonical `build_parser()` surface for tests and entrypoints
    - Parse CLI arguments and initialize shared settings/database state
    - Delegate command routing to the shared dispatch tree

Scope:
    - CLI startup orchestration only
    - Public re-export surface for parser creation and command execution

Non-scope:
    - Command parser construction details
    - Command-dispatch tree definitions
    - Command handler business logic

Usage:
    - `main(argv)` runs the CLI and returns a process exit code.
    - `build_parser()` returns the full argparse tree for inspection or tests.

Invariants/Assumptions:
    - Database initialization happens before command dispatch.
    - Parser construction and dispatch stay outside this module.
    - Exit code `0` means success, `1` means validation/input error, and `2`
      means not found or invalid transition.
"""

from __future__ import annotations

from .. import db
from ..settings import Settings, get_settings
from .dispatch import dispatch_command
from .parser_factory import build_parser


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    settings: Settings = get_settings()

    db.init_databases(settings)
    return dispatch_command(parser=parser, args=args, settings=settings)


__all__ = ["build_parser", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
