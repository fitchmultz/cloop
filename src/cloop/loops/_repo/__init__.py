"""Loop repository internal package marker.

Purpose:
    Declare the internal loop repository package and document its boundary.
Responsibilities:
    - Mark ``cloop.loops._repo`` as an internal-only package.
    - Keep repository implementation details grouped behind the package.
Scope:
    Internal repository helpers used by the loop domain implementation.
Usage:
    Import concrete modules from this package only within loop implementation
    code.
Invariants/Assumptions:
    - This package is private and not part of the supported public API surface.
    - Callers should prefer higher-level loop facades instead of importing this
      package directly.
"""
