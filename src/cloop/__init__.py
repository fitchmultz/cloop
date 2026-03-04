"""Cloop package public exports.

Purpose:
    Provide stable package-level imports for app bootstrapping and version metadata.

Responsibilities:
    - Expose FastAPI application object for ASGI servers.
    - Expose package version constant for runtime/version reporting.

Non-scope:
    - Application configuration or startup side effects beyond import wiring.
"""

from ._version import __version__
from .main import app

__all__ = ["app", "__version__"]
