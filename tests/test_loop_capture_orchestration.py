"""Shared capture orchestration tests.

Purpose:
    Verify the transport-agnostic loop capture orchestration layer that powers
    HTTP, CLI, and MCP capture entrypoints.

Responsibilities:
    - Validate template lookup and precedence rules
    - Validate recurrence input normalization rules
    - Validate explicit capture fields overriding template defaults

Non-scope:
    - Transport-specific request parsing and response shaping
    - Background enrichment execution

Invariants/Assumptions:
    - Tests use isolated temporary databases
    - Autopilot is disabled unless a test opts into it explicitly
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cloop import db
from cloop.loops import repo
from cloop.loops.capture_orchestration import (
    CaptureFieldInputs,
    CaptureOrchestrationInput,
    CaptureStatusFlags,
    CaptureTemplateRef,
    orchestrate_capture,
)
from cloop.loops.errors import ValidationError
from cloop.settings import get_settings


def _setup_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def test_orchestrate_capture_prefers_template_id_over_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """template_id should win when both template_id and template_name are supplied."""
    settings = _setup_settings(tmp_path, monkeypatch)

    with sqlite3.connect(settings.core_db_path) as conn:
        conn.row_factory = sqlite3.Row
        actionable_template = repo.create_loop_template(
            name="Actionable Template",
            description="",
            raw_text_pattern="Actionable pattern",
            defaults_json={"actionable": True},
            conn=conn,
        )
        repo.create_loop_template(
            name="Blocked Template",
            description="",
            raw_text_pattern="Blocked pattern",
            defaults_json={"blocked": True},
            conn=conn,
        )

        result = orchestrate_capture(
            input_data=CaptureOrchestrationInput(
                raw_text="User details",
                captured_at_iso="2026-02-15T10:00:00Z",
                client_tz_offset_min=0,
                status_flags=CaptureStatusFlags(),
                template_ref=CaptureTemplateRef(
                    template_id=actionable_template["id"],
                    template_name="Blocked Template",
                ),
            ),
            settings=settings,
            conn=conn,
        )

    assert result.loop["status"] == "actionable"
    assert result.loop["raw_text"] == "Actionable pattern\n\nUser details"


def test_orchestrate_capture_schedule_phrase_overrides_direct_rrule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Natural-language schedule phrases should take precedence over direct RRULE input."""
    settings = _setup_settings(tmp_path, monkeypatch)

    with sqlite3.connect(settings.core_db_path) as conn:
        conn.row_factory = sqlite3.Row
        result = orchestrate_capture(
            input_data=CaptureOrchestrationInput(
                raw_text="Recurring task",
                captured_at_iso="2026-02-15T10:00:00Z",
                client_tz_offset_min=0,
                status_flags=CaptureStatusFlags(),
                schedule="every weekday",
                rrule="FREQ=MONTHLY;COUNT=1",
            ),
            settings=settings,
            conn=conn,
        )

    assert result.loop["recurrence_rrule"] != "FREQ=MONTHLY;COUNT=1"
    assert "FREQ=WEEKLY" in result.loop["recurrence_rrule"]


def test_orchestrate_capture_keeps_explicit_fields_over_template_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit capture fields should not be overwritten by template defaults."""
    settings = _setup_settings(tmp_path, monkeypatch)

    with sqlite3.connect(settings.core_db_path) as conn:
        conn.row_factory = sqlite3.Row
        template = repo.create_loop_template(
            name="Defaulted Template",
            description="",
            raw_text_pattern="Template pattern",
            defaults_json={
                "project": "Template Project",
                "tags": ["template-tag"],
                "time_minutes": 45,
            },
            conn=conn,
        )

        result = orchestrate_capture(
            input_data=CaptureOrchestrationInput(
                raw_text="User details",
                captured_at_iso="2026-02-15T10:00:00Z",
                client_tz_offset_min=0,
                status_flags=CaptureStatusFlags(),
                template_ref=CaptureTemplateRef(template_id=template["id"]),
                field_inputs=CaptureFieldInputs(
                    project="Explicit Project",
                    tags=["explicit-tag"],
                    time_minutes=15,
                ),
            ),
            settings=settings,
            conn=conn,
        )

    assert result.loop["project"] == "Explicit Project"
    assert result.loop["tags"] == ["explicit-tag"]
    assert result.loop["time_minutes"] == 15


def test_orchestrate_capture_rejects_missing_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown template references should fail validation instead of silently degrading."""
    settings = _setup_settings(tmp_path, monkeypatch)

    with sqlite3.connect(settings.core_db_path) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises(ValidationError, match="template not found"):
            orchestrate_capture(
                input_data=CaptureOrchestrationInput(
                    raw_text="Missing template",
                    captured_at_iso="2026-02-15T10:00:00Z",
                    client_tz_offset_min=0,
                    status_flags=CaptureStatusFlags(),
                    template_ref=CaptureTemplateRef(template_name="missing-template"),
                ),
                settings=settings,
                conn=conn,
            )
