"""Shared JSON extraction helpers for model-produced loop payloads.

Purpose:
    Extract top-level JSON objects from model responses that may include text or
    markdown fences.

Responsibilities:
    - Parse whole-string JSON object payloads.
    - Optionally parse fenced markdown code blocks before falling back.
    - Scan noisy text for the first decodable top-level JSON object.

Scope:
    - JSON object extraction only; caller-specific validation and error mapping
      remain with the caller.

Non-scope:
    - Schema validation, persistence, or caller-specific exception wording.

Usage:
    Imported by loop enrichment and planning workflows before Pydantic validation.

Invariants/Assumptions:
    - Only JSON objects are accepted; arrays and scalar values are rejected.
    - The first decodable object in noisy text is the intended payload.
"""

from __future__ import annotations

import json
import re
from typing import Any

_MARKDOWN_JSON_BLOCK = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL | re.IGNORECASE)


def extract_first_json_object(
    payload: str,
    *,
    allow_markdown_fence: bool = False,
) -> dict[str, Any] | None:
    """Return the first top-level JSON object in ``payload`` when one exists."""
    text = payload.strip()
    decoder = json.JSONDecoder()

    if allow_markdown_fence:
        match = _MARKDOWN_JSON_BLOCK.match(text)
        if match:
            fenced_text = match.group(1).strip()
            try:
                parsed, _ = decoder.raw_decode(fenced_text)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(parsed, dict):
                    return parsed

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(parsed, dict):
            return parsed

    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None
