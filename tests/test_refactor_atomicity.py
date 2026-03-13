"""Transaction ownership regression tests.

Purpose:
    Lock in the refactor that moved commit ownership out of repository helpers
    and back into caller-owned transactions.

Responsibilities:
    - Verify multi-step domain flows roll back when downstream work fails
    - Verify repo mutation helpers no longer commit behind the caller's back
    - Exercise representative claims, dependency, and template flows

Non-scope:
    - Transport-level HTTP/MCP/CLI response contracts
    - Broad CRUD coverage already handled by subsystem test files

Invariants/Assumptions:
    - Each test uses an isolated core database rooted in tmp_path
    - `db.core_connection(...)` is the canonical connection entrypoint
    - Rollback assertions use a fresh connection to avoid seeing uncommitted rows
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cloop import db
from cloop.loops import claims as loop_claims
from cloop.loops import repo, service
from cloop.loops.models import LoopStatus, format_utc_datetime, utc_now
from cloop.settings import Settings, get_settings


def _setup_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_PI_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_PI_ORGANIZER_MODEL", "mock-organizer")
    get_settings.cache_clear()
    settings = get_settings()
    db.init_databases(settings)
    return settings


def _capture_loop(settings: Settings, *, raw_text: str, status: LoopStatus) -> dict[str, Any]:
    with db.core_connection(settings) as conn:
        return service.capture_loop(
            raw_text=raw_text,
            captured_at_iso=format_utc_datetime(utc_now()),
            client_tz_offset_min=0,
            status=status,
            conn=conn,
        )


def test_claim_loop_rolls_back_when_webhook_queue_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claim creation should not persist the claim or event if queueing fails."""
    settings = _setup_settings(tmp_path, monkeypatch)
    loop_record = _capture_loop(settings, raw_text="Claim rollback", status=LoopStatus.INBOX)
    loop_id = int(loop_record["id"])

    def _boom(**_: object) -> None:
        raise RuntimeError("queue failed")

    monkeypatch.setattr(loop_claims, "queue_deliveries", _boom)

    with db.core_connection(settings) as conn:
        with pytest.raises(RuntimeError, match="queue failed"):
            loop_claims.claim_loop(
                loop_id=loop_id,
                owner="agent-rollback",
                conn=conn,
                settings=settings,
            )

    with db.core_connection(settings) as conn:
        assert repo.read_claim(loop_id=loop_id, conn=conn) is None
        event_types = [
            event["event_type"] for event in repo.list_loop_events(loop_id=loop_id, conn=conn)
        ]
        assert "claim" not in event_types


def test_add_loop_dependency_rolls_back_when_follow_up_status_update_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dependency insertion should roll back if the derived status change fails."""
    settings = _setup_settings(tmp_path, monkeypatch)
    loop_record = _capture_loop(settings, raw_text="Needs blocker", status=LoopStatus.ACTIONABLE)
    blocker_record = _capture_loop(settings, raw_text="Open blocker", status=LoopStatus.INBOX)
    loop_id = int(loop_record["id"])
    blocker_id = int(blocker_record["id"])

    original_update = service.repo.update_loop_fields

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("derived status failed")

    monkeypatch.setattr(service.repo, "update_loop_fields", _boom)

    with db.core_connection(settings) as conn:
        with pytest.raises(RuntimeError, match="derived status failed"):
            service.add_loop_dependency(
                loop_id=loop_id,
                depends_on_loop_id=blocker_id,
                conn=conn,
            )

    monkeypatch.setattr(service.repo, "update_loop_fields", original_update)

    with db.core_connection(settings) as conn:
        assert repo.list_dependencies(loop_id=loop_id, conn=conn) == []
        refreshed = repo.read_loop(loop_id=loop_id, conn=conn)
        assert refreshed is not None
        assert refreshed.status is LoopStatus.ACTIONABLE


def test_create_loop_template_does_not_commit_without_caller_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repository template creation should stay invisible until the caller commits."""
    settings = _setup_settings(tmp_path, monkeypatch)

    with db.core_connection(settings) as conn:
        created = repo.create_loop_template(
            name="Transient Template",
            description="Created inside an uncommitted transaction",
            raw_text_pattern="Pattern",
            defaults_json={"tags": ["draft"]},
            is_system=False,
            conn=conn,
        )

        with db.core_connection(settings) as verify_conn:
            assert repo.get_loop_template(template_id=created["id"], conn=verify_conn) is None

        conn.rollback()

    with db.core_connection(settings) as verify_conn:
        assert repo.get_loop_template(template_id=created["id"], conn=verify_conn) is None
