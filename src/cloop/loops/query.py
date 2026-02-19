"""Loop query DSL parser and SQL compiler.

Purpose:
    Provides a safe, parameterized query language for filtering loops
    across all product surfaces (HTTP API, CLI, MCP, Web UI).

Supported terms:
    - status:<value> where value in {open, all, inbox, actionable,
      blocked, scheduled, completed, dropped}
    - tag:<value>
    - project:<value>
    - due:<value> where value in {today, tomorrow, overdue, none, next7d}
      OR due:on:<YYYY-MM-DD>
      OR due:before:<YYYY-MM-DD>
      OR due:after:<YYYY-MM-DD>
      OR due:between:<YYYY-MM-DD>..<YYYY-MM-DD>
    - text:<value>
    - Bare tokens without field: prefix are treated as text:<token>

Semantics:
    - Different fields combine with AND
    - Repeated status: terms combine with OR
    - Repeated tag: terms combine with OR
    - Repeated project: terms combine with OR
    - Repeated text:/bare terms combine with AND; matches raw_text,
      title, summary, next_action
    - Multiple due: terms (keywords and/or date predicates) OR together

Responsibilities:
    - Tokenize DSL safely (support quoted values)
    - Parse into typed AST (LoopQuery)
    - Compile to parameterized SQL fragments (no raw interpolation)

Non-scope:
    - Full-text search with stemming/ranking
    - Complex boolean expressions with parentheses/negation
    - Custom field extensions

Invariants:
    - All field names come from _ALLOWED_FIELDS allowlist
    - All status values come from _ALLOWED_STATUSES allowlist
    - All due values come from _ALLOWED_DUE_VALUES allowlist or are
      validated ISO 8601 date strings
    - SQL is strictly parameterized (never interpolate user values)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .errors import ValidationError

_ALLOWED_FIELDS = frozenset({"status", "tag", "project", "due", "text", "recurring"})
_ALLOWED_STATUSES = frozenset(
    {"open", "all", "inbox", "actionable", "blocked", "scheduled", "completed", "dropped"}
)
_OPEN_STATUSES = frozenset({"inbox", "actionable", "blocked", "scheduled"})
_ALLOWED_DUE_VALUES = frozenset({"today", "tomorrow", "overdue", "none", "next7d"})
_ALLOWED_RECURRING_VALUES = frozenset({"yes", "no", "true", "false", "1", "0"})

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@dataclass(frozen=True, slots=True)
class DueDateFilter:
    """A structured due date predicate with operator and date(s)."""

    operator: Literal["on", "before", "after", "between"]
    date: str  # ISO 8601 date for on/before/after
    date_end: str | None = None  # ISO 8601 date for between (inclusive end)


@dataclass(frozen=True, slots=True)
class LoopQuery:
    """Parsed loop query AST.

    All tuples are normalized: lowercase, stripped, deduplicated.
    """

    statuses: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    due_filters: tuple[str, ...] = ()  # Keep for backwards compat (today, tomorrow, etc.)
    due_date_filters: tuple[DueDateFilter, ...] = ()  # Structured date predicates
    text_terms: tuple[str, ...] = ()
    recurring: bool | None = None


def _tokenize(raw: str) -> list[tuple[str, str]]:
    """Tokenize raw query string into (field, value) pairs.

    Supports:
        - field:value (unquoted)
        - field:"quoted value with spaces"
        - bare_token (treated as text:bare_token)

    Returns:
        List of (field, value) tuples, all lowercase

    Raises:
        ValidationError: On unclosed quotes or empty field/value
    """
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(raw)

    while i < n:
        if raw[i].isspace():
            i += 1
            continue

        if raw[i] == '"':
            j = i + 1
            while j < n and raw[j] != '"':
                j += 1
            if j >= n:
                raise ValidationError("query", "unclosed double quote")
            value = raw[i + 1 : j].strip()
            if not value:
                raise ValidationError("query", "empty quoted value")
            tokens.append(("text", value.lower()))
            i = j + 1
            continue

        j = i
        in_quotes = False
        while j < n:
            if raw[j] == '"':
                in_quotes = not in_quotes
            elif raw[j].isspace() and not in_quotes:
                break
            j += 1

        segment = raw[i:j]
        colon_pos = segment.find(":")

        if colon_pos > 0:
            field_part = segment[:colon_pos].lower()
            value_part = segment[colon_pos + 1 :]

            if not field_part:
                raise ValidationError("query", "empty field name before colon")

            if value_part.startswith('"'):
                if not value_part.endswith('"') or len(value_part) < 2:
                    raise ValidationError("query", "unclosed double quote")
                value_part = value_part[1:-1]

            if not value_part:
                raise ValidationError("query", f"empty value for {field_part}:")

            tokens.append((field_part, value_part.lower()))
        elif colon_pos == 0:
            raise ValidationError("query", "empty field name before colon")
        else:
            if segment:
                tokens.append(("text", segment.lower()))

        i = j

    return tokens


def _parse_iso_date(value: str) -> str:
    """Validate and normalize an ISO 8601 date string.

    Returns the validated date string (YYYY-MM-DD).
    Raises ValidationError if invalid.
    """
    if not _DATE_RE.match(value):
        raise ValidationError("query", f"invalid date '{value}' (expected YYYY-MM-DD format)")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as e:
        raise ValidationError("query", f"invalid date '{value}': {e}") from None
    return value


def parse_loop_query(raw: str) -> LoopQuery:
    """Parse raw query string into LoopQuery AST.

    Args:
        raw: Raw query string (e.g., 'status:inbox tag:work due:today meeting')

    Returns:
        LoopQuery AST with normalized, deduplicated terms

    Raises:
        ValidationError: On unknown fields, invalid status/due values, or syntax errors
    """
    if not raw or not raw.strip():
        raise ValidationError("query", "query string cannot be empty")

    tokens = _tokenize(raw)

    statuses: set[str] = set()
    tags: set[str] = set()
    projects: set[str] = set()
    due_filters: set[str] = set()
    due_date_filters: list[DueDateFilter] = []
    text_terms: set[str] = set()
    recurring: bool | None = None

    for field_name, value in tokens:
        if field_name not in _ALLOWED_FIELDS:
            raise ValidationError(
                "query",
                f"unknown field '{field_name}' (allowed: {', '.join(sorted(_ALLOWED_FIELDS))})",
            )

        if field_name == "status":
            if value not in _ALLOWED_STATUSES:
                allowed = ", ".join(sorted(_ALLOWED_STATUSES))
                raise ValidationError("query", f"invalid status '{value}' (allowed: {allowed})")
            statuses.add(value)
        elif field_name == "tag":
            tags.add(value)
        elif field_name == "project":
            projects.add(value)
        elif field_name == "due":
            # Check for new date operators first
            if value.startswith("on:"):
                date_str = _parse_iso_date(value[3:])
                due_date_filters.append(DueDateFilter(operator="on", date=date_str))
            elif value.startswith("before:"):
                date_str = _parse_iso_date(value[7:])
                due_date_filters.append(DueDateFilter(operator="before", date=date_str))
            elif value.startswith("after:"):
                date_str = _parse_iso_date(value[6:])
                due_date_filters.append(DueDateFilter(operator="after", date=date_str))
            elif value.startswith("between:"):
                range_part = value[8:]
                if ".." not in range_part:
                    raise ValidationError(
                        "query",
                        f"invalid between syntax '{value}' (expected due:between:START..END)",
                    )
                start_str, end_str = range_part.split("..", 1)
                start_date = _parse_iso_date(start_str)
                end_date = _parse_iso_date(end_str)
                if start_date > end_date:
                    raise ValidationError(
                        "query",
                        f"invalid date range: start ({start_date}) after end ({end_date})",
                    )
                due_date_filters.append(
                    DueDateFilter(operator="between", date=start_date, date_end=end_date)
                )
            elif value in _ALLOWED_DUE_VALUES:
                # Existing keyword filters
                due_filters.add(value)
            else:
                allowed = ", ".join(sorted(_ALLOWED_DUE_VALUES))
                raise ValidationError(
                    "query",
                    f"invalid due filter '{value}' (keywords: {allowed}; "
                    "or use on:/before:/after:/between: with YYYY-MM-DD dates)",
                )
        elif field_name == "text":
            text_terms.add(value)
        elif field_name == "recurring":
            if value not in _ALLOWED_RECURRING_VALUES:
                raise ValidationError(
                    "query",
                    f"invalid recurring filter '{value}' (allowed: yes, no)",
                )
            recurring = value in ("yes", "true", "1")

    return LoopQuery(
        statuses=tuple(sorted(statuses)),
        tags=tuple(sorted(tags)),
        projects=tuple(sorted(projects)),
        due_filters=tuple(sorted(due_filters)),
        due_date_filters=tuple(due_date_filters),
        text_terms=tuple(sorted(text_terms)),
        recurring=recurring,
    )


def _start_of_day_utc(now_utc: datetime) -> datetime:
    """Return start of current day in UTC."""
    return now_utc.replace(hour=0, minute=0, second=0, microsecond=0)


def _escape_like_pattern(term: str) -> str:
    """Escape SQL LIKE wildcards in a search term."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def compile_loop_query(query: LoopQuery, *, now_utc: datetime) -> tuple[str, list[object]]:
    """Compile LoopQuery to parameterized SQL WHERE clause.

    Args:
        query: Parsed LoopQuery AST
        now_utc: Current UTC datetime (for due filter computation)

    Returns:
        Tuple of (where_sql, params) where:
        - where_sql: SQL fragment starting with "WHERE" or empty string
        - params: List of parameter values for placeholders

    Notes:
        - Repeated status: terms combine with OR (IN clause)
        - Repeated tag: terms combine with OR via EXISTS subquery
        - Repeated project: terms combine with OR (IN clause on projects.name)
        - Repeated text:/bare terms combine with AND across terms
        - Each text term matches any of (raw_text, title, summary, next_action) with LIKE
        - status:open expands to the 4 open statuses
        - status:all is ignored (no status filter)
    """
    conditions: list[str] = []
    params: list[object] = []

    status_values = list(query.statuses)

    if "all" in status_values:
        status_values = [s for s in status_values if s != "all"]

    if "open" in status_values:
        status_values = [s for s in status_values if s != "open"]
        status_values.extend(_OPEN_STATUSES)

    status_values = sorted(set(status_values))

    if status_values:
        placeholders = ", ".join("?" for _ in status_values)
        conditions.append(f"loops.status IN ({placeholders})")
        params.extend(status_values)

    if query.tags:
        tag_conditions: list[str] = []
        for tag in query.tags:
            tag_conditions.append(
                "EXISTS (SELECT 1 FROM loop_tags lt JOIN tags t ON t.id = lt.tag_id "
                "WHERE lt.loop_id = loops.id AND LOWER(t.name) = ?)"
            )
            params.append(tag)
        conditions.append(f"({' OR '.join(tag_conditions)})")

    if query.projects:
        placeholders = ", ".join("?" for _ in query.projects)
        conditions.append(f"LOWER(projects.name) IN ({placeholders})")
        params.extend(query.projects)

    # Handle due filters (both keyword and date-based)
    due_conditions: list[str] = []
    if query.due_filters:
        start_of_today = _start_of_day_utc(now_utc)
        start_of_tomorrow = start_of_today + timedelta(days=1)
        start_of_day_after = start_of_today + timedelta(days=2)
        start_of_next_week = now_utc + timedelta(days=7)

        for due_filter in query.due_filters:
            if due_filter == "today":
                due_conditions.append("(loops.due_at_utc >= ? AND loops.due_at_utc < ?)")
                params.extend([start_of_today.isoformat(), start_of_tomorrow.isoformat()])
            elif due_filter == "tomorrow":
                due_conditions.append("(loops.due_at_utc >= ? AND loops.due_at_utc < ?)")
                params.extend([start_of_tomorrow.isoformat(), start_of_day_after.isoformat()])
            elif due_filter == "overdue":
                due_conditions.append("(loops.due_at_utc IS NOT NULL AND loops.due_at_utc < ?)")
                params.append(now_utc.isoformat())
            elif due_filter == "none":
                due_conditions.append("loops.due_at_utc IS NULL")
            elif due_filter == "next7d":
                due_conditions.append("(loops.due_at_utc >= ? AND loops.due_at_utc < ?)")
                params.extend([now_utc.isoformat(), start_of_next_week.isoformat()])

    # Handle structured date predicates
    if query.due_date_filters:
        for df in query.due_date_filters:
            if df.operator == "on":
                # Due on this date (start of day to end of day)
                date_start = f"{df.date}T00:00:00Z"
                date_end = f"{df.date}T23:59:59.999999Z"
                due_conditions.append("(loops.due_at_utc >= ? AND loops.due_at_utc <= ?)")
                params.extend([date_start, date_end])
            elif df.operator == "before":
                # Due before start of this date
                date_start = f"{df.date}T00:00:00Z"
                due_conditions.append("(loops.due_at_utc < ?)")
                params.append(date_start)
            elif df.operator == "after":
                # Due after end of this date
                date_end = f"{df.date}T23:59:59.999999Z"
                due_conditions.append("(loops.due_at_utc > ?)")
                params.append(date_end)
            elif df.operator == "between":
                # Due within range (inclusive)
                range_start = f"{df.date}T00:00:00Z"
                range_end = f"{df.date_end}T23:59:59.999999Z"
                due_conditions.append("(loops.due_at_utc >= ? AND loops.due_at_utc <= ?)")
                params.extend([range_start, range_end])

    if due_conditions:
        if len(due_conditions) == 1:
            conditions.append(due_conditions[0])
        else:
            # Multiple due predicates OR together
            conditions.append(f"({' OR '.join(due_conditions)})")

    if query.text_terms:
        text_conditions: list[str] = []
        for term in query.text_terms:
            escaped = _escape_like_pattern(term)
            like_pattern = f"%{escaped}%"
            text_conditions.append(
                "(loops.raw_text LIKE ? ESCAPE '\\' OR loops.title LIKE ? ESCAPE '\\' "
                "OR loops.summary LIKE ? ESCAPE '\\' OR loops.next_action LIKE ? ESCAPE '\\')"
            )
            params.extend([like_pattern, like_pattern, like_pattern, like_pattern])
        conditions.append(" AND ".join(text_conditions))

    if query.recurring is not None:
        if query.recurring:
            conditions.append("loops.recurrence_enabled = 1")
        else:
            conditions.append("loops.recurrence_enabled = 0")

    if not conditions:
        return ("", [])

    where_sql = "WHERE " + " AND ".join(conditions)
    return (where_sql, params)


__all__ = ["DueDateFilter", "LoopQuery", "parse_loop_query", "compile_loop_query"]
