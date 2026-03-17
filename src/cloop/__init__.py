"""Purpose: Define the lightweight package root for Cloop.

Responsibilities:
    - Expose runtime version metadata at package import time.
    - Keep package-root imports free of FastAPI/app boot side effects.

Scope:
    - Package metadata exports only.
    - No application bootstrap or runtime wiring.

Non-scope:
    - FastAPI app bootstrapping.
    - CLI, storage, or AI runtime imports.

Usage:
    - Import `cloop.__version__` or `from cloop import __version__`.
    - Import `cloop.main.app` or `cloop.main.create_app` for FastAPI access.

Invariants/Assumptions:
    - `import cloop` must stay lightweight.
    - The package root does not re-export the FastAPI app.
"""

from __future__ import annotations

from ._version import __version__

__all__ = ["__version__"]
