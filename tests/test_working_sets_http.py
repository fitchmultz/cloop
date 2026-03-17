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
    - Run `uv run --locked pytest tests/test_working_sets_http.py -q`

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


def test_working_set_endpoints(make_test_client) -> None:
    client = make_test_client()
    first_loop_id = _capture(client, "Prepare launch checklist")
    second_loop_id = _capture(client, "Draft rollback note")

    create_response = client.post(
        "/loops/working-sets",
        json={
            "name": "Launch reset",
            "description": "Keep the launch cleanup loops and follow-up anchors together.",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    working_set_id = created["id"]
    assert created["item_count"] == 0

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

    add_query_anchor_response = client.post(
        f"/loops/working-sets/{working_set_id}/items",
        json={
            "item_type": "query_anchor",
            "label": "Blocked launch work",
            "description": "Return to blocked launch cleanup if drift appears.",
            "metadata": {
                "query": "status:blocked project:launch",
                "state": "review",
            },
        },
    )
    assert add_query_anchor_response.status_code == 200
    add_query_anchor_payload = add_query_anchor_response.json()
    assert add_query_anchor_payload["item_count"] == 2
    assert add_query_anchor_payload["items"][0]["item_type"] == "query_anchor"
    assert (
        add_query_anchor_payload["items"][0]["launch"]["query"] == "status:blocked project:launch"
    )

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

    reorder_response = client.post(
        f"/loops/working-sets/{working_set_id}/reorder",
        json={"ordered_item_ids": list(reversed(ordered_ids))},
    )
    assert reorder_response.status_code == 200
    reordered = reorder_response.json()
    assert [item["id"] for item in reordered["items"]] == list(reversed(ordered_ids))

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

    update_response = client.patch(
        f"/loops/working-sets/{working_set_id}",
        json={"name": "Launch resume set"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Launch resume set"

    delete_response = client.delete(f"/loops/working-sets/{working_set_id}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}

    cleared_context_response = client.get("/loops/working-sets/context")
    assert cleared_context_response.status_code == 200
    assert cleared_context_response.json()["active_working_set_id"] is None
    assert cleared_context_response.json()["focus_mode_enabled"] is False


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
    assert payload["items"][0]["status_label"] == "Missing loop"
