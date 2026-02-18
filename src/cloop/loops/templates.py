"""Loop template variable substitution.

Purpose:
    Replace {{variable}} placeholders in template patterns with actual values.

Responsibilities:
    - Parse and substitute date/time variables in {{variable}} format
    - Support multiple datetime formats and timezone offsets
    - Apply templates to generate capture request defaults
    - Extract update fields from applied template results

Non-scope:
    - Does not define or manage templates (templates stored in database)
    - Does not handle user input parsing or CLI interactions
    - Does not persist loop data (handled by database layer)

Supported variables:
    - {{date}}: Current date (YYYY-MM-DD)
    - {{time}}: Current time (HH:MM)
    - {{datetime}}: ISO datetime (YYYY-MM-DDTHH:MM)
    - {{day}}: Day name (Monday, Tuesday, etc.)
    - {{day_short}}: Short day name (Mon, Tue, etc.)
    - {{week}}: ISO week number (1-53)
    - {{month}}: Month name (January, February, etc.)
    - {{month_short}}: Short month name (Jan, Feb, etc.)
    - {{year}}: Full year (2026)
    - {{year_short}}: Short year (26)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

_VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\}\}")

# Day and month name constants (module-level for performance)
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_MONTH_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def substitute_template_variables(
    text: str,
    *,
    now_utc: datetime | None = None,
    tz_offset_min: int = 0,
    additional_vars: dict[str, str] | None = None,
) -> str:
    """Replace {{variable}} placeholders with actual values.

    Args:
        text: Template text containing {{variable}} placeholders
        now_utc: Current UTC datetime (defaults to now)
        tz_offset_min: Timezone offset in minutes for local time display
        additional_vars: Extra variable mappings to support

    Returns:
        Text with all recognized variables substituted
    """
    if not text:
        return text

    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # Calculate local time from UTC + offset
    offset = timedelta(minutes=tz_offset_min)
    local_time = now_utc.replace(tzinfo=timezone.utc).astimezone(timezone(offset))

    # ISO week number (1-53)
    iso_calendar = local_time.isocalendar()
    week_num = iso_calendar[1]

    variables: dict[str, str] = {
        "date": local_time.strftime("%Y-%m-%d"),
        "time": local_time.strftime("%H:%M"),
        "datetime": local_time.strftime("%Y-%m-%dT%H:%M"),
        "day": _DAY_NAMES[local_time.weekday()],
        "day_short": _DAY_SHORT[local_time.weekday()],
        "week": str(week_num),
        "month": _MONTH_NAMES[local_time.month - 1],
        "month_short": _MONTH_SHORT[local_time.month - 1],
        "year": str(local_time.year),
        "year_short": str(local_time.year)[-2:],
    }

    if additional_vars:
        variables.update(additional_vars)

    def replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1).lower()
        return variables.get(var_name, match.group(0))  # Keep original if not found

    return _VARIABLE_PATTERN.sub(replace_var, text)


def apply_template_to_capture(
    *,
    template: dict[str, Any],
    raw_text_override: str | None = None,
    now_utc: datetime | None = None,
    tz_offset_min: int = 0,
) -> dict[str, Any]:
    """Apply a template to produce capture request defaults.

    Args:
        template: Template record from database
        raw_text_override: Optional text to append to pattern (user input)
        now_utc: Current UTC datetime
        tz_offset_min: Timezone offset for variable substitution

    Returns:
        Dict with fields suitable for capture request:
        - raw_text: Substituted pattern + override
        - tags: From defaults
        - time_minutes: From defaults
        - actionable/scheduled/blocked: From defaults
        - etc.
    """
    # Substitute variables in pattern
    pattern = template.get("raw_text_pattern") or ""
    substituted = substitute_template_variables(
        pattern,
        now_utc=now_utc,
        tz_offset_min=tz_offset_min,
    )

    # Combine with user text if provided
    if raw_text_override:
        if substituted:
            raw_text = f"{substituted}\n\n{raw_text_override}"
        else:
            raw_text = raw_text_override
    else:
        raw_text = substituted

    # Parse defaults
    defaults: dict[str, Any] = {}
    defaults_json = template.get("defaults_json")
    if defaults_json:
        if isinstance(defaults_json, str):
            try:
                defaults = json.loads(defaults_json)
            except json.JSONDecodeError:
                defaults = {}
        else:
            defaults = defaults_json

    return {
        "raw_text": raw_text,
        "tags": defaults.get("tags"),
        "title": defaults.get("title"),
        "time_minutes": defaults.get("time_minutes"),
        "activation_energy": defaults.get("activation_energy"),
        "actionable": defaults.get("actionable", False),
        "scheduled": defaults.get("scheduled", False),
        "blocked": defaults.get("blocked", False),
        "project": defaults.get("project"),
        "urgency": defaults.get("urgency"),
        "importance": defaults.get("importance"),
    }


def extract_update_fields_from_template(
    applied: dict[str, Any],
) -> dict[str, Any]:
    """Extract loop update fields from applied template defaults.

    Args:
        applied: Result dict from apply_template_to_capture()

    Returns:
        Dict with only the non-None fields suitable for update_loop()
    """
    update_fields: dict[str, Any] = {}
    if applied.get("tags"):
        update_fields["tags"] = applied["tags"]
    if applied.get("time_minutes") is not None:
        update_fields["time_minutes"] = applied["time_minutes"]
    if applied.get("activation_energy") is not None:
        update_fields["activation_energy"] = applied["activation_energy"]
    if applied.get("urgency") is not None:
        update_fields["urgency"] = applied["urgency"]
    if applied.get("importance") is not None:
        update_fields["importance"] = applied["importance"]
    if applied.get("project"):
        update_fields["project"] = applied["project"]
    return update_fields
