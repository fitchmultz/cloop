"""Shared orchestration for loop capture flows.

Purpose:
    Centralize the higher-level decisions around loop capture so HTTP routes,
    CLI commands, and MCP tools all follow the same template, recurrence, and
    enrichment behavior.

Responsibilities:
    - Resolve initial loop status from explicit flags
    - Normalize schedule phrases into RRULE strings
    - Load and apply loop templates by ID or name
    - Build capture_fields payloads from richer capture metadata
    - Apply post-capture template defaults without clobbering explicit inputs
    - Request enrichment when autopilot is enabled

Non-scope:
    - Does not own persistence primitives (service.py / repo.py)
    - Does not map domain errors to transport-specific responses
    - Does not execute background enrichment workers

Usage:
    Construct CaptureOrchestrationInput from transport-specific inputs, then
    call orchestrate_capture(...) inside an existing database connection.

Invariants/Assumptions:
    - Explicit status flags always override template-provided status flags
    - Natural-language schedule phrases take precedence over direct RRULE input
    - Explicit capture fields always override template default update fields
    - template_id lookup takes precedence over template_name lookup
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..settings import Settings
from . import repo, service
from .errors import ValidationError
from .models import LoopStatus, resolve_status_from_flags, utc_now
from .templates import apply_template_to_capture, extract_update_fields_from_template


@dataclass(slots=True, frozen=True)
class CaptureStatusFlags:
    """Status-flag inputs that determine the initial capture status."""

    actionable: bool = False
    blocked: bool = False
    scheduled: bool = False

    def resolve(self) -> LoopStatus:
        """Resolve the capture status from the explicit status flags."""
        return resolve_status_from_flags(
            scheduled=self.scheduled,
            blocked=self.blocked,
            actionable=self.actionable,
        )

    @property
    def has_explicit_status(self) -> bool:
        """Whether any explicit status flag was provided by the caller."""
        return self.actionable or self.blocked or self.scheduled


@dataclass(slots=True, frozen=True)
class CaptureTemplateRef:
    """Template identifier inputs for capture orchestration."""

    template_id: int | None = None
    template_name: str | None = None

    def resolve_template(self, *, conn: sqlite3.Connection) -> dict[str, Any] | None:
        """Load the requested template, preferring an explicit ID over a name."""
        if self.template_id is not None:
            return repo.get_loop_template(template_id=self.template_id, conn=conn)
        if self.template_name:
            return repo.get_loop_template_by_name(name=self.template_name, conn=conn)
        return None

    @property
    def requested(self) -> bool:
        """Whether the caller requested a template lookup."""
        return self.template_id is not None or bool(self.template_name)

    @property
    def identifier(self) -> str:
        """Return a user-facing template identifier for validation messages."""
        if self.template_id is not None:
            return str(self.template_id)
        return self.template_name or ""

    @property
    def field_name(self) -> str:
        """Return the validation field associated with this template reference."""
        if self.template_id is not None:
            return "template_id"
        return "template_name"


@dataclass(slots=True, frozen=True)
class CaptureFieldInputs:
    """Optional rich capture metadata that becomes capture_fields."""

    activation_energy: int | None = None
    blocked_reason: str | None = None
    due_date: str | None = None
    due_at_utc: str | None = None
    next_action: str | None = None
    project: str | None = None
    tags: list[str] | None = None
    time_minutes: int | None = None

    def to_capture_fields(self) -> dict[str, Any]:
        """Build a service capture_fields payload from non-empty inputs."""
        capture_fields: dict[str, Any] = {}
        if self.due_date:
            capture_fields["due_date"] = self.due_date
        if self.due_at_utc:
            capture_fields["due_at_utc"] = self.due_at_utc
        if self.next_action:
            capture_fields["next_action"] = self.next_action
        if self.time_minutes is not None:
            capture_fields["time_minutes"] = self.time_minutes
        if self.activation_energy is not None:
            capture_fields["activation_energy"] = self.activation_energy
        if self.project:
            capture_fields["project"] = self.project
        if self.tags:
            capture_fields["tags"] = self.tags
        if self.blocked_reason:
            capture_fields["blocked_reason"] = self.blocked_reason
        return capture_fields


@dataclass(slots=True, frozen=True)
class CaptureOrchestrationInput:
    """Normalized transport-agnostic capture inputs."""

    raw_text: str
    captured_at_iso: str
    client_tz_offset_min: int
    status_flags: CaptureStatusFlags
    schedule: str | None = None
    rrule: str | None = None
    timezone: str | None = None
    template_ref: CaptureTemplateRef = CaptureTemplateRef()
    field_inputs: CaptureFieldInputs = CaptureFieldInputs()


@dataclass(slots=True, frozen=True)
class CaptureResult:
    """Result of an orchestrated capture operation."""

    loop: dict[str, Any]
    enrichment_requested: bool


def _resolve_recurrence_rrule(input_data: CaptureOrchestrationInput) -> str | None:
    """Normalize schedule input into an RRULE string."""
    if input_data.schedule:
        from .recurrence import parse_recurrence_schedule

        try:
            parsed = parse_recurrence_schedule(input_data.schedule)
        except ValueError as exc:
            raise ValidationError("schedule", str(exc)) from None
        return parsed.rrule
    return input_data.rrule


def _resolve_template_application(
    *,
    input_data: CaptureOrchestrationInput,
    conn: sqlite3.Connection,
    now_utc: datetime,
) -> tuple[str, dict[str, Any], LoopStatus]:
    """Apply any requested template and determine the final initial status."""
    status = input_data.status_flags.resolve()
    raw_text = input_data.raw_text
    template_defaults: dict[str, Any] = {}

    if not input_data.template_ref.requested:
        return raw_text, template_defaults, status

    template = input_data.template_ref.resolve_template(conn=conn)
    if template is None:
        raise ValidationError(
            input_data.template_ref.field_name,
            f"template not found: {input_data.template_ref.identifier}",
        )

    template_defaults = apply_template_to_capture(
        template=template,
        raw_text_override=input_data.raw_text,
        now_utc=now_utc,
        tz_offset_min=input_data.client_tz_offset_min,
    )
    raw_text = template_defaults["raw_text"]

    if not input_data.status_flags.has_explicit_status:
        status = resolve_status_from_flags(
            scheduled=template_defaults.get("scheduled", False),
            blocked=template_defaults.get("blocked", False),
            actionable=template_defaults.get("actionable", False),
        )

    return raw_text, template_defaults, status


def orchestrate_capture(
    *,
    input_data: CaptureOrchestrationInput,
    settings: Settings,
    conn: sqlite3.Connection,
    now_utc: datetime | None = None,
) -> CaptureResult:
    """Capture a loop using the shared orchestration flow."""
    effective_now = now_utc or utc_now()
    recurrence_rrule = _resolve_recurrence_rrule(input_data)
    raw_text, template_defaults, status = _resolve_template_application(
        input_data=input_data,
        conn=conn,
        now_utc=effective_now,
    )
    capture_fields = input_data.field_inputs.to_capture_fields()

    record = service.capture_loop(
        raw_text=raw_text,
        captured_at_iso=input_data.captured_at_iso,
        client_tz_offset_min=input_data.client_tz_offset_min,
        status=status,
        conn=conn,
        recurrence_rrule=recurrence_rrule,
        recurrence_tz=input_data.timezone,
        capture_fields=capture_fields if capture_fields else None,
    )

    if template_defaults:
        update_fields = extract_update_fields_from_template(template_defaults)
        if capture_fields:
            update_fields = {
                key: value for key, value in update_fields.items() if key not in capture_fields
            }
        if update_fields:
            record = service.update_loop(
                loop_id=record["id"],
                fields=update_fields,
                conn=conn,
            )

    enrichment_requested = False
    if settings.autopilot_enabled:
        record = service.request_enrichment(loop_id=record["id"], conn=conn)
        enrichment_requested = True

    return CaptureResult(loop=record, enrichment_requested=enrichment_requested)
