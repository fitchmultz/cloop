"""
Natural-language recurrence parsing and rrule generation.

Purpose:
    Parse human-friendly schedule phrases into RFC 5545 RRULE format and
    compute next due dates with timezone/DST awareness.

Responsibilities:
    - Parse natural-language schedule phrases (e.g., "every weekday", "every 2 weeks")
    - Validate and normalize RRULE strings
    - Compute next occurrence dates respecting timezone and DST transitions
    - Convert timezone offsets to IANA timezone names

Non-scope:
    - Date arithmetic outside of recurrence (use datetime directly)
    - Calendar UI or display formatting
    - Recurrence storage or persistence

Invariants:
    - All datetime values are UTC internally
    - RRULE strings are always valid RFC 5545 format after validation
    - Timezone names are valid IANA identifiers
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

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

# Ordinal suffixes for position parsing
ORDINAL_PATTERN = re.compile(r"^(\d+)(?:st|nd|rd|th)?$", re.IGNORECASE)

# Common offset-to-timezone mappings for user convenience
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


@dataclass(frozen=True, slots=True)
class ParsedRecurrence:
    """Result of parsing a natural-language schedule phrase."""

    rrule: str
    description: str


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
    - "every 1st business day" -> FREQ=MONTHLY;BYDAY=1MO (first Monday)
    - "every last friday" -> FREQ=MONTHLY;BYDAY=-1FR

    Args:
        phrase: Natural-language schedule description

    Returns:
        ParsedRecurrence with rrule and description

    Raises:
        ValidationError: If the phrase cannot be parsed
    """
    if not RRULE_AVAILABLE:
        raise RecurrenceError(
            "Recurrence support requires python-dateutil. Install it with: uv add python-dateutil"
        )

    phrase = phrase.strip().lower()
    if not phrase:
        raise RecurrenceError("Schedule phrase cannot be empty")

    # Normalize common variations
    phrase = re.sub(r"\s+", " ", phrase)

    # Remove "every " prefix if present for easier matching
    working = phrase
    if working.startswith("every "):
        working = working[6:]

    # Handle "daily"
    if working in ("day", "daily"):
        return ParsedRecurrence(rrule="FREQ=DAILY", description="Daily")

    # Handle "weekday" / "weekdays" (Monday-Friday)
    if working in ("weekday", "weekdays", "business day"):
        return ParsedRecurrence(
            rrule="FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", description="Every weekday"
        )

    # Handle "weekend" (Saturday-Sunday)
    if working in ("weekend", "weekends"):
        return ParsedRecurrence(rrule="FREQ=WEEKLY;BYDAY=SA,SU", description="Every weekend")

    # Handle "week" / "weekly"
    if working in ("week", "weekly"):
        return ParsedRecurrence(rrule="FREQ=WEEKLY", description="Weekly")

    # Handle "month" / "monthly"
    if working in ("month", "monthly"):
        return ParsedRecurrence(rrule="FREQ=MONTHLY", description="Monthly")

    # Handle "year" / "yearly" / "annual" / "annually"
    if working in ("year", "yearly", "annual", "annually"):
        return ParsedRecurrence(rrule="FREQ=YEARLY", description="Yearly")

    # Match "N weeks" or "N months" or "N days" or "N years"
    interval_match = re.match(r"^(\d+)\s+(day|days|week|weeks|month|months|year|years)$", working)
    if interval_match:
        count = int(interval_match.group(1))
        unit = interval_match.group(2)

        if count < 1:
            raise RecurrenceError(f"Interval must be at least 1, got {count}")

        if unit in ("day", "days"):
            freq = "DAILY"
            desc = f"Every {count} day{'s' if count > 1 else ''}"
        elif unit in ("week", "weeks"):
            freq = "WEEKLY"
            desc = f"Every {count} week{'s' if count > 1 else ''}"
        elif unit in ("month", "months"):
            freq = "MONTHLY"
            desc = f"Every {count} month{'s' if count > 1 else ''}"
        else:  # year/years
            freq = "YEARLY"
            desc = f"Every {count} year{'s' if count > 1 else ''}"

        rrule_str = f"FREQ={freq}"
        if count > 1:
            rrule_str += f";INTERVAL={count}"

        return ParsedRecurrence(rrule=rrule_str, description=desc)

    # Match day names: "monday,wednesday,friday" or "mon wed fri"
    day_pattern = (
        r"^(?:(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|"
        r"thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)[,\s]*)+$"
    )
    if re.match(day_pattern, working):
        # Extract day abbreviations
        days: list[int] = []
        for day_match in re.finditer(
            r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)",
            working,
        ):
            day_name = day_match.group(1)
            if day_name in DAY_MAP:
                day_num = DAY_MAP[day_name]
                if day_num not in days:
                    days.append(day_num)

        if not days:
            raise RecurrenceError(f"Could not parse any valid days from: {phrase}")

        days.sort()
        day_abbrs = [_weekday_to_abbr(d) for d in days]
        return ParsedRecurrence(
            rrule=f"FREQ=WEEKLY;BYDAY={','.join(day_abbrs)}",
            description=f"Every {', '.join(day_abbrs)}",
        )

    # Match ordinal + day: "1st monday", "last friday", "2nd tuesday"
    ordinal_day_pattern = (
        r"^(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last|-?\d+)[,\s]+"
        r"(mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|"
        r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)(?:\s+(?:of\s+)?(?:the\s+)?month)?$"
    )
    ordinal_match = re.match(ordinal_day_pattern, working)
    if ordinal_match:
        pos_str = ordinal_match.group(1)
        day_name = ordinal_match.group(2)

        # Convert position
        position_map = {
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
        if pos_str in position_map:
            pos = position_map[pos_str]
        else:
            pos = int(pos_str)

        if pos < -1 or pos > 5 or pos == 0:
            raise RecurrenceError(f"Invalid ordinal position: {pos_str}")

        day_num = DAY_MAP.get(day_name)
        if day_num is None:
            raise RecurrenceError(f"Unknown day name: {day_name}")

        day_abbr = _weekday_to_abbr(day_num)
        return ParsedRecurrence(
            rrule=f"FREQ=MONTHLY;BYDAY={pos}{day_abbr}",
            description=f"Every {pos_str} {day_name.capitalize()}",
        )

    # Match "Nth business day" / "Nth weekday of month"
    business_day_pattern = (
        r"^(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last|-?\d+)"
        r"[,\s]+(?:business\s+day|weekday)(?:\s+(?:of\s+)?(?:the\s+)?month)?$"
    )
    if re.match(business_day_pattern, working):
        pos_str = re.match(business_day_pattern, working).group(1)  # type: ignore[union-attr]

        position_map = {
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
        if pos_str in position_map:
            pos = position_map[pos_str]
        else:
            pos = int(pos_str)

        # For "Nth business day", we use BYDAY with MO-FR and BYSETPOS
        # FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1 means first business day
        return ParsedRecurrence(
            rrule=f"FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS={pos}",
            description=f"Every {pos_str} business day",
        )

    # Handle raw RRULE strings (pass through with validation)
    if working.upper().startswith("FREQ="):
        return ParsedRecurrence(rrule=working.upper(), description=f"Custom: {working}")

    raise RecurrenceError(f"Could not parse schedule phrase: '{phrase}'")


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
    if not RRULE_AVAILABLE:
        raise RecurrenceError(
            "Recurrence support requires python-dateutil. Install it with: uv add python-dateutil"
        )

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
    if not RRULE_AVAILABLE:
        raise RecurrenceError(
            "Recurrence support requires python-dateutil. Install it with: uv add python-dateutil"
        )

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
    if offset_minutes < -720 or offset_minutes > 840:
        raise RecurrenceError(
            f"Invalid UTC offset: {offset_minutes} minutes. "
            f"Must be between -720 (-12:00) and 840 (+14:00)"
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
