from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .models import parse_utc_datetime


@dataclass(frozen=True, slots=True)
class PriorityWeights:
    due_weight: float
    urgency_weight: float
    importance_weight: float
    time_penalty: float
    activation_penalty: float


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return parse_utc_datetime(value)


def compute_priority_score(
    loop: dict[str, Any],
    *,
    now_utc: datetime,
    w: PriorityWeights,
) -> float:
    score = 0.0
    due_at = _parse_time(loop.get("due_at_utc"))
    if due_at is not None:
        delta = (due_at - now_utc).total_seconds()
        if delta <= 0:
            due_factor = 1.0
        else:
            hours = delta / 3600
            due_factor = max(0.0, 1.0 - min(hours / 72.0, 1.0))
        score += w.due_weight * due_factor

    urgency = float(loop.get("urgency") or 0.0)
    importance = float(loop.get("importance") or 0.0)
    score += w.urgency_weight * urgency
    score += w.importance_weight * importance

    time_minutes = float(loop.get("time_minutes") or 0.0)
    activation_energy = float(loop.get("activation_energy") or 0.0)
    score -= w.time_penalty * (time_minutes / 60.0)
    score -= w.activation_penalty * activation_energy
    return score


def bucketize(loop: dict[str, Any], *, now_utc: datetime) -> str:
    due_at = _parse_time(loop.get("due_at_utc"))
    if due_at is not None and due_at <= now_utc + timedelta(hours=48):
        return "due_soon"

    time_minutes = loop.get("time_minutes")
    activation_energy = loop.get("activation_energy")
    if (
        time_minutes is not None
        and activation_energy is not None
        and int(time_minutes) <= 15
        and int(activation_energy) <= 1
    ):
        return "quick_wins"

    importance = loop.get("importance")
    if importance is not None and float(importance) >= 0.7:
        return "high_leverage"

    return "standard"
