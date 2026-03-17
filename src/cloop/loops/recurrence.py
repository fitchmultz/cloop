"""Natural-language recurrence parsing and RRULE utilities.

Purpose:
    Parse human-friendly schedule phrases into RFC 5545 RRULE format and
    compute next due dates with timezone/DST awareness.

Responsibilities:
    - Parse natural-language schedule phrases (for example `every weekday` or
      `every 2 weeks`)
    - Validate and normalize RRULE strings
    - Compute next occurrence dates respecting timezone and DST transitions
    - Convert timezone offsets to IANA timezone names

Scope:
    - Recurrence parsing, validation, and next-occurrence computation
    - Timezone-name validation for recurrence scheduling

Non-scope:
    - Date arithmetic outside of recurrence workflows
    - Calendar UI or display formatting
    - Recurrence persistence concerns

Usage:
    - Call `parse_recurrence_schedule(...)` for human-friendly schedule input.
    - Call `validate_rrule(...)` and `compute_next_due(...)` for RRULE-backed
      recurrence workflows.

Invariants/Assumptions:
    - All datetime values are UTC internally.
    - RRULE strings are valid RFC 5545 after validation.
    - Timezone names are valid IANA identifiers when accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..constants import (
    OFFSET_TO_TIMEZONE,
    RRULE_MAX_TZ_OFFSET_MIN,
    RRULE_MIN_TZ_OFFSET_MIN,
)
from .errors import RecurrenceError

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

try:
    from dateutil.rrule import (
        DAILY,
        FR,
        MO,
        MONTHLY,
        SA,
        SU,
        TH,
        TU,
        WE,
        WEEKLY,
        YEARLY,
        rrulestr,
    )

    RRULE_AVAILABLE = True
except ImportError:
    RRULE_AVAILABLE = False
    # Create placeholder values for type checking
    MO = TU = WE = TH = FR = SA = SU = None  # type: ignore[misc]
    DAILY = WEEKLY = MONTHLY = YEARLY = None

# Day name to weekday number mapping (Monday=0, Sunday=6)
DAY_MAP: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "m": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "t": 1,
    "wednesday": 2,
    "wed": 2,
    "w": 2,
    "thursday": 3,
    "thu": 3,
    "thurs": 3,
    "r": 3,
    "friday": 4,
    "fri": 4,
    "f": 4,
    "saturday": 5,
    "sat": 5,
    "s": 5,
    "sunday": 6,
    "sun": 6,
    "u": 6,
}


@dataclass(frozen=True, slots=True)
class ParsedRecurrence:
    """Result of parsing a natural-language schedule phrase."""

    rrule: str
    description: str


NAMED_RECURRENCE_MAP: dict[str, tuple[str, str]] = {
    "day": ("FREQ=DAILY", "Daily"),
    "daily": ("FREQ=DAILY", "Daily"),
    "weekday": ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "Every weekday"),
    "weekdays": ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "Every weekday"),
    "business day": ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "Every weekday"),
    "weekend": ("FREQ=WEEKLY;BYDAY=SA,SU", "Every weekend"),
    "weekends": ("FREQ=WEEKLY;BYDAY=SA,SU", "Every weekend"),
    "week": ("FREQ=WEEKLY", "Weekly"),
    "weekly": ("FREQ=WEEKLY", "Weekly"),
    "month": ("FREQ=MONTHLY", "Monthly"),
    "monthly": ("FREQ=MONTHLY", "Monthly"),
    "year": ("FREQ=YEARLY", "Yearly"),
    "yearly": ("FREQ=YEARLY", "Yearly"),
    "annual": ("FREQ=YEARLY", "Yearly"),
    "annually": ("FREQ=YEARLY", "Yearly"),
}
POSITION_MAP: dict[str, int] = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "last": -1,
}
INTERVAL_PATTERN = re.compile(r"^(\d+)\s+(day|days|week|weeks|month|months|year|years)$")
DAY_LIST_PATTERN = re.compile(
    r"^(?:(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|"
    r"thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)[,\s]*)+$"
)
DAY_NAME_TOKEN_PATTERN = re.compile(
    r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|"
    r"thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
)
ORDINAL_DAY_PATTERN = re.compile(
    r"^(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last|-?\d+)[,\s]+"
    r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|"
    r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)(?:\s+(?:of\s+)?(?:the\s+)?month)?$"
)
BUSINESS_DAY_PATTERN = re.compile(
    r"^(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last|-?\d+)"
    r"[,\s]+(?:business\s+day|weekday)(?:\s+(?:of\s+)?(?:the\s+)?month)?$"
)


def parse_recurrence_schedule(phrase: str) -> ParsedRecurrence:
    """
    Parse a natural-language schedule phrase into an RRULE string.

    Supported formats:
    - "every day" -> FREQ=DAILY
    - "every weekday" -> FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
    - "every week" / "weekly" -> FREQ=WEEKLY
    - "every N weeks" -> FREQ=WEEKLY;INTERVAL=N
    - "every month" / "monthly" -> FREQ=MONTHLY
    - "every N months" -> FREQ=MONTHLY;INTERVAL=N
    - "every year" / "yearly" / "annually" -> FREQ=YEARLY
    - "every monday,wednesday,friday" -> FREQ=WEEKLY;BYDAY=MO,WE,FR
    - "every 1st business day" -> FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1
    - "every last friday" -> FREQ=MONTHLY;BYDAY=-1FR

    Args:
        phrase: Natural-language schedule description

    Returns:
        ParsedRecurrence with rrule and description

    Raises:
        RecurrenceError: If the phrase cannot be parsed
    """
    _require_rrule_support()
    normalized_phrase = _normalize_schedule_phrase(phrase)
    working_phrase = _remove_every_prefix(normalized_phrase)

    for parser in (
        _parse_named_recurrence,
        _parse_interval_recurrence,
        _parse_day_list_recurrence,
        _parse_ordinal_day_recurrence,
        _parse_business_day_recurrence,
        _parse_raw_rrule_recurrence,
    ):
        parsed = parser(working_phrase)
        if parsed is not None:
            return parsed

    raise RecurrenceError(f"Could not parse schedule phrase: '{normalized_phrase}'")


def _require_rrule_support() -> None:
    """Raise the canonical error when python-dateutil recurrence support is unavailable."""
    if not RRULE_AVAILABLE:
        raise RecurrenceError(
            "Recurrence support requires python-dateutil. Install it with: uv add python-dateutil"
        )


def _normalize_schedule_phrase(phrase: str) -> str:
    """Trim, lowercase, and collapse whitespace in one schedule phrase."""
    normalized_phrase = re.sub(r"\s+", " ", phrase.strip().lower())
    if not normalized_phrase:
        raise RecurrenceError("Schedule phrase cannot be empty")
    return normalized_phrase


def _remove_every_prefix(phrase: str) -> str:
    """Strip an optional leading `every ` prefix for simpler parser matching."""
    if phrase.startswith("every "):
        return phrase[6:]
    return phrase


def _parse_named_recurrence(phrase: str) -> ParsedRecurrence | None:
    """Parse direct named schedules like `daily`, `weekly`, or `weekend`."""
    mapping = NAMED_RECURRENCE_MAP.get(phrase)
    if mapping is None:
        return None
    rrule, description = mapping
    return ParsedRecurrence(rrule=rrule, description=description)


def _parse_interval_recurrence(phrase: str) -> ParsedRecurrence | None:
    """Parse interval schedules like `2 weeks` or `3 months`."""
    interval_match = INTERVAL_PATTERN.match(phrase)
    if interval_match is None:
        return None

    count = int(interval_match.group(1))
    unit = interval_match.group(2)
    if count < 1:
        raise RecurrenceError(f"Interval must be at least 1, got {count}")

    if unit in ("day", "days"):
        freq = "DAILY"
        description = _pluralized_description(count=count, unit="day")
    elif unit in ("week", "weeks"):
        freq = "WEEKLY"
        description = _pluralized_description(count=count, unit="week")
    elif unit in ("month", "months"):
        freq = "MONTHLY"
        description = _pluralized_description(count=count, unit="month")
    else:
        freq = "YEARLY"
        description = _pluralized_description(count=count, unit="year")

    interval_suffix = f";INTERVAL={count}" if count > 1 else ""
    return ParsedRecurrence(rrule=f"FREQ={freq}{interval_suffix}", description=description)


def _parse_day_list_recurrence(phrase: str) -> ParsedRecurrence | None:
    """Parse comma- or space-delimited weekday lists into BYDAY schedules."""
    if DAY_LIST_PATTERN.match(phrase) is None:
        return None

    day_numbers: list[int] = []
    for day_match in DAY_NAME_TOKEN_PATTERN.finditer(phrase):
        day_name = day_match.group(1)
        day_number = DAY_MAP.get(day_name)
        if day_number is not None and day_number not in day_numbers:
            day_numbers.append(day_number)

    if not day_numbers:
        raise RecurrenceError(f"Could not parse any valid days from: {phrase}")

    day_abbreviations = [_weekday_to_abbr(day_number) for day_number in sorted(day_numbers)]
    return ParsedRecurrence(
        rrule=f"FREQ=WEEKLY;BYDAY={','.join(day_abbreviations)}",
        description=f"Every {', '.join(day_abbreviations)}",
    )


def _parse_ordinal_day_recurrence(phrase: str) -> ParsedRecurrence | None:
    """Parse schedules like `1st monday` or `last friday`."""
    ordinal_match = ORDINAL_DAY_PATTERN.match(phrase)
    if ordinal_match is None:
        return None

    position_token, day_name = ordinal_match.groups()
    position = _parse_position_token(position_token)

    day_number = DAY_MAP.get(day_name)
    if day_number is None:
        raise RecurrenceError(f"Unknown day name: {day_name}")

    day_abbreviation = _weekday_to_abbr(day_number)
    return ParsedRecurrence(
        rrule=f"FREQ=MONTHLY;BYDAY={position}{day_abbreviation}",
        description=f"Every {position_token} {day_name.capitalize()}",
    )


def _parse_business_day_recurrence(phrase: str) -> ParsedRecurrence | None:
    """Parse schedules like `1st business day` or `last weekday of month`."""
    business_day_match = BUSINESS_DAY_PATTERN.match(phrase)
    if business_day_match is None:
        return None

    position_token = business_day_match.group(1)
    position = _parse_position_token(position_token)
    return ParsedRecurrence(
        rrule=f"FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS={position}",
        description=f"Every {position_token} business day",
    )


def _parse_raw_rrule_recurrence(phrase: str) -> ParsedRecurrence | None:
    """Accept raw RRULE phrases after validating them eagerly."""
    if not phrase.upper().startswith("FREQ="):
        return None

    rrule = phrase.upper()
    validate_rrule(rrule)
    return ParsedRecurrence(rrule=rrule, description=f"Custom: {rrule}")


def _pluralized_description(*, count: int, unit: str) -> str:
    """Build one `Every N unit(s)` recurrence description."""
    suffix = "s" if count != 1 else ""
    return f"Every {count} {unit}{suffix}"


def _parse_position_token(position_token: str) -> int:
    """Parse and validate one ordinal position token used in monthly schedules."""
    if position_token in POSITION_MAP:
        position = POSITION_MAP[position_token]
    else:
        position = int(position_token)

    if position < -1 or position > 5 or position == 0:
        raise RecurrenceError(f"Invalid ordinal position: {position_token}")
    return position


def validate_rrule(rrule_str: str) -> str:
    """
    Validate and normalize an RRULE string.

    Args:
        rrule_str: RRULE string to validate

    Returns:
        Normalized RRULE string (uppercase, trimmed)

    Raises:
        ValidationError: If the RRULE is invalid
    """
    _require_rrule_support()

    if not rrule_str or not rrule_str.strip():
        raise RecurrenceError("RRULE cannot be empty")

    rrule_str = rrule_str.strip().upper()

    # Allow both bare FREQ= and DTSTART-prefixed forms
    if not (rrule_str.startswith("FREQ=") or rrule_str.startswith("DTSTART:")):
        raise RecurrenceError("RRULE must contain FREQ=")

    # Check for FREQ= anywhere in the string (handles DTSTART prefix)
    if "FREQ=" not in rrule_str:
        raise RecurrenceError("RRULE must contain FREQ=")

    try:
        # Try to parse it to validate
        rule = rrulestr(rrule_str)
        # Return normalized form
        return str(rule).upper()
    except (ValueError, TypeError) as e:
        raise RecurrenceError(f"Invalid RRULE '{rrule_str}': {e}") from e


def compute_next_due(
    rrule: str,
    timezone_name: str,
    after_utc: datetime,
) -> datetime | None:
    """
    Compute the next occurrence date after a given datetime.

    This function respects timezone and DST boundaries. The returned
    datetime is always in UTC.

    Args:
        rrule: Valid RRULE string
        timezone_name: IANA timezone name (e.g., "America/New_York")
        after_utc: Reference datetime in UTC (exclusive; result must be after this)

    Returns:
        Next occurrence datetime in UTC, or None if no more occurrences

    Raises:
        ValidationError: If RRULE or timezone is invalid
    """
    _require_rrule_support()

    # Validate timezone
    if not is_valid_timezone(timezone_name):
        raise RecurrenceError(f"Invalid timezone: {timezone_name}")

    # Validate and normalize RRULE
    rrule = validate_rrule(rrule)

    # Get the timezone object
    from zoneinfo import ZoneInfo

    tz: ZoneInfo = ZoneInfo(timezone_name)

    # Convert the after_utc to the local timezone for rrule computation
    # RRULE should be evaluated in local time to handle DST correctly
    after_local = after_utc.astimezone(tz)

    try:
        rule = rrulestr(rrule)

        # Strip timezone info from after_local for comparison
        # rrulestr returns naive datetimes
        after_naive = after_local.replace(tzinfo=None)

        # Get next occurrence after the local time
        # Use after= parameter with a timedelta to ensure we get the NEXT occurrence
        next_naive = rule.after(after_naive, inc=False)

        if next_naive is None:
            return None

        # The result is naive, so localize it assuming it's in the local timezone
        next_local = next_naive.replace(tzinfo=tz)

        return next_local.astimezone(timezone.utc)

    except (ValueError, TypeError) as e:
        raise RecurrenceError(f"Error computing next occurrence: {e}") from e


def is_valid_timezone(timezone_name: str) -> bool:
    """
    Check if a string is a valid IANA timezone name.

    Args:
        timezone_name: Timezone name to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        from zoneinfo import available_timezones

        # Special case for UTC
        if timezone_name.upper() == "UTC":
            return True

        # Check against available timezones
        return timezone_name in available_timezones()
    except ImportError:
        # Fallback: accept common patterns
        return (
            timezone_name.upper() == "UTC"
            or "/" in timezone_name  # IANA names contain slashes
            or timezone_name.startswith("Etc/GMT")
        )


def offset_minutes_to_timezone(offset_minutes: int) -> str:
    """
    Convert a UTC offset in minutes to an IANA timezone name.

    Uses common timezone mappings where possible (e.g., -480 -> America/Los_Angeles).
    Falls back to Etc/GMT format for uncommon offsets.

    Args:
        offset_minutes: UTC offset in minutes (positive = east of UTC)

    Returns:
        IANA timezone name

    Raises:
        ValidationError: If offset is out of valid range (-12 to +14 hours)
    """
    # Validate range (-12 hours to +14 hours)
    if not (RRULE_MIN_TZ_OFFSET_MIN <= offset_minutes <= RRULE_MAX_TZ_OFFSET_MIN):
        raise RecurrenceError(
            f"Invalid UTC offset: {offset_minutes} minutes. "
            f"Must be between {RRULE_MIN_TZ_OFFSET_MIN} "
            f"({RRULE_MIN_TZ_OFFSET_MIN // 60}:00) "
            f"and {RRULE_MAX_TZ_OFFSET_MIN} (+{RRULE_MAX_TZ_OFFSET_MIN // 60}:00)"
        )

    # Check for common mappings
    if offset_minutes in OFFSET_TO_TIMEZONE:
        return OFFSET_TO_TIMEZONE[offset_minutes]

    # Fall back to Etc/GMT format
    # Note: Etc/GMT signs are inverted from conventional usage
    # Etc/GMT+5 = UTC-5, Etc/GMT-5 = UTC+5
    hours = abs(offset_minutes) // 60
    minutes = abs(offset_minutes) % 60

    if offset_minutes >= 0:
        # East of UTC -> Etc/GMT-N (inverted)
        sign = "-"
    else:
        # West of UTC -> Etc/GMT+N (inverted)
        sign = "+"

    if minutes == 0:
        return f"Etc/GMT{sign}{hours}"
    else:
        return f"Etc/GMT{sign}{hours}:{minutes:02d}"


def describe_rrule(rrule_str: str) -> str:
    """
    Generate a human-readable description of an RRULE.

    Args:
        rrule_str: Valid RRULE string

    Returns:
        Human-readable description
    """
    try:
        parsed = parse_recurrence_schedule(rrule_str)
        return parsed.description
    except RecurrenceError:
        # If we can't parse it, return a generic description
        return f"Recurring: {rrule_str}"


def _weekday_to_abbr(weekday: int) -> str:
    """Convert weekday number (0=Monday) to RRULE abbreviation."""
    abbrs = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
    if 0 <= weekday <= 6:
        return abbrs[weekday]
    raise RecurrenceError(f"Invalid weekday number: {weekday}")
