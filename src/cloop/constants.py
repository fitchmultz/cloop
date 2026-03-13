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
# HTTP Status Codes
# =============================================================================

HTTP_OK: int = 200
HTTP_CREATED: int = 201
HTTP_BAD_REQUEST: int = 400
HTTP_UNAUTHORIZED: int = 401
HTTP_FORBIDDEN: int = 403
HTTP_NOT_FOUND: int = 404
HTTP_CONFLICT: int = 409
HTTP_UNPROCESSABLE_ENTITY: int = 422
HTTP_INTERNAL_SERVER_ERROR: int = 500
HTTP_BAD_GATEWAY: int = 502
HTTP_SERVICE_UNAVAILABLE: int = 503
HTTP_GATEWAY_TIMEOUT: int = 504

# =============================================================================
# Scheduler/Prioritization Thresholds
# =============================================================================

NUDGE_THRESHOLD_LOW: int = 2
NUDGE_THRESHOLD_HIGH: int = 4
MAX_ESCALATION_LEVEL: int = 2

DUE_SOON_HOURS_DEFAULT: float = 24.0
STALE_HOURS_DEFAULT: float = 72.0
BLOCKED_HOURS_DEFAULT: float = 48.0

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

# Memory fields
MEMORY_KEY_MAX: int = 200
MEMORY_CONTENT_MAX: int = 2000

# View/query fields
VIEW_NAME_MAX: int = 255
VIEW_DESCRIPTION_MAX: int = 1000
SEARCH_QUERY_MAX: int = 2000

# Template fields
TEMPLATE_NAME_MAX: int = 100  # Template names are shorter than view names
TEMPLATE_DESCRIPTION_MAX: int = 500  # Matches webhook description length

# =============================================================================
# Bulk operation limits
# =============================================================================

BULK_OPERATION_MAX_ITEMS: int = 100  # Max items per bulk request

# =============================================================================
# Timezone offset constants
# =============================================================================

# Python's timezone class requires offsets strictly between -24 and +24 hours,
# so we use [-1439, +1439] minutes (exclusive of exactly +/-24h = +/-1440min)
# Used for: captured_tz_offset_min field validation in validate_tz_offset()
MIN_TZ_OFFSET_MIN: int = -1439
MAX_TZ_OFFSET_MIN: int = 1439

# IANA timezone range for RRULE/recurrence calculations
# Real-world timezones range from UTC-12 (Baker Island) to UTC+14 (Line Islands)
# Used for: offset_minutes_to_timezone() in recurrence.py
RRULE_MIN_TZ_OFFSET_MIN: int = -720  # -12 hours
RRULE_MAX_TZ_OFFSET_MIN: int = 840  # +14 hours

# Common offset-to-timezone mappings for user convenience
# Keys must be within [RRULE_MIN_TZ_OFFSET_MIN, RRULE_MAX_TZ_OFFSET_MIN] range
OFFSET_TO_TIMEZONE: dict[int, str] = {
    -720: "Etc/GMT+12",  # UTC-12
    -660: "Etc/GMT+11",  # UTC-11
    -600: "Etc/GMT+10",  # UTC-10 (HAST)
    -540: "Etc/GMT+9",  # UTC-9 (AKST)
    -480: "America/Los_Angeles",  # UTC-8 (PST)
    -420: "America/Denver",  # UTC-7 (MST)
    -360: "America/Chicago",  # UTC-6 (CST)
    -300: "America/New_York",  # UTC-5 (EST)
    -240: "America/Halifax",  # UTC-4 (AST)
    -180: "America/Sao_Paulo",  # UTC-3
    -120: "Etc/GMT+2",  # UTC-2
    -60: "Etc/GMT+1",  # UTC-1
    0: "UTC",  # UTC
    60: "Etc/GMT-1",  # UTC+1 (CET)
    120: "Europe/Berlin",  # UTC+2 (CEST - in summer)
    180: "Europe/Moscow",  # UTC+3
    210: "Asia/Tehran",  # UTC+3:30
    240: "Asia/Dubai",  # UTC+4
    270: "Asia/Kabul",  # UTC+4:30
    300: "Asia/Karachi",  # UTC+5
    330: "Asia/Kolkata",  # UTC+5:30
    345: "Asia/Kathmandu",  # UTC+5:45
    360: "Asia/Dhaka",  # UTC+6
    390: "Asia/Yangon",  # UTC+6:30
    420: "Asia/Bangkok",  # UTC+7
    480: "Asia/Shanghai",  # UTC+8
    540: "Asia/Tokyo",  # UTC+9
    570: "Australia/Adelaide",  # UTC+9:30
    600: "Australia/Sydney",  # UTC+10
    630: "Australia/Lord_Howe",  # UTC+10:30
    660: "Pacific/Noumea",  # UTC+11
    720: "Pacific/Auckland",  # UTC+12
    765: "Pacific/Chatham",  # UTC+12:45
    780: "Pacific/Tongatapu",  # UTC+13
    840: "Pacific/Kiritimati",  # UTC+14
}
