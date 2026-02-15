"""Application-wide constants for Cloop.

Purpose:
    Define default values and magic numbers used across the codebase.

Responsibilities:
    - Define default values for pagination limits
    - Single source of truth for magic constants

Non-scope:
    - Environment-driven configuration (use settings.py)
    - Runtime-modifiable values
"""

DEFAULT_LOOP_LIST_LIMIT: int = 50
DEFAULT_LOOP_NEXT_LIMIT: int = 5
