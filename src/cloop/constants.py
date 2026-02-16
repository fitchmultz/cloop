"""Application-wide constants for Cloop.

Purpose:
    Define default values, limits, and magic numbers used across the codebase.

Responsibilities:
    - Define default values for pagination limits
    - Define max length constraints for text fields (single source of truth)
    - Single source of truth for magic constants

Non-scope:
    - Environment-driven configuration (use settings.py)
    - Runtime-modifiable values
"""

DEFAULT_LOOP_LIST_LIMIT: int = 50
DEFAULT_LOOP_NEXT_LIMIT: int = 5

# =============================================================================
# Text field max lengths
# =============================================================================

# Loop text fields
RAW_TEXT_MAX: int = 10000  # Main loop content (about 2-3 pages of text)
TITLE_MAX: int = 500  # Short title
SUMMARY_MAX: int = 1000  # AI-generated summary
DEFINITION_OF_DONE_MAX: int = 2000  # Checklist/criteria
NEXT_ACTION_MAX: int = 500  # Single next action step
PROJECT_MAX: int = 255  # Project name (matches tag length)
BLOCKED_REASON_MAX: int = 1000  # Explanation of blocker
COMPLETION_NOTE_MAX: int = 2000  # Note when closing loop
SCHEDULE_MAX: int = 500  # Natural language recurrence phrase
RRULE_MAX: int = 500  # RFC 5545 RRULE string
TIMEZONE_MAX: int = 64  # IANA timezone name (e.g., "America/New_York")

# Note/comment fields
NOTE_BODY_MAX: int = 50000  # Full note body (about 10-15 pages)
COMMENT_BODY_MAX: int = 10000  # Comment markdown body
AUTHOR_MAX: int = 255  # Comment author / claim owner identifier

# Webhook fields
WEBHOOK_URL_MAX: int = 2048  # URL max length
WEBHOOK_DESCRIPTION_MAX: int = 500

# Chat fields
CHAT_MESSAGE_MAX: int = 50000  # Single chat message

# View/query fields
VIEW_NAME_MAX: int = 255
VIEW_DESCRIPTION_MAX: int = 1000
SEARCH_QUERY_MAX: int = 2000

# Template fields
TEMPLATE_NAME_MAX: int = 100  # Template names are shorter than view names
TEMPLATE_DESCRIPTION_MAX: int = 500  # Matches webhook description length
