"""CLI output formatting utilities.

Purpose:
    Provide consistent output formatting for CLI commands.

Responsibilities:
    - Render tables with column alignment
    - Emit JSON or table format based on --format flag
    - Convert values to displayable strings

Non-scope:
    - Business logic (see service layers)
    - Color/styling (not implemented)
"""

from __future__ import annotations

import json
from typing import Any

_TABLE_EMPTY = "(no rows)"


def stringify_cell(value: Any) -> str:
    """Convert any value to a displayable string."""
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, separators=(",", ":"))


def render_table(*, headers: list[str], rows: list[list[str]]) -> str:
    """Render data as aligned table."""
    if not rows:
        return _TABLE_EMPTY
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    header_line = " | ".join(header.ljust(widths[index]) for index, header in enumerate(headers))
    separator_line = "-+-".join("-" * width for width in widths)
    body_lines = [
        " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)) for row in rows
    ]
    return "\n".join([header_line, separator_line, *body_lines])


def emit_output(payload: Any, output_format: str) -> None:
    """Emit output in specified format (json or table)."""
    if output_format == "json":
        print(json.dumps(payload, indent=2))
        return

    if isinstance(payload, list):
        if not payload:
            print(_TABLE_EMPTY)
            return
        if all(isinstance(item, dict) for item in payload):
            headers: list[str] = []
            for item in payload:
                item_map = dict(item)
                for key in item_map:
                    key_name = str(key)
                    if key_name not in headers:
                        headers.append(key_name)
            rows = [
                [stringify_cell(dict(item).get(header)) for header in headers] for item in payload
            ]
            print(render_table(headers=headers, rows=rows))
            return
        print(render_table(headers=["value"], rows=[[stringify_cell(item)] for item in payload]))
        return

    if isinstance(payload, dict):
        rows = [[str(key), stringify_cell(value)] for key, value in payload.items()]
        print(render_table(headers=["field", "value"], rows=rows))
        return

    print(render_table(headers=["value"], rows=[[stringify_cell(payload)]]))


def add_format_option(parser: Any) -> None:
    """Add --format option to a parser."""
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="Output format (default: json)",
    )
