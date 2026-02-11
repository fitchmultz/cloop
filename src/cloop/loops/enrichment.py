from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Mapping

import litellm
from pydantic import BaseModel, Field, ValidationError

from .. import db
from ..providers import resolve_provider_kwargs
from ..settings import Settings, get_settings
from . import repo
from .errors import LoopNotFoundError
from .errors import ValidationError as CloopValidationError
from .models import EnrichmentState, LoopEventType, format_utc_datetime
from .related import suggest_links, upsert_loop_embedding


class LoopSuggestion(BaseModel):
    title: str | None = None
    summary: str | None = None
    definition_of_done: str | None = None
    next_action: str | None = None
    due_at: datetime | None = None
    snooze_until: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    project: str | None = None
    activation_energy: int | None = None
    time_minutes: int | None = None
    urgency: float | None = None
    importance: float | None = None
    confidence: dict[str, float] = Field(default_factory=dict)
    needs_clarification: list[str] = Field(default_factory=list)


def _extract_json(payload: str) -> dict[str, Any]:
    """
    Extract JSON object from LLM response, handling markdown blocks and text.

    Tries multiple strategies in order:
    1. Strip markdown code blocks and parse
    2. Find JSON object by brace matching
    3. Raise ValueError if all fail
    """
    import re

    payload = payload.strip()

    # Strategy 1: Strip markdown code blocks
    # Match ```json...``` or ```...``` blocks (with optional language specifier)
    markdown_pattern = r"^```(?:json)?\s*\n?(.*?)\n?```$"
    match = re.match(markdown_pattern, payload, re.DOTALL | re.IGNORECASE)
    if match:
        inner = match.group(1).strip()
        try:
            decoder = json.JSONDecoder()
            parsed, _ = decoder.raw_decode(inner)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass  # Fall through to next strategy

    # Strategy 2: Find JSON by brace matching
    # Look for the first '{' that starts a valid JSON object
    decoder = json.JSONDecoder()
    for i, char in enumerate(payload):
        if char == "{":
            try:
                parsed, _ = decoder.raw_decode(payload, i)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue  # Try next '{'

    # Strategy 3: Try parsing the whole string as JSON (simple case)
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    raise CloopValidationError("response", "invalid JSON from LLM")


def _build_prompt(loop: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a loop organizer. Return only JSON that matches the schema. "
                "Do not wrap the response in markdown. Use ISO8601 datetimes or null."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "raw_text": loop.get("raw_text"),
                    "captured_at_utc": loop.get("captured_at_utc"),
                    "captured_tz_offset_min": loop.get("captured_tz_offset_min"),
                    "status": loop.get("status"),
                }
            ),
        },
        {
            "role": "system",
            "content": json.dumps(
                {
                    "schema": {
                        "title": "string or null",
                        "summary": "string or null",
                        "definition_of_done": "string or null",
                        "next_action": "string or null",
                        "due_at": "ISO8601 datetime or null",
                        "snooze_until": "ISO8601 datetime or null",
                        "tags": ["string", "..."],
                        "project": "string or null",
                        "activation_energy": "integer 0-3 or null",
                        "time_minutes": "integer minutes or null",
                        "urgency": "float 0-1 or null",
                        "importance": "float 0-1 or null",
                        "confidence": {
                            "title": "float 0-1",
                            "summary": "float 0-1",
                            "definition_of_done": "float 0-1",
                            "next_action": "float 0-1",
                            "due_at": "float 0-1",
                            "snooze_until": "float 0-1",
                            "tags": "float 0-1",
                            "project": "float 0-1",
                            "activation_energy": "float 0-1",
                            "time_minutes": "float 0-1",
                            "urgency": "float 0-1",
                            "importance": "float 0-1",
                        },
                        "needs_clarification": ["string", "..."],
                    }
                }
            ),
        },
    ]


def _confidence_for(suggestion: LoopSuggestion, field: str) -> float:
    return float(suggestion.confidence.get(field, 0.0))


def _apply_suggestion(
    *,
    loop: Mapping[str, Any],
    suggestion: LoopSuggestion,
    suggestion_id: int,
    conn: sqlite3.Connection,
    settings: Settings,
) -> tuple[dict[str, Any], list[str]]:
    if not settings.autopilot_enabled:
        return {}, []

    locked = set(loop.get("user_locks") or [])
    provenance = dict(loop.get("provenance") or {})
    updates: dict[str, Any] = {}
    provenance_changed = False
    applied_fields: list[str] = []

    def consider(field: str, value: Any, confidence_key: str | None = None) -> None:
        nonlocal provenance_changed
        if value is None:
            return
        if field in locked:
            return
        confidence = _confidence_for(suggestion, confidence_key or field)
        if confidence < settings.autopilot_autoapply_min_confidence:
            return
        updates[field] = value
        provenance[field] = {
            "source": "ai",
            "confidence": confidence,
            "suggestion_id": suggestion_id,
        }
        provenance_changed = True
        applied_fields.append(field)

    consider("title", suggestion.title)
    consider("summary", suggestion.summary)
    consider("definition_of_done", suggestion.definition_of_done)
    consider("next_action", suggestion.next_action)

    if suggestion.due_at:
        consider("due_at_utc", format_utc_datetime(suggestion.due_at), "due_at")
    if suggestion.snooze_until:
        consider(
            "snooze_until_utc",
            format_utc_datetime(suggestion.snooze_until),
            "snooze_until",
        )

    consider("activation_energy", suggestion.activation_energy)
    consider("time_minutes", suggestion.time_minutes)
    consider("urgency", suggestion.urgency)
    consider("importance", suggestion.importance)

    if suggestion.project and "project_id" not in locked:
        project_name = suggestion.project.strip()
        if (
            project_name
            and _confidence_for(suggestion, "project")
            >= settings.autopilot_autoapply_min_confidence
        ):
            project_id = repo.upsert_project(name=project_name, conn=conn)
            updates["project_id"] = project_id
            provenance["project_id"] = {
                "source": "ai",
                "confidence": _confidence_for(suggestion, "project"),
                "suggestion_id": suggestion_id,
            }
            provenance_changed = True
            applied_fields.append("project")

    if suggestion.tags and "tags" not in locked:
        if _confidence_for(suggestion, "tags") >= settings.autopilot_autoapply_min_confidence:
            cleaned_tags = [tag.strip().lower() for tag in suggestion.tags if tag.strip()]
            repo.replace_loop_tags(loop_id=int(loop["id"]), tag_names=cleaned_tags, conn=conn)
            provenance["tags"] = {
                "source": "ai",
                "confidence": _confidence_for(suggestion, "tags"),
                "suggestion_id": suggestion_id,
            }
            provenance_changed = True
            applied_fields.append("tags")

    if updates or provenance_changed:
        updates["provenance_json"] = json.dumps(provenance)
        repo.update_loop_fields(loop_id=int(loop["id"]), fields=updates, conn=conn)
    return updates, applied_fields


def enrich_loop(
    *,
    loop_id: int,
    conn: sqlite3.Connection | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if conn is None:
        with db.core_connection(settings) as managed:
            return enrich_loop(loop_id=loop_id, conn=managed, settings=settings)

    record = repo.read_loop(loop_id=loop_id, conn=conn)
    if record is None:
        raise LoopNotFoundError(loop_id)
    loop_payload = {
        "id": record.id,
        "raw_text": record.raw_text,
        "captured_at_utc": format_utc_datetime(record.captured_at_utc),
        "captured_tz_offset_min": record.captured_tz_offset_min,
        "status": record.status.value,
        "user_locks": list(record.user_locks),
        "provenance": dict(record.provenance),
    }

    provider_kwargs = resolve_provider_kwargs(settings.organizer_model, settings)
    messages = _build_prompt(loop_payload)

    try:
        response = litellm.completion(
            model=settings.organizer_model,
            messages=messages,
            timeout=int(settings.organizer_timeout),
            **provider_kwargs,
        )
        choices = response.get("choices", [])
        content = ""
        if choices:
            message = choices[0].get("message", {})
            content = str(message.get("content", ""))
        raw_json = _extract_json(content)
        suggestion = LoopSuggestion.model_validate(raw_json)
    except KeyboardInterrupt, SystemExit:
        # Re-raise system signals without modification
        raise
    except json.JSONDecodeError as exc:
        with conn:
            repo.update_loop_fields(
                loop_id=loop_id,
                fields={"enrichment_state": EnrichmentState.FAILED.value},
                conn=conn,
            )
            repo.insert_loop_event(
                loop_id=loop_id,
                event_type=LoopEventType.ENRICH_FAILURE.value,
                payload={"error": f"JSON decode error: {exc}"},
                conn=conn,
            )
        raise
    except ValidationError as exc:
        with conn:
            repo.update_loop_fields(
                loop_id=loop_id,
                fields={"enrichment_state": EnrichmentState.FAILED.value},
                conn=conn,
            )
            repo.insert_loop_event(
                loop_id=loop_id,
                event_type=LoopEventType.ENRICH_FAILURE.value,
                payload={"error": f"Validation error: {exc}"},
                conn=conn,
            )
        raise
    except Exception as exc:
        # Catch-all for unexpected errors (litellm API errors, etc.)
        with conn:
            repo.update_loop_fields(
                loop_id=loop_id,
                fields={"enrichment_state": EnrichmentState.FAILED.value},
                conn=conn,
            )
            repo.insert_loop_event(
                loop_id=loop_id,
                event_type=LoopEventType.ENRICH_FAILURE.value,
                payload={"error": str(exc)},
                conn=conn,
            )
        raise

    with conn:
        suggestion_payload = suggestion.model_dump(mode="json")
        suggestion_id = repo.insert_loop_suggestion(
            loop_id=loop_id,
            suggestion_json=suggestion_payload,
            model=settings.organizer_model,
            conn=conn,
        )
        _, applied_fields = _apply_suggestion(
            loop=loop_payload,
            suggestion=suggestion,
            suggestion_id=suggestion_id,
            conn=conn,
            settings=settings,
        )
        repo.update_loop_fields(
            loop_id=loop_id,
            fields={"enrichment_state": EnrichmentState.COMPLETE.value},
            conn=conn,
        )
        repo.insert_loop_event(
            loop_id=loop_id,
            event_type=LoopEventType.ENRICH_SUCCESS.value,
            payload={
                "suggestion_id": suggestion_id,
                "applied_fields": sorted(set(applied_fields)),
            },
            conn=conn,
        )

    if settings.autopilot_enabled:
        try:
            text_for_embedding = " ".join(
                chunk
                for chunk in [
                    suggestion.title or record.title or "",
                    record.raw_text,
                ]
                if chunk
            )
            if text_for_embedding.strip():
                upsert_loop_embedding(
                    loop_id=loop_id, text=text_for_embedding, conn=conn, settings=settings
                )
                suggest_links(loop_id=loop_id, conn=conn, settings=settings)
        except Exception as exc:
            # Log embedding/suggestion failures but don't fail the enrichment
            logging.warning(
                "Failed to create embedding or suggestions for loop %s: %s",
                loop_id,
                exc,
                exc_info=True,
            )

    return {
        "loop_id": loop_id,
        "suggestion_id": suggestion_id,
        "applied_fields": sorted(set(applied_fields)),
        "needs_clarification": suggestion.needs_clarification,
    }
