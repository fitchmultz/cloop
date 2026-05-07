"""Canonical backend-ranked operator Now-feed assembly.

Purpose:
    Build one deterministic Now feed that combines continuity summaries,
    planning/review sessions, and prioritized loops into a shared launch list.

Responsibilities:
    - Reuse existing read surfaces instead of duplicating storage logic.
    - Rank candidate next moves deterministically on the backend.
    - Deduplicate identical launch targets before returning the final feed.

Non-scope:
    - Frontend rendering or browser-local ranking.
    - Introducing new persistence tables or transport-specific copies.

Scope:
    - Operator Now-feed aggregation only.

Usage:
    Imported by HTTP routes and future transport surfaces that need the same
    ranked operator next-move feed.

Invariants/Assumptions:
    - Launch targets must reuse the shared continuity location contract.
    - Continuity summaries already carry meaningful backend-authored ranking.
    - Session and loop fallbacks should never duplicate a stronger continuity item.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from . import db
from .loops import (
    planning_workflows,
    review_workflows,
    working_sets,
)
from .loops import (
    read_service as loop_read_service,
)
from .loops.models import format_utc_datetime, utc_now
from .schemas.loops import (
    ContinuityLocationResponse,
    NowFeedDisplayTone,
    NowFeedItemResponse,
    NowFeedResponse,
)
from .settings import Settings, get_settings
from .storage import read_continuity_snapshot

_BUCKET_BASE_RANK: dict[str, int] = {
    "due_soon": 2400,
    "quick_wins": 2150,
    "high_leverage": 2100,
    "standard": 1850,
}
_BUCKET_COPY: dict[str, tuple[str, NowFeedDisplayTone, str, str, str]] = {
    "due_soon": (
        "Due soon",
        "attention",
        "This loop is time-sensitive enough to deserve immediate operator attention.",
        "Work the nearest due commitment before lower-pressure tasks drift it further.",
        "Open in Do",
    ),
    "quick_wins": (
        "Quick win",
        "progress",
        "This loop looks cheap to move right now, making it a strong momentum play.",
        "Take the quick win while the task is ready and low-friction.",
        "Open in Do",
    ),
    "high_leverage": (
        "High leverage",
        "progress",
        "This loop appears to unlock outsized value relative to the rest of the queue.",
        "Use this leverage point to unblock or accelerate more downstream work.",
        "Open in Do",
    ),
    "standard": (
        "Ready loop",
        "neutral",
        (
            "This loop is ready to work without extra preparation, even if it lacks "
            "a stronger urgency signal."
        ),
        ("Use this as a stable default when no stronger plan, review, or timing signal wins."),
        "Open in Do",
    ),
}


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _title(loop: Mapping[str, Any]) -> str:
    title = str(loop.get("title") or "").strip()
    if title:
        return title
    return str(loop.get("raw_text") or f"Loop #{loop.get('id')}").strip()


def _clean_labels(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    labels: list[str] = []
    for raw in values:
        label = str(raw or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def _active_working_set_id(conn: Any) -> int | None:
    payload = working_sets.get_working_set_context(conn=conn)
    return _integer(payload.get("active_working_set_id"))


def _action_label(location: ContinuityLocationResponse) -> str:
    if location.state == "plan":
        return "Resume plan"
    if location.state == "decide":
        if location.review_focus == "relationship":
            return "Open decision queue"
        if location.review_focus == "enrichment":
            return "Open enrichment queue"
        return "Open review"
    if location.state == "do":
        return "Open in Do"
    if location.state == "recall":
        if location.recall_tool == "memory":
            return "Open memory"
        if location.recall_tool == "rag":
            return "Open documents"
        return "Open grounded chat"
    if location.state == "working_set":
        return "Open working set"
    return "Open now"


def _location_identity(location: ContinuityLocationResponse) -> tuple[object, ...]:
    return (
        location.state,
        location.recall_tool,
        location.review_focus,
        location.session_id,
        location.loop_id,
        location.view_id,
        location.memory_id,
        location.working_set_id,
        location.query,
        location.include_loop_context,
        location.include_memory_context,
        location.include_rag_context,
    )


def _session_sorted_by_updated(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row.get("updated_at_utc") or ""), reverse=True)


def _planning_launch_location(snapshot: Mapping[str, Any]) -> ContinuityLocationResponse:
    execution_history = list(snapshot.get("execution_history") or [])
    latest_execution = execution_history[-1] if execution_history else None
    if isinstance(latest_execution, Mapping):
        for surface in latest_execution.get("launch_surfaces") or []:
            if not isinstance(surface, Mapping):
                continue
            web = surface.get("web")
            if not isinstance(web, Mapping):
                continue
            surface_name = str(web.get("surface") or "").strip()
            review_kind = str(web.get("review_kind") or "").strip()
            session_id = _integer(web.get("session_id"))
            working_set_id = _integer(web.get("working_set_id"))
            if (
                surface_name == "review_session"
                and review_kind in {"relationship", "enrichment"}
                and session_id is not None
            ):
                resolved_review_focus = (
                    "relationship" if review_kind == "relationship" else "enrichment"
                )
                return ContinuityLocationResponse(
                    state="decide",
                    review_focus=resolved_review_focus,
                    session_id=session_id,
                    working_set_id=working_set_id,
                )
    session = snapshot.get("session") or {}
    return ContinuityLocationResponse(
        state="plan",
        review_focus="planning",
        session_id=_integer(session.get("id")),
    )


def _continuity_candidate(
    summary: Any,
    *,
    active_working_set_id: int | None,
) -> NowFeedItemResponse:
    working_set_boost = (
        120
        if summary.working_set_id is not None and summary.working_set_id == active_working_set_id
        else 0
    )
    reason_labels = _clean_labels([*summary.why_now, *summary.changed_since_last_seen])
    return NowFeedItemResponse(
        id=f"continuity:{summary.id}",
        rank=5000 + int(summary.rank) + working_set_boost,
        source="continuity",
        display_kind=summary.display_card.kind,
        display_tone=summary.display_card.tone,
        eyebrow=summary.display_card.eyebrow,
        title=summary.display_title,
        summary=summary.display_summary,
        rationale=summary.display_card.rationale,
        reason_labels=reason_labels,
        freshness_at_utc=summary.occurred_at_utc,
        freshness_prefix="Observed",
        action_label=_action_label(summary.resolved_resume.resolved_location),
        launch_location=summary.resolved_resume.resolved_location,
        working_set_id=summary.working_set_id,
    )


def _planning_candidate(
    snapshot: Mapping[str, Any],
    *,
    active_working_set_id: int | None,
) -> NowFeedItemResponse | None:
    session = snapshot.get("session")
    if not isinstance(session, Mapping):
        return None
    session_id = _integer(session.get("id"))
    if session_id is None:
        return None

    launch_location = _planning_launch_location(snapshot)
    raw_context_freshness = snapshot.get("context_freshness")
    context_freshness: dict[str, Any] = (
        dict(raw_context_freshness) if isinstance(raw_context_freshness, Mapping) else {}
    )
    latest_execution = None
    execution_history = list(snapshot.get("execution_history") or [])
    if execution_history:
        latest = execution_history[-1]
        latest_execution = latest if isinstance(latest, Mapping) else None

    working_set_id = _integer(launch_location.working_set_id)
    working_set_boost = (
        120 if working_set_id is not None and working_set_id == active_working_set_id else 0
    )
    launch_surface_count = (
        len(latest_execution.get("launch_surfaces") or []) if latest_execution else 0
    )
    follow_up_count = (
        len(latest_execution.get("follow_up_resources") or []) if latest_execution else 0
    )
    is_stale = bool(context_freshness.get("is_stale"))
    current_checkpoint = (
        snapshot.get("current_checkpoint")
        if isinstance(snapshot.get("current_checkpoint"), Mapping)
        else None
    )
    loop_count = len(snapshot.get("target_loops") or [])
    status = str(session.get("status") or "draft")

    reason_labels = _clean_labels(
        [
            str(context_freshness.get("summary_label") or "") or None,
            f"{loop_count} target loop{'s' if loop_count != 1 else ''}",
            f"Checkpoint: {current_checkpoint.get('title')}" if current_checkpoint else None,
            (
                f"{launch_surface_count} prepared downstream surface"
                f"{'s' if launch_surface_count != 1 else ''}"
            )
            if launch_surface_count
            else None,
            f"{follow_up_count} follow-up resource{'s' if follow_up_count != 1 else ''}"
            if follow_up_count
            else None,
            "Plan context drifted since the last generation" if is_stale else None,
        ]
    )
    summary_text = str(
        snapshot.get("plan_summary") or session.get("name") or f"Plan #{session_id}"
    ).strip()

    return NowFeedItemResponse(
        id=f"planning:{session_id}",
        rank=3300
        + (120 if status != "completed" else 40)
        + (90 if launch_surface_count else 0)
        + (60 if is_stale else 0)
        + working_set_boost,
        source="planning_session",
        display_kind="handoff",
        display_tone="attention" if launch_surface_count or status != "completed" else "progress",
        eyebrow="Plan in motion",
        title=str(session.get("name") or f"Plan #{session_id}"),
        summary=summary_text,
        rationale=(
            "Checkpointed planning should stay resumable from one explicit feed "
            "instead of being rediscovered from separate tabs and queues."
        ),
        reason_labels=reason_labels,
        freshness_at_utc=str(session.get("updated_at_utc") or "") or None,
        freshness_prefix="Updated",
        action_label=_action_label(launch_location),
        launch_location=launch_location,
        working_set_id=working_set_id,
    )


def _relationship_candidate(
    snapshot: Mapping[str, Any],
    *,
    active_working_set_id: int | None,
) -> NowFeedItemResponse | None:
    session = snapshot.get("session")
    if not isinstance(session, Mapping):
        return None
    session_id = _integer(session.get("id"))
    if session_id is None:
        return None
    loop_count = _integer(snapshot.get("loop_count")) or 0
    if loop_count <= 0:
        return None
    current_item = (
        snapshot.get("current_item") if isinstance(snapshot.get("current_item"), Mapping) else None
    )
    top_score = float(current_item.get("top_score") or 0.0) if current_item else 0.0
    working_set_id = _integer(session.get("working_set_id"))
    working_set_boost = (
        120 if working_set_id is not None and working_set_id == active_working_set_id else 0
    )
    launch_location = ContinuityLocationResponse(
        state="decide",
        review_focus="relationship",
        session_id=session_id,
        working_set_id=working_set_id,
    )
    reason_labels = _clean_labels(
        [
            f"{loop_count} similarity decision{'s' if loop_count != 1 else ''} queued",
            f"Top candidate is {round(top_score * 100)}% similar" if top_score > 0 else None,
            f"Current loop: {_title(current_item.get('loop') or {})}" if current_item else None,
        ]
    )
    return NowFeedItemResponse(
        id=f"relationship:{session_id}",
        rank=2900 + min(loop_count, 20) * 8 + (70 if top_score >= 0.9 else 0) + working_set_boost,
        source="relationship_review_session",
        display_kind="decision",
        display_tone="attention" if top_score >= 0.9 else "neutral",
        eyebrow="Decision queue",
        title=str(session.get("name") or f"Relationship review #{session_id}"),
        summary=(
            f"{loop_count} duplicate or related-loop decision"
            f"{'s' if loop_count != 1 else ''} are waiting in this saved queue."
        ),
        rationale=(
            "Saved relationship review sessions preserve cursor and candidate context, "
            "so they should reopen as one explicit next move."
        ),
        reason_labels=reason_labels,
        freshness_at_utc=str(session.get("updated_at_utc") or "") or None,
        freshness_prefix="Updated",
        action_label="Open decision queue",
        launch_location=launch_location,
        working_set_id=working_set_id,
    )


def _enrichment_candidate(
    snapshot: Mapping[str, Any],
    *,
    active_working_set_id: int | None,
) -> NowFeedItemResponse | None:
    session = snapshot.get("session")
    if not isinstance(session, Mapping):
        return None
    session_id = _integer(session.get("id"))
    if session_id is None:
        return None
    loop_count = _integer(snapshot.get("loop_count")) or 0
    if loop_count <= 0:
        return None
    current_item = (
        snapshot.get("current_item") if isinstance(snapshot.get("current_item"), Mapping) else None
    )
    clarification_count = (
        _integer(current_item.get("pending_clarification_count")) or 0 if current_item else 0
    )
    suggestion_count = (
        _integer(current_item.get("pending_suggestion_count")) or 0 if current_item else 0
    )
    working_set_id = _integer(session.get("working_set_id"))
    working_set_boost = (
        120 if working_set_id is not None and working_set_id == active_working_set_id else 0
    )
    launch_location = ContinuityLocationResponse(
        state="decide",
        review_focus="enrichment",
        session_id=session_id,
        working_set_id=working_set_id,
    )
    reason_labels = _clean_labels(
        [
            f"{loop_count} enrichment follow-up item{'s' if loop_count != 1 else ''}",
            (
                f"{clarification_count} clarification"
                f"{'s' if clarification_count != 1 else ''} still need answers"
            )
            if clarification_count
            else None,
            (
                f"{suggestion_count} suggestion"
                f"{'s' if suggestion_count != 1 else ''} are ready to review"
            )
            if suggestion_count
            else None,
        ]
    )
    return NowFeedItemResponse(
        id=f"enrichment:{session_id}",
        rank=2800 + min(loop_count, 20) * 7 + clarification_count * 20 + working_set_boost,
        source="enrichment_review_session",
        display_kind="decision",
        display_tone="attention" if clarification_count else "progress",
        eyebrow="Decision queue",
        title=str(session.get("name") or f"Enrichment review #{session_id}"),
        summary=(
            f"{loop_count} enrichment follow-up item"
            f"{'s' if loop_count != 1 else ''} are ready for apply/reject or "
            "clarification answers."
        ),
        rationale=(
            "Saved enrichment review sessions should stay resumable from the same "
            "ranked feed that picks the operator's next move."
        ),
        reason_labels=reason_labels,
        freshness_at_utc=str(session.get("updated_at_utc") or "") or None,
        freshness_prefix="Updated",
        action_label="Open enrichment queue",
        launch_location=launch_location,
        working_set_id=working_set_id,
    )


def _loop_candidates(
    next_loops: Mapping[str, list[dict[str, Any]]],
) -> list[NowFeedItemResponse]:
    items: list[NowFeedItemResponse] = []
    for bucket, loops in next_loops.items():
        eyebrow, tone, summary_copy, rationale, action_label = _BUCKET_COPY.get(
            bucket,
            _BUCKET_COPY["standard"],
        )
        base_rank = _BUCKET_BASE_RANK.get(bucket, _BUCKET_BASE_RANK["standard"])
        for index, loop in enumerate(loops):
            loop_id = _integer(loop.get("id"))
            if loop_id is None:
                continue
            next_action = str(loop.get("next_action") or "").strip()
            due_bits = loop.get("due_at_utc") or loop.get("due_date")
            reason_labels = _clean_labels(
                [
                    summary_copy,
                    f"Next action: {next_action}" if next_action else None,
                    "Has a due date" if due_bits else None,
                    f"Project: {loop.get('project')}" if loop.get("project") else None,
                ]
            )
            items.append(
                NowFeedItemResponse(
                    id=f"loop:{loop_id}",
                    rank=base_rank - index * 4,
                    source="loop",
                    display_kind="mutation",
                    display_tone=tone,
                    eyebrow=eyebrow,
                    title=_title(loop),
                    summary=next_action or summary_copy,
                    rationale=rationale,
                    reason_labels=reason_labels,
                    freshness_at_utc=str(loop.get("updated_at_utc") or "") or None,
                    freshness_prefix="Updated",
                    action_label=action_label,
                    launch_location=ContinuityLocationResponse(state="do", loop_id=loop_id),
                )
            )
    return items


def _dedupe_ranked_candidates(
    candidates: list[NowFeedItemResponse],
    *,
    limit: int,
) -> list[NowFeedItemResponse]:
    ranked = sorted(
        candidates,
        key=lambda item: (
            item.rank,
            item.freshness_at_utc or "",
            item.id,
        ),
        reverse=True,
    )
    results: list[NowFeedItemResponse] = []
    seen_locations: set[tuple[object, ...]] = set()
    for item in ranked:
        location_key = _location_identity(item.launch_location)
        if location_key in seen_locations:
            continue
        seen_locations.add(location_key)
        results.append(item)
        if len(results) >= limit:
            break
    return results


def read_operator_now_feed(
    *,
    limit: int = 8,
    settings: Settings | None = None,
) -> NowFeedResponse:
    """Read the canonical backend-ranked operator Now feed."""
    settings = settings or get_settings()
    limit = max(1, min(limit, 20))
    candidate_budget = max(limit * 3, 12)
    continuity_snapshot = read_continuity_snapshot(limit=candidate_budget, settings=settings)

    with db.core_connection(settings) as conn:
        active_working_set_id = _active_working_set_id(conn)
        next_loops = loop_read_service.next_loops(
            limit=min(candidate_budget, 20),
            conn=conn,
            settings=settings,
        )
        planning_sessions = _session_sorted_by_updated(
            planning_workflows.list_planning_sessions(conn=conn)
        )
        relationship_sessions = _session_sorted_by_updated(
            review_workflows.list_relationship_review_sessions(conn=conn)
        )
        enrichment_sessions = _session_sorted_by_updated(
            review_workflows.list_enrichment_review_sessions(conn=conn)
        )

        planning_snapshot = (
            planning_workflows.get_planning_session(
                session_id=int(planning_sessions[0]["id"]),
                conn=conn,
            )
            if planning_sessions
            else None
        )
        relationship_snapshot = (
            review_workflows.get_relationship_review_session(
                session_id=int(relationship_sessions[0]["id"]),
                conn=conn,
                settings=settings,
            )
            if relationship_sessions
            else None
        )
        enrichment_snapshot = (
            review_workflows.get_enrichment_review_session(
                session_id=int(enrichment_sessions[0]["id"]),
                conn=conn,
            )
            if enrichment_sessions
            else None
        )

    candidates: list[NowFeedItemResponse] = [
        _continuity_candidate(summary, active_working_set_id=active_working_set_id)
        for summary in continuity_snapshot.workflow_summaries
    ]
    if isinstance(planning_snapshot, Mapping):
        planning_item = _planning_candidate(
            planning_snapshot,
            active_working_set_id=active_working_set_id,
        )
        if planning_item is not None:
            candidates.append(planning_item)
    if isinstance(relationship_snapshot, Mapping):
        relationship_item = _relationship_candidate(
            relationship_snapshot,
            active_working_set_id=active_working_set_id,
        )
        if relationship_item is not None:
            candidates.append(relationship_item)
    if isinstance(enrichment_snapshot, Mapping):
        enrichment_item = _enrichment_candidate(
            enrichment_snapshot,
            active_working_set_id=active_working_set_id,
        )
        if enrichment_item is not None:
            candidates.append(enrichment_item)
    candidates.extend(_loop_candidates(next_loops))

    return NowFeedResponse(
        generated_at_utc=format_utc_datetime(utc_now()),
        items=_dedupe_ranked_candidates(candidates, limit=limit),
    )


__all__ = ["read_operator_now_feed"]
