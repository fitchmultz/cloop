"""HTTP tests for durable working sets and focus mode.

Purpose:
    Verify the working-set API persists named sets, ordered membership rows,
    and active focus-mode context for the operator shell.

Responsibilities:
    - Exercise working-set CRUD endpoints
    - Verify working-set membership add/remove/reorder behavior
    - Verify active focus-mode context updates and missing-item handling

Scope:
    - HTTP-level contract verification for the working-set routes only

Usage:
    - Run `uv run --locked --all-groups pytest tests/test_working_sets_http.py -q`

Invariants/Assumptions:
    - Test clients use isolated temporary SQLite databases
    - Working sets return resolved items with launch-ready metadata
    - Missing referenced objects should remain visible instead of breaking the set
"""

from __future__ import annotations

from cloop import db
from cloop.loops import repo
from cloop.settings import get_settings


def _capture(client, raw_text: str) -> int:
    response = client.post(
        "/loops/capture",
        json={
            "raw_text": raw_text,
            "captured_at": "2026-03-16T12:00:00+00:00",
            "client_tz_offset_min": 0,
            "actionable": True,
        },
    )
    assert response.status_code == 200
    return int(response.json()["id"])


def _undo_working_set(client, expected_event_id: int, *, idempotency_key: str | None = None):
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key is not None else None
    return client.post(
        "/loops/working-sets/undo",
        json={"expected_event_id": expected_event_id},
        headers=headers,
    )


def test_working_set_endpoints(make_test_client) -> None:
    client = make_test_client()
    first_loop_id = _capture(client, "Prepare launch checklist")
    second_loop_id = _capture(client, "Draft rollback note")

    create_response = client.post(
        "/loops/working-sets",
        json={
            "name": "Launch reset",
            "description": "Keep the launch cleanup loops and reusable saved items together.",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    working_set_id = created["id"]
    assert created["item_count"] == 0
    assert created["launch"]["state"] == "working_set"
    assert created["launch"]["working_set_id"] == working_set_id
    assert isinstance(created["latest_reversible_event_id"], int)
    assert created["latest_reversible_event_type"] == "create"

    add_loop_response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "loop",
            "item_id": first_loop_id,
            "label": "Launch checklist",
            "description": "Primary execution loop",
            "metadata": {},
        },
    )
    assert add_loop_response.status_code == 200
    add_loop_payload = add_loop_response.json()
    assert add_loop_payload["item_count"] == 1
    assert add_loop_payload["items"][0]["item_type"] == "loop"
    assert add_loop_payload["items"][0]["launch"]["loop_id"] == first_loop_id
    assert add_loop_payload["latest_reversible_event_type"] == "add_item"

    add_query_helper_response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "query_anchor",
            "metadata": {
                "query": "status:blocked project:launch",
                "state": "review",
            },
        },
    )
    assert add_query_helper_response.status_code == 200
    add_query_helper_payload = add_query_helper_response.json()
    assert add_query_helper_payload["item_count"] == 2
    assert add_query_helper_payload["items"][0]["item_type"] == "query_anchor"
    assert (
        add_query_helper_payload["items"][0]["launch"]["query"] == "status:blocked project:launch"
    )
    assert add_query_helper_payload["latest_reversible_event_type"] == "add_item"

    add_second_loop_response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "loop",
            "item_id": second_loop_id,
            "label": "Rollback note",
            "description": "Secondary cleanup loop",
            "metadata": {},
        },
    )
    assert add_second_loop_response.status_code == 200
    add_second_loop_payload = add_second_loop_response.json()
    ordered_ids = [item["id"] for item in add_second_loop_payload["items"]]
    assert len(ordered_ids) == 3
    assert add_second_loop_payload["latest_reversible_event_type"] == "add_item"

    reorder_response = client.post(
        f"/loops/working-sets/{working_set_id}/reorder",
        json={"ordered_item_ids": list(reversed(ordered_ids))},
    )
    assert reorder_response.status_code == 200
    reordered = reorder_response.json()
    assert [item["id"] for item in reordered["items"]] == list(reversed(ordered_ids))
    assert reordered["latest_reversible_event_type"] == "reorder"

    context_response = client.patch(
        "/loops/working-sets/context",
        json={
            "active_working_set_id": working_set_id,
            "focus_mode_enabled": True,
        },
    )
    assert context_response.status_code == 200
    context_payload = context_response.json()
    assert context_payload["active_working_set_id"] == working_set_id
    assert context_payload["focus_mode_enabled"] is True
    assert context_payload["active_working_set"]["name"] == "Launch reset"
    assert context_payload["latest_reversible_event_type"] == "context_update"

    list_response = client.get("/loops/working-sets")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert len(listed) == 1
    assert listed[0]["id"] == working_set_id
    assert listed[0]["item_count"] == 3

    first_item_id = reordered["items"][0]["id"]
    remove_response = client.delete(f"/loops/working-sets/{working_set_id}/items/{first_item_id}")
    assert remove_response.status_code == 200
    removed_payload = remove_response.json()
    assert removed_payload["item_count"] == 2
    assert removed_payload["latest_reversible_event_type"] == "remove_item"

    update_response = client.patch(
        f"/loops/working-sets/{working_set_id}",
        json={"name": "Launch resume set"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Launch resume set"
    assert update_response.json()["latest_reversible_event_type"] == "update"

    delete_response = client.delete(f"/loops/working-sets/{working_set_id}")
    assert delete_response.status_code == 200
    deleted = delete_response.json()
    assert deleted["deleted"] is True
    assert deleted["deleted_working_set_id"] == working_set_id
    assert deleted["deleted_working_set_name"] == "Launch resume set"
    assert deleted["latest_reversible_event_type"] == "delete"
    assert deleted["context"]["active_working_set_id"] is None

    cleared_context_response = client.get("/loops/working-sets/context")
    assert cleared_context_response.status_code == 200
    assert cleared_context_response.json()["active_working_set_id"] is None
    assert cleared_context_response.json()["focus_mode_enabled"] is False


def test_working_set_name_conflicts_return_structured_409(make_test_client) -> None:
    client = make_test_client()

    first_create = client.post(
        "/loops/working-sets",
        json={"name": "Launch reset", "description": "Primary bounded context."},
    )
    assert first_create.status_code == 201
    first_id = int(first_create.json()["id"])

    duplicate_create = client.post(
        "/loops/working-sets",
        json={"name": "Launch reset", "description": "Duplicate bounded context."},
    )
    assert duplicate_create.status_code == 409
    assert duplicate_create.json()["error"]["code"] == "working_set_name_conflict"
    assert "already exists" in duplicate_create.json()["error"]["message"]

    second_create = client.post(
        "/loops/working-sets",
        json={"name": "Rollback reset", "description": "Secondary bounded context."},
    )
    assert second_create.status_code == 201
    second_id = int(second_create.json()["id"])

    duplicate_rename = client.patch(
        f"/loops/working-sets/{second_id}",
        json={"name": "Launch reset"},
    )
    assert duplicate_rename.status_code == 409
    assert duplicate_rename.json()["error"]["code"] == "working_set_name_conflict"
    assert "already exists" in duplicate_rename.json()["error"]["message"]

    first_get = client.get(f"/loops/working-sets/{first_id}")
    second_get = client.get(f"/loops/working-sets/{second_id}")
    assert first_get.status_code == 200
    assert second_get.status_code == 200
    assert first_get.json()["name"] == "Launch reset"
    assert second_get.json()["name"] == "Rollback reset"


def test_working_set_undo_restore_name_conflicts_return_structured_409(
    make_test_client,
) -> None:
    client = make_test_client()

    create_response = client.post(
        "/loops/working-sets",
        json={"name": "Launch reset", "description": "Original bounded context."},
    )
    assert create_response.status_code == 201
    original_id = int(create_response.json()["id"])

    delete_response = client.delete(f"/loops/working-sets/{original_id}")
    assert delete_response.status_code == 200
    delete_event_id = int(delete_response.json()["latest_reversible_event_id"])

    replacement_response = client.post(
        "/loops/working-sets",
        json={"name": "Launch reset", "description": "Replacement bounded context."},
    )
    assert replacement_response.status_code == 201
    replacement_id = int(replacement_response.json()["id"])

    undo_response = _undo_working_set(client, delete_event_id)
    assert undo_response.status_code == 409
    assert undo_response.json()["error"]["code"] == "working_set_name_conflict"
    assert "already exists" in undo_response.json()["error"]["message"]

    replacement_get = client.get(f"/loops/working-sets/{replacement_id}")
    original_get = client.get(f"/loops/working-sets/{original_id}")
    assert replacement_get.status_code == 200
    assert original_get.status_code == 404


def test_working_set_undo_rejects_stale_handles(make_test_client) -> None:
    client = make_test_client()

    create_response = client.post(
        "/loops/working-sets",
        json={
            "name": "Undo stale handle",
            "description": "Exercise exact working-set undo handles.",
        },
    )
    assert create_response.status_code == 201
    working_set_id = int(create_response.json()["id"])

    first_update = client.patch(
        f"/loops/working-sets/{working_set_id}",
        json={"name": "Undo stale handle v2"},
    )
    assert first_update.status_code == 200
    stale_event_id = int(first_update.json()["latest_reversible_event_id"])

    second_update = client.patch(
        f"/loops/working-sets/{working_set_id}",
        json={"name": "Undo stale handle v3"},
    )
    assert second_update.status_code == 200
    latest_event_id = int(second_update.json()["latest_reversible_event_id"])

    stale_response = _undo_working_set(client, stale_event_id)
    assert stale_response.status_code == 400
    stale_error = stale_response.json()["error"]
    assert stale_error["code"] == "undo_not_possible"
    assert stale_error["details"]["reason"] == "stale_event_handle"

    undo_response = _undo_working_set(client, latest_event_id)
    assert undo_response.status_code == 200
    undo_payload = undo_response.json()
    assert undo_payload["undone_event_id"] == latest_event_id
    assert undo_payload["undone_event_type"] == "update"
    assert undo_payload["working_set"]["name"] == "Undo stale handle v2"


def test_working_set_delete_undo_restores_active_context(make_test_client) -> None:
    client = make_test_client()

    create_response = client.post(
        "/loops/working-sets",
        json={"name": "Delete restore", "description": "Restore active context after delete."},
    )
    assert create_response.status_code == 201
    working_set_id = int(create_response.json()["id"])

    context_response = client.patch(
        "/loops/working-sets/context",
        json={"active_working_set_id": working_set_id, "focus_mode_enabled": True},
    )
    assert context_response.status_code == 200
    assert context_response.json()["active_working_set_id"] == working_set_id
    assert context_response.json()["focus_mode_enabled"] is True

    delete_response = client.delete(f"/loops/working-sets/{working_set_id}")
    assert delete_response.status_code == 200
    deleted = delete_response.json()
    assert deleted["context"]["active_working_set_id"] is None
    assert deleted["context"]["focus_mode_enabled"] is False

    undo_response = _undo_working_set(client, int(deleted["latest_reversible_event_id"]))
    assert undo_response.status_code == 200
    undo_payload = undo_response.json()
    assert undo_payload["working_set"]["id"] == working_set_id
    assert undo_payload["context"]["active_working_set_id"] == working_set_id
    assert undo_payload["context"]["focus_mode_enabled"] is True
    assert undo_payload["context"]["active_working_set"]["name"] == "Delete restore"


def test_working_set_context_undo_restores_prior_focus_state(make_test_client) -> None:
    client = make_test_client()

    first_create = client.post(
        "/loops/working-sets",
        json={"name": "Context one", "description": "First bounded context."},
    )
    second_create = client.post(
        "/loops/working-sets",
        json={"name": "Context two", "description": "Second bounded context."},
    )
    assert first_create.status_code == 201
    assert second_create.status_code == 201
    first_id = int(first_create.json()["id"])
    second_id = int(second_create.json()["id"])

    first_context = client.patch(
        "/loops/working-sets/context",
        json={"active_working_set_id": first_id, "focus_mode_enabled": True},
    )
    assert first_context.status_code == 200

    second_context = client.patch(
        "/loops/working-sets/context",
        json={"active_working_set_id": second_id, "focus_mode_enabled": False},
    )
    assert second_context.status_code == 200
    latest_event_id = int(second_context.json()["latest_reversible_event_id"])

    undo_response = _undo_working_set(client, latest_event_id)
    assert undo_response.status_code == 200
    undo_payload = undo_response.json()
    assert undo_payload["undone_event_type"] == "context_update"
    assert undo_payload["context"]["active_working_set_id"] == first_id
    assert undo_payload["context"]["focus_mode_enabled"] is True
    assert undo_payload["context"]["active_working_set"]["name"] == "Context one"


def test_working_set_bulk_add_and_undo(make_test_client) -> None:
    client = make_test_client()
    first_loop_id = _capture(client, "Bulk add first")
    second_loop_id = _capture(client, "Bulk add second")

    create_response = client.post(
        "/loops/working-sets",
        json={"name": "Bulk add", "description": "Undo bulk saved-item creation."},
    )
    assert create_response.status_code == 201
    working_set_id = int(create_response.json()["id"])

    bulk_response = client.post(
        f"/loops/working-sets/{working_set_id}/items/bulk",
        json={
            "items": [
                {
                    "item_type": "loop",
                    "item_id": first_loop_id,
                    "label": "Bulk first",
                    "description": "First bulk loop",
                    "metadata": {},
                },
                {
                    "item_type": "loop",
                    "item_id": second_loop_id,
                    "label": "Bulk second",
                    "description": "Second bulk loop",
                    "metadata": {},
                },
            ]
        },
    )
    assert bulk_response.status_code == 200
    bulk_payload = bulk_response.json()
    assert bulk_payload["item_count"] == 2
    assert bulk_payload["latest_reversible_event_type"] == "bulk_add_items"

    undo_response = _undo_working_set(client, int(bulk_payload["latest_reversible_event_id"]))
    assert undo_response.status_code == 200
    undo_payload = undo_response.json()
    assert undo_payload["working_set"]["item_count"] == 0
    assert undo_payload["working_set"]["items"] == []


def test_working_set_undo_replays_idempotently(make_test_client) -> None:
    client = make_test_client()

    create_response = client.post(
        "/loops/working-sets",
        json={"name": "Idempotent undo", "description": "Replay working-set undo safely."},
    )
    assert create_response.status_code == 201
    working_set_id = int(create_response.json()["id"])

    update_response = client.patch(
        f"/loops/working-sets/{working_set_id}",
        json={"name": "Idempotent undo renamed"},
    )
    assert update_response.status_code == 200
    event_id = int(update_response.json()["latest_reversible_event_id"])

    first_undo = _undo_working_set(client, event_id, idempotency_key="working-set-undo-idem")
    assert first_undo.status_code == 200
    second_undo = _undo_working_set(client, event_id, idempotency_key="working-set-undo-idem")
    assert second_undo.status_code == 200
    assert second_undo.json() == first_undo.json()


def test_working_set_query_launch_helper_round_trips_recall_tool(make_test_client) -> None:
    client = make_test_client()
    create_response = client.post(
        "/loops/working-sets",
        json={
            "name": "Recall helper",
            "description": "Verify recall query launch helpers keep their tool.",
        },
    )
    assert create_response.status_code == 201
    working_set_id = int(create_response.json()["id"])

    response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "query_anchor",
            "label": "Recall · Documents",
            "description": "Reopen the evidence question.",
            "metadata": {
                "query": "What changed in the roadmap?",
                "state": "recall",
                "recall_tool": "rag",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["item_count"] == 1
    assert payload["items"][0]["item_type"] == "query_anchor"
    assert payload["items"][0]["launch"]["state"] == "recall"
    assert payload["items"][0]["launch"]["recall_tool"] == "rag"
    assert payload["items"][0]["launch"]["query"] == "What changed in the roadmap?"


def test_working_set_state_launch_helper_requires_working_set_id_for_working_set_launch(
    make_test_client,
) -> None:
    client = make_test_client()
    create_response = client.post(
        "/loops/working-sets",
        json={"name": "Session launch", "description": "Validate working-set saved locations."},
    )
    assert create_response.status_code == 201
    working_set_id = int(create_response.json()["id"])

    response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "state_anchor",
            "label": "Resume this working set",
            "description": "Open the dedicated working-set session.",
            "metadata": {"state": "working_set"},
        },
    )

    assert response.status_code == 400
    assert "working_set_id" in response.text


def test_working_set_state_launch_helper_rejects_boolean_metadata_ids(make_test_client) -> None:
    client = make_test_client()
    create_response = client.post(
        "/loops/working-sets",
        json={"name": "Strict ids", "description": "Reject boolean metadata ids."},
    )
    assert create_response.status_code == 201
    working_set_id = int(create_response.json()["id"])

    response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "state_anchor",
            "label": "Bad working set launch",
            "metadata": {"state": "working_set", "working_set_id": True},
        },
    )
    assert response.status_code == 400
    assert "working_set_id" in response.text

    response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "state_anchor",
            "label": "Bad plan launch",
            "metadata": {"state": "plan", "session_id": True},
        },
    )
    assert response.status_code == 400
    assert "session_id" in response.text


def test_working_set_returns_missing_items_instead_of_breaking(make_test_client) -> None:
    client = make_test_client()
    loop_id = _capture(client, "Remove this loop later")

    create_response = client.post(
        "/loops/working-sets",
        json={"name": "Missing-state test", "description": "Ensure deleted items remain visible."},
    )
    assert create_response.status_code == 201
    working_set_id = int(create_response.json()["id"])

    add_response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "loop",
            "item_id": loop_id,
            "label": "Transient loop",
            "description": "Will be deleted after pinning.",
            "metadata": {},
        },
    )
    assert add_response.status_code == 200

    with db.core_connection(get_settings()) as conn:
        deleted = repo.delete_loop(loop_id=loop_id, conn=conn)
        assert deleted is True
        conn.commit()

    get_response = client.get(f"/loops/working-sets/{working_set_id}")
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["missing_item_count"] == 1
    assert payload["items"][0]["missing"] is True
