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
    - text:<value>
    - Bare tokens without field: prefix are treated as text:<token>

Semantics:
    - Different fields combine with AND
    - Repeated status: terms combine with OR
    - Repeated tag: terms combine with OR
    - Repeated project: terms combine with OR
    - Repeated text:/bare terms combine with AND; matches raw_text,
      title, summary, next_action

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
    - All due values come from _ALLOWED_DUE_VALUES allowlist
    - SQL is strictly parameterized (never interpolate user values)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .errors import ValidationError

_ALLOWED_FIELDS = frozenset({"status", "tag", "project", "due", "text", "recurring"})
_ALLOWED_STATUSES = frozenset(
    {"open", "all", "inbox", "actionable", "blocked", "scheduled", "completed", "dropped"}
)
_OPEN_STATUSES = frozenset({"inbox", "actionable", "blocked", "scheduled"})
_ALLOWED_DUE_VALUES = frozenset({"today", "tomorrow", "overdue", "none", "next7d"})
_ALLOWED_RECURRING_VALUES = frozenset({"yes", "no", "true", "false", "1", "0"})


@dataclass(frozen=True, slots=True)
class LoopQuery:
    """Parsed loop query AST.

    All tuples are normalized: lowercase, stripped, deduplicated.
    """

    statuses: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    due_filters: tuple[str, ...] = ()
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
            if value not in _ALLOWED_DUE_VALUES:
                allowed = ", ".join(sorted(_ALLOWED_DUE_VALUES))
                raise ValidationError("query", f"invalid due filter '{value}' (allowed: {allowed})")
            due_filters.add(value)
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
        - Always excludes sentinel loop (id=0)
    """
    # Always exclude sentinel loop
    conditions: list[str] = ["loops.id > 0"]
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

    if query.due_filters:
        due_conditions: list[str] = []
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

        if len(due_conditions) == 1:
            conditions.append(due_conditions[0])
        else:
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


__all__ = ["LoopQuery", "parse_loop_query", "compile_loop_query"]
