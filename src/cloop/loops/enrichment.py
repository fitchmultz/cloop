"""AI-powered loop enrichment via LLM.

Purpose:
    Auto-populate loop fields (title, tags, next_action) using LLM suggestions.

Responsibilities:
    - Build structured prompts from raw loop text
    - Parse LLM responses into LoopSuggestion models
    - Apply suggestions with confidence gating
    - Coordinate with related loops embedding
    - Gather contextual information for intelligent suggestions

Non-scope:
    - Embedding generation (see loops/related.py)
    - Status transitions (see loops/service.py)

Entrypoints:
    - enrich_loop(loop_id, conn, settings) -> Dict[str, Any]
    - LoopSuggestion: Pydantic model for structured responses
    - EnrichmentContext: Dataclass for contextual information
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from pydantic import BaseModel, Field, ValidationError

from .. import db
from ..llm import chat_completion
from ..settings import Settings, get_settings
from ..webhooks.service import queue_deliveries
from . import repo, similarity
from .errors import LoopNotFoundError
from .errors import ValidationError as CloopValidationError
from .models import EnrichmentState, LoopEventType, format_utc_datetime
from .related import find_duplicate_candidates, suggest_links
from .utils import normalize_tags

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EnrichmentContext:
    """Context information for enrichment to make intelligent suggestions.

    Attributes:
        related_loops: List of related loop summaries (max 5)
        duplicate_candidates: List of potential duplicates (max 3)
        workload_snapshot: Current workload priorities (max 3 items)
        existing_links: All existing link relationships for this loop
        answered_clarifications: User-provided answers to prior clarification questions
    """

    related_loops: list[dict[str, Any]]
    duplicate_candidates: list[dict[str, Any]]
    workload_snapshot: list[dict[str, Any]]
    existing_links: list[dict[str, Any]]
    answered_clarifications: list[dict[str, Any]]


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
    context_used: list[str] = Field(
        default_factory=list,
        description=(
            "List of context keys that influenced this suggestion "
            "(e.g., 'related_loops', 'workload')"
        ),
    )


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


def _gather_enrichment_context(
    *,
    loop_id: int,
    loop_text: str,
    conn: sqlite3.Connection,
    settings: Settings,
) -> EnrichmentContext:
    """Gather bounded context for enrichment prompt.

    Collects related loops, duplicate candidates, workload snapshot, and
    existing links to help the LLM make context-aware suggestions.

    Gracefully degrades on errors - returns empty lists if context fetch fails.

    Args:
        loop_id: The loop being enriched
        loop_text: The raw text of the loop (for context)
        conn: Database connection
        settings: Application settings

    Returns:
        EnrichmentContext with bounded context information
    """
    related_loops: list[dict[str, Any]] = []
    duplicate_candidates: list[dict[str, Any]] = []
    workload_snapshot: list[dict[str, Any]] = []
    existing_links: list[dict[str, Any]] = []
    answered_clarifications: list[dict[str, Any]] = []

    try:
        # Fetch related loops via embedding similarity (limit 5)
        # This requires the embedding to exist - may be empty for new loops
        links = repo.list_loop_links_by_type(
            loop_id=loop_id,
            relationship_type="related",
            conn=conn,
        )
        if links:
            related_ids = [int(link["related_loop_id"]) for link in links[:5]]
            related_records = repo.read_loops_batch(loop_ids=related_ids, conn=conn)
            for rid in related_ids:
                rec = related_records.get(rid)
                if rec:
                    related_loops.append(
                        {
                            "id": rid,
                            "title": rec.title,
                            "status": rec.status.value,
                            "confidence": next(
                                (
                                    link["confidence"]
                                    for link in links
                                    if link["related_loop_id"] == rid
                                ),
                                None,
                            ),
                        }
                    )
    except sqlite3.Error, ValueError, KeyError, TypeError:
        logger.debug("Failed to fetch related loops for loop %s", loop_id)

    try:
        # Fetch duplicate candidates (limit 3)
        dupes = find_duplicate_candidates(loop_id=loop_id, conn=conn, settings=settings)
        for d in dupes[:3]:
            duplicate_candidates.append(
                {
                    "loop_id": d.loop_id,
                    "title": d.title,
                    "status": d.status,
                    "score": d.score,
                    "preview": d.raw_text_preview,
                }
            )
    except sqlite3.Error, ValueError, AttributeError:
        logger.debug("Failed to fetch duplicate candidates for loop %s", loop_id)

    try:
        # Fetch workload snapshot (top 3 actionable)
        # Import here to avoid circular imports
        from .read_service import next_loops

        workload = next_loops(limit=3, conn=conn, settings=settings)
        # Flatten buckets into single list, take top 3
        all_items = []
        for bucket_items in workload.values():
            all_items.extend(bucket_items)
        for item in all_items[:3]:
            workload_snapshot.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "status": item.get("status"),
                    "project": item.get("project"),
                }
            )
    except sqlite3.Error, ValueError, KeyError, TypeError:
        logger.debug("Failed to fetch workload snapshot for loop %s", loop_id)

    try:
        # Fetch all existing link types for this loop
        for rel_type in ["related", "duplicate", "blocks", "depends_on"]:
            links = repo.list_loop_links_by_type(
                loop_id=loop_id,
                relationship_type=rel_type,
                conn=conn,
            )
            for link in links:
                existing_links.append(
                    {
                        "related_loop_id": link["related_loop_id"],
                        "relationship_type": rel_type,
                        "confidence": link.get("confidence"),
                    }
                )
    except sqlite3.Error, ValueError, KeyError, TypeError:
        logger.debug("Failed to fetch existing links for loop %s", loop_id)

    try:
        # Fetch answered clarifications for this loop
        clars = repo.list_answered_clarifications(loop_id=loop_id, conn=conn)
        for clar in clars[:10]:  # Limit to 10 most recent
            answered_clarifications.append(
                {
                    "question": clar["question"],
                    "answer": clar["answer"],
                    "answered_at": clar["answered_at"],
                }
            )
    except sqlite3.Error, ValueError, KeyError, TypeError:
        logger.debug("Failed to fetch clarifications for loop %s", loop_id)

    return EnrichmentContext(
        related_loops=related_loops,
        duplicate_candidates=duplicate_candidates,
        workload_snapshot=workload_snapshot,
        existing_links=existing_links,
        answered_clarifications=answered_clarifications,
    )


def _build_prompt(
    loop: Mapping[str, Any],
    context: EnrichmentContext | None = None,
) -> list[dict[str, str]]:
    """Build the LLM prompt with optional context.

    Args:
        loop: The loop data to enrich
        context: Optional context information for intelligent suggestions

    Returns:
        List of message dicts for the LLM
    """
    user_content: dict[str, Any] = {
        "raw_text": loop.get("raw_text"),
        "captured_at_utc": loop.get("captured_at_utc"),
        "captured_tz_offset_min": loop.get("captured_tz_offset_min"),
        "status": loop.get("status"),
    }

    # Add context section if available
    if context and (
        context.related_loops
        or context.duplicate_candidates
        or context.workload_snapshot
        or context.existing_links
        or context.answered_clarifications
    ):
        context_section: dict[str, Any] = {}
        if context.related_loops:
            context_section["related_loops"] = context.related_loops
        if context.duplicate_candidates:
            context_section["potential_duplicates"] = context.duplicate_candidates
        if context.workload_snapshot:
            context_section["current_workload"] = context.workload_snapshot
        if context.existing_links:
            context_section["existing_links"] = context.existing_links
        if context.answered_clarifications:
            context_section["user_clarifications"] = context.answered_clarifications
        user_content["context"] = context_section

    return [
        {
            "role": "system",
            "content": (
                "You are a loop organizer. Return only JSON that matches the schema. "
                "Do not wrap the response in markdown. Use ISO8601 datetimes or null. "
                "When context is provided, use it to: (1) avoid duplicating existing work, "
                "(2) suggest consolidating with related/duplicate items, "
                "(3) prioritize appropriately given current workload, "
                "(4) incorporate user clarification answers into your suggestions. "
                "Set context_used field to indicate which context sources influenced your decision."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(user_content),
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
                        "context_used": ["string", "..."],
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
            cleaned_tags = normalize_tags(suggestion.tags)
            repo.replace_loop_tags(loop_id=int(loop["id"]), tag_names=cleaned_tags, conn=conn)
            provenance["tags"] = {
                "source": "ai",
                "confidence": _confidence_for(suggestion, "tags"),
                "suggestion_id": suggestion_id,
            }
            provenance_changed = True
            applied_fields.append("tags")

    # Track context usage in provenance
    if suggestion.context_used:
        provenance["context_used"] = suggestion.context_used
        provenance_changed = True

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

    # NEW: Gather context before building prompt
    context: EnrichmentContext | None = None
    if settings.autopilot_enabled:
        try:
            context = _gather_enrichment_context(
                loop_id=loop_id,
                loop_text=record.raw_text,
                conn=conn,
                settings=settings,
            )
        except Exception as exc:
            logging.warning("Failed to gather enrichment context for loop %s: %s", loop_id, exc)

    messages = _build_prompt(loop_payload, context=context)

    try:
        content, _metadata = chat_completion(
            messages=messages,
            settings=settings,
            model=settings.pi_organizer_model,
            thinking_level=settings.pi_organizer_thinking_level,
            timeout_s=settings.pi_organizer_timeout,
        )
        raw_json = _extract_json(content)
        suggestion = LoopSuggestion.model_validate(raw_json)
    except KeyboardInterrupt:
        # Re-raise system signals without modification
        raise
    except SystemExit:
        # Re-raise system signals without modification
        raise
    except json.JSONDecodeError as exc:
        with conn:
            repo.update_loop_fields(
                loop_id=loop_id,
                fields={"enrichment_state": EnrichmentState.FAILED.value},
                conn=conn,
            )
            event_id = repo.insert_loop_event(
                loop_id=loop_id,
                event_type=LoopEventType.ENRICH_FAILURE.value,
                payload={"error": f"JSON decode error: {exc}"},
                conn=conn,
            )
            queue_deliveries(
                event_id=event_id,
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
            event_id = repo.insert_loop_event(
                loop_id=loop_id,
                event_type=LoopEventType.ENRICH_FAILURE.value,
                payload={"error": f"Validation error: {exc}"},
                conn=conn,
            )
            queue_deliveries(
                event_id=event_id,
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
            event_id = repo.insert_loop_event(
                loop_id=loop_id,
                event_type=LoopEventType.ENRICH_FAILURE.value,
                payload={"error": str(exc)},
                conn=conn,
            )
            queue_deliveries(
                event_id=event_id,
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
            model=settings.pi_organizer_model,
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
        event_id = repo.insert_loop_event(
            loop_id=loop_id,
            event_type=LoopEventType.ENRICH_SUCCESS.value,
            payload={
                "suggestion_id": suggestion_id,
                "applied_fields": sorted(set(applied_fields)),
            },
            conn=conn,
        )
        queue_deliveries(
            event_id=event_id,
            event_type=LoopEventType.ENRICH_SUCCESS.value,
            payload={
                "suggestion_id": suggestion_id,
                "applied_fields": sorted(set(applied_fields)),
            },
            conn=conn,
        )

        # Insert clarification questions from enrichment (with deduplication)
        if suggestion.needs_clarification:
            existing_questions = repo.list_unanswered_clarification_questions(
                loop_id=loop_id, conn=conn
            )
            for question in suggestion.needs_clarification:
                question_text = question.strip()
                if question_text and question_text not in existing_questions:
                    repo.insert_loop_clarification(
                        loop_id=loop_id,
                        question=question_text,
                        conn=conn,
                    )

    if settings.autopilot_enabled:
        try:
            similarity.ensure_loop_embeddings(
                loop_ids=[loop_id],
                conn=conn,
                settings=settings,
            )
            suggest_links(loop_id=loop_id, conn=conn, settings=settings)
            # Detect and link potential duplicates
            dupes = find_duplicate_candidates(loop_id=loop_id, conn=conn, settings=settings)
            for dupe in dupes:
                repo.insert_loop_link(
                    loop_id=loop_id,
                    related_loop_id=dupe.loop_id,
                    relationship_type="duplicate",
                    confidence=dupe.score,
                    source="ai",
                    conn=conn,
                )
        except CloopValidationError as exc:
            # Common expected case: provider misconfiguration (e.g., missing api_base).
            # Keep autopilot capture successful, but avoid scary traceback spam.
            logging.warning(
                "Skipping embedding/suggestion phase for loop %s due to configuration: %s",
                loop_id,
                exc,
            )
        except (sqlite3.Error, AttributeError, TypeError) as exc:
            # Unexpected embedding/suggestion failures: include traceback for diagnosis.
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
