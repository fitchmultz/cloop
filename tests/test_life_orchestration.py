"""Tests for the Life feed contract."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient


def _status_for_test_life_state(life_state: str) -> str:
    return {
        "captured": "inbox",
        "active": "actionable",
        "needs_clarification": "blocked",
        "prepared": "actionable",
        "scheduled": "scheduled",
        "waiting": "blocked",
        "blocked": "blocked",
        "stale": "actionable",
        "completed": "completed",
        "archived": "dropped",
        "abandoned": "dropped",
    }[life_state]


def _status_for_test_cleanup_action(action: str) -> str | None:
    return {
        "complete": "completed",
        "archive": "dropped",
        "abandon": "dropped",
        "reschedule": "scheduled",
        "mark_waiting": "blocked",
        "mark_active": "actionable",
        "delegate": "blocked",
        "update_priority": "actionable",
    }.get(action)


def _life_state_for_test_cleanup_action(action: str) -> str | None:
    return {
        "complete": "completed",
        "archive": "archived",
        "abandon": "abandoned",
        "delete": "deleted",
        "reschedule": "scheduled",
        "mark_waiting": "waiting",
        "mark_active": "active",
        "delegate": "waiting",
        "update_priority": "active",
        "merge": "active",
        "add_dependency": "waiting",
        "remove_dependency": "active",
    }.get(action)


def _complete_test_agent_contract(payload: dict[str, Any]) -> dict[str, Any]:
    for capture in payload.get("captures", []):
        if isinstance(capture, dict) and "life_state" in capture:
            capture.setdefault(
                "loop_status",
                _status_for_test_life_state(str(capture["life_state"])),
            )
    for update in payload.get("updates", []):
        if isinstance(update, dict) and "life_state" in update:
            update.setdefault("loop_status", _status_for_test_life_state(str(update["life_state"])))
    for action in payload.get("cleanup_actions", []):
        if not isinstance(action, dict):
            continue
        target_status = _status_for_test_cleanup_action(str(action.get("action") or ""))
        if target_status is not None:
            action.setdefault("target_loop_status", target_status)
        result_life_state = _life_state_for_test_cleanup_action(str(action.get("action") or ""))
        if result_life_state is not None:
            action.setdefault("result_life_state", result_life_state)
    return payload


def _agent_response(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return json.dumps(_complete_test_agent_contract(payload)), {
        "model": "mock-organizer",
        "usage": {},
    }


def _user_payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(messages[1]["content"]))


def _post_life(client: TestClient, message: str, **extra: object) -> dict[str, Any]:
    response = client.post(
        "/life/message",
        json={
            "message": message,
            "captured_at": extra.pop("captured_at", "2026-05-07T08:00:00-06:00"),
            "client_tz_offset_min": extra.pop("client_tz_offset_min", -360),
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json())


def test_life_agent_accepts_null_for_omittable_collection_fields(
    make_test_client, monkeypatch
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        return json.dumps(
            {
                "mode": "capture",
                "reply": "Captured the dentist appointment loop.",
                "updates": None,
                "memories": None,
                "captures": [
                    {
                        "raw_text": "Schedule dentist appointment by Friday",
                        "title": "Schedule dentist appointment",
                        "life_state": "active",
                        "loop_status": "actionable",
                        "next_action": "Call dentist office",
                        "prepared_actions": None,
                        "tags": None,
                        "related_loop_ids": None,
                        "relationship_type": None,
                        "group_names": None,
                        "source_evidence": None,
                    }
                ],
                "groups": [
                    {
                        "name": "needs_attention_today",
                        "title": "Needs attention today",
                        "summary": "Fresh captures that need a next action.",
                        "items": [
                            {
                                "loop_id": "captured_0",
                                "life_state": "active",
                                "rationale": "The capture has not been persisted yet.",
                                "prepared_actions": None,
                            }
                        ],
                    }
                ],
            }
        ), {"model": "mock-organizer", "usage": {}}

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)

    payload = _post_life(client, "Schedule dentist appointment by Friday")

    assert payload["captured"][0]["loop"]["title"] == "Schedule dentist appointment"
    assert payload["captured"][0]["loop"]["next_action"] == "Call dentist office"
    assert payload["captured"][0]["prepared_actions"] == []
    assert payload["groups"][0]["items"][0]["loop"]["title"] == "Schedule dentist appointment"


def test_life_message_splits_messy_dump_into_multiple_loops(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        assert "Return only JSON" in messages[0]["content"]
        return _agent_response(
            {
                "mode": "capture",
                "reply": "Captured 5 loops. Quick win: Send availability to the recruiter.",
                "captures": [
                    {
                        "raw_text": "update my DOE CR",
                        "title": "Update my DOE CR",
                        "life_state": "active",
                        "next_action": "Open the DOE CR",
                    },
                    {
                        "raw_text": "send availability to the recruiter",
                        "title": "Send availability to the recruiter",
                        "life_state": "active",
                        "next_action": "Send availability to the recruiter",
                        "time_minutes": 3,
                        "emotional_weight": 0.2,
                        "confidence": 0.92,
                        "group_names": ["quick_wins"],
                    },
                    {
                        "raw_text": "pick up medicine",
                        "title": "Pick up medicine",
                        "life_state": "active",
                    },
                    {
                        "raw_text": "research that supplement",
                        "title": "Research that supplement",
                        "summary": "Warm research context.",
                        "life_state": "captured",
                        "group_names": ["ideas_not_tasks"],
                    },
                    {
                        "raw_text": "look into a new shaft for my 9-iron",
                        "title": "Golf shaft",
                        "summary": "Warm research context.",
                        "life_state": "captured",
                        "group_names": ["ideas_not_tasks"],
                    },
                ],
                "groups": [
                    {
                        "name": "quick_wins",
                        "title": "Tiny wins",
                        "summary": "Agent-picked low-friction loops.",
                        "loop_ids": [],
                    },
                    {
                        "name": "ideas_not_tasks",
                        "title": "Ideas to hold lightly",
                        "summary": "Agent-picked context that should not become pressure.",
                        "loop_ids": [],
                    },
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    payload = _post_life(
        client,
        (
            "Need to update my DOE CR, send availability to the recruiter, pick up medicine, "
            "research that supplement, and look into a new shaft for my 9-iron."
        ),
    )

    assert payload["mode"] == "capture"
    assert "Captured 5 loops" in payload["reply"]
    captured = payload["captured"]
    assert len(captured) == 5
    titles = [item["loop"]["title"] for item in captured]
    assert "Update my DOE CR" in titles
    assert "Send availability to the recruiter" in titles
    assert any(item["loop"]["time_minutes"] == 3 for item in captured)
    recruiter = next(
        item for item in captured if item["loop"]["title"] == "Send availability to the recruiter"
    )
    assert recruiter["loop"]["emotional_weight"] == 0.2
    assert recruiter["loop"]["confidence"] == 0.92
    groups = {group["name"]: group for group in payload["groups"]}
    assert "quick_wins" in groups
    assert groups["quick_wins"]["title"] == "Tiny wins"
    assert "ideas_not_tasks" in groups


def test_life_message_attaches_duplicate_mentions_to_open_loop(
    make_test_client, monkeypatch
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the medicine loop.",
                    "captures": [
                        {
                            "raw_text": "Need to pick up medicine",
                            "title": "Pick up medicine",
                            "life_state": "active",
                        }
                    ],
                }
            )
        loop_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "capture",
                "reply": "Attached that to the existing medicine loop.",
                "captures": [
                    {
                        "raw_text": "Medicine got refilled yesterday",
                        "duplicate_of_loop_id": loop_id,
                        "life_state": "active",
                        "rationale": "This is the same existing open loop.",
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    first = _post_life(client, "Need to pick up medicine")
    assert len(first["captured"]) == 1

    second = _post_life(client, "Medicine got refilled yesterday")

    assert second["mode"] == "capture"
    assert second["captured"] == []
    assert len(second["updated"]) == 1
    assert "existing open loop" in second["updated"][0]["rationale"]


def test_life_capture_can_link_related_context(
    make_test_client, monkeypatch, tmp_path: Path
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the camping loop.",
                    "captures": [
                        {
                            "raw_text": "Plan camping with Ryan",
                            "title": "Plan camping with Ryan",
                            "life_state": "active",
                        }
                    ],
                }
            )
        related_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "capture",
                "reply": "Captured that and linked it to camping.",
                "captures": [
                    {
                        "raw_text": "Get back to Ryan about this weekend",
                        "title": "Reply to Ryan",
                        "life_state": "active",
                        "related_loop_ids": [related_id],
                        "relationship_type": "related",
                        "relationship_confidence": 0.86,
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    existing_id = _post_life(client, "Plan camping with Ryan")["captured"][0]["loop"]["id"]

    payload = _post_life(client, "Get back to Ryan about this weekend")

    new_id = payload["captured"][0]["loop"]["id"]
    assert payload["evidence"]["context_links_created"] == 1
    with closing(sqlite3.connect(tmp_path / "core.db")) as conn:
        rows = conn.execute(
            """
            SELECT loop_id, related_loop_id, relationship_type, source
            FROM loop_links
            WHERE relationship_type = 'related'
            ORDER BY loop_id ASC
            """
        ).fetchall()
    assert (new_id, existing_id, "related", "life_agent") in rows
    assert (existing_id, new_id, "related", "life_agent") in rows


def test_life_agent_receives_and_preserves_external_source_evidence(
    make_test_client, monkeypatch
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        external_inputs = user_payload["external_inputs"]
        assert external_inputs == [
            {
                "kind": "image",
                "label": "pharmacy.png",
                "media_type": "image/png",
                "size_bytes": 1234,
            },
            {
                "kind": "link",
                "label": "https://example.com/prescription",
                "source_url": "https://example.com/prescription",
            },
        ]
        return _agent_response(
            {
                "mode": "capture",
                "reply": "Captured the pharmacy pickup with source context.",
                "captures": [
                    {
                        "raw_text": "Pick up medicine with attached pharmacy evidence",
                        "title": "Pick up medicine",
                        "life_state": "active",
                        "source_evidence": [
                            "pharmacy.png",
                            "https://example.com/prescription",
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)

    payload = _post_life(
        client,
        "This is the pharmacy pickup source.",
        external_inputs=[
            {
                "kind": "image",
                "label": "pharmacy.png",
                "media_type": "image/png",
                "size_bytes": 1234,
            },
            {
                "kind": "link",
                "label": "https://example.com/prescription",
                "source_url": "https://example.com/prescription",
            },
        ],
    )

    loop_id = payload["captured"][0]["loop"]["id"]
    loop = client.get(f"/loops/{loop_id}").json()
    assert loop["provenance"]["life_source_evidence"] == [
        {
            "kind": "image",
            "label": "pharmacy.png",
            "media_type": "image/png",
            "size_bytes": 1234,
        },
        {
            "kind": "link",
            "label": "https://example.com/prescription",
            "source_url": "https://example.com/prescription",
        },
    ]


def test_life_preference_message_creates_preference_memory(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        return _agent_response(
            {
                "mode": "preference",
                "reply": "Got it. I will ask before recruiter emails.",
                "memories": [
                    {
                        "content": "Never send recruiter emails without asking me first.",
                        "key": "life.preference.recruiter_email_approval",
                        "priority": 90,
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    payload = _post_life(client, "Never send recruiter emails without asking me first.")

    assert payload["mode"] == "preference"
    assert payload["memories"][0]["category"] == "preference"
    assert (
        payload["memories"][0]["content"] == "Never send recruiter emails without asking me first."
    )


def test_life_agent_can_store_basic_pattern_memory(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        return _agent_response(
            {
                "mode": "preference",
                "reply": "Noted. Research loops tend to sit unless they get a tiny first step.",
                "memories": [
                    {
                        "content": (
                            "User often defers vague research loops unless they are reduced "
                            "to a 10-minute decision."
                        ),
                        "key": "life.pattern.research_deferral",
                        "category": "pattern",
                        "memory_layer": "warm",
                        "priority": 70,
                        "source": "inferred",
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    payload = _post_life(client, "I keep putting off vague research ideas.")

    assert payload["mode"] == "preference"
    assert payload["memories"][0]["category"] == "pattern"
    assert payload["memories"][0]["source"] == "inferred"
    assert payload["memories"][0]["metadata"]["life_layer"] == "warm"


def test_life_agent_receives_tone_and_autonomy_memory(make_test_client, monkeypatch) -> None:
    client = make_test_client()
    response = client.post(
        "/memory",
        json={
            "key": "life.preference.tone",
            "content": "User wants direct momentum-oriented tone for errands.",
            "category": "preference",
            "priority": 90,
            "metadata": {"life_layer": "active"},
        },
    )
    assert response.status_code == 201

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        assert "direct momentum-oriented tone" in user_payload["memory_context"]
        assert "adapt tone" in messages[0]["content"]
        assert "autonomy policy" in messages[0]["content"]
        return _agent_response(
            {
                "mode": "resurface",
                "reply": "Nothing needs a shove right now.",
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)

    payload = _post_life(client, "What matters today?")

    assert payload["mode"] == "resurface"


def test_life_agent_can_store_active_and_cold_memory_layers(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        return _agent_response(
            {
                "mode": "preference",
                "reply": "I moved the current job search context into memory layers.",
                "memories": [
                    {
                        "content": "Job search is the active life context this week.",
                        "key": "life.context.job_search",
                        "category": "context",
                        "memory_layer": "active",
                        "priority": 85,
                    },
                    {
                        "content": "Old golf-shaft research can stay as history.",
                        "key": "life.context.golf_shaft",
                        "category": "context",
                        "memory_layer": "cold",
                        "priority": 30,
                        "source": "inferred",
                    },
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    payload = _post_life(client, "Job search matters this week. Golf shaft can just be history.")

    layers = {memory["key"]: memory["metadata"]["life_layer"] for memory in payload["memories"]}
    assert layers == {
        "life.context.job_search": "active",
        "life.context.golf_shaft": "cold",
    }


def test_life_agent_can_store_person_and_event_memory(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        return _agent_response(
            {
                "mode": "preference",
                "reply": "I kept Ryan and the camping plan as useful context.",
                "memories": [
                    {
                        "content": "Ryan is the person tied to the camping weekend plan.",
                        "key": "life.person.ryan",
                        "category": "person",
                        "memory_layer": "warm",
                        "priority": 75,
                        "source": "inferred",
                    },
                    {
                        "content": "Camping weekend is an event that can collect related loops.",
                        "key": "life.event.camping_weekend",
                        "category": "event",
                        "memory_layer": "warm",
                        "priority": 70,
                        "source": "inferred",
                    },
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    payload = _post_life(client, "Ryan and I need to sort out camping this weekend.")

    categories = {memory["key"]: memory["category"] for memory in payload["memories"]}
    assert categories == {
        "life.person.ryan": "person",
        "life.event.camping_weekend": "event",
    }


def test_life_agent_can_ask_optional_contextual_clarification(
    make_test_client,
    monkeypatch,
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        schema_payload = json.loads(messages[2]["content"])
        assert "clarifications" in schema_payload
        assert "capture_index" in schema_payload["clarifications"][0]
        assert "blocking wizard" in messages[0]["content"]
        return _agent_response(
            {
                "mode": "capture",
                "reply": "Captured. Assuming CostMedica unless different.",
                "captures": [
                    {
                        "raw_text": "Need to pick up medicine",
                        "title": "Pick up medicine",
                        "life_state": "needs_clarification",
                    }
                ],
                "clarifications": [
                    {
                        "capture_index": 0,
                        "question": "Is this CostMedica, or a different pharmacy?",
                        "assumption": "Assuming CostMedica unless different.",
                        "rationale": "Location changes the errand plan.",
                        "improves": ["location", "next_action"],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)

    payload = _post_life(client, "Need to pick up medicine.")

    clarification = payload["clarifications"][0]
    loop_id = payload["captured"][0]["loop"]["id"]
    assert clarification["loop_id"] == loop_id
    assert clarification["clarification_id"] > 0
    assert clarification["question"] == "Is this CostMedica, or a different pharmacy?"
    assert clarification["assumption"] == "Assuming CostMedica unless different."
    stored = client.get(f"/loops/{loop_id}/clarifications").json()["clarifications"]
    assert stored[0]["id"] == clarification["clarification_id"]
    assert stored[0]["question"] == clarification["question"]


def test_life_agent_can_record_conversational_clarification_answer(
    make_test_client,
    monkeypatch,
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        schema_payload = json.loads(messages[2]["content"])
        assert "clarification_answers" in schema_payload
        if "Need to pick up medicine" in user_payload["user_message"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured. Assuming CostMedica unless different.",
                    "captures": [
                        {
                            "raw_text": "Need to pick up medicine",
                            "title": "Pick up medicine",
                            "life_state": "needs_clarification",
                        }
                    ],
                    "clarifications": [
                        {
                            "capture_index": 0,
                            "question": "Is this CostMedica, or a different pharmacy?",
                            "assumption": "Assuming CostMedica unless different.",
                            "rationale": "Location changes the errand plan.",
                            "improves": ["location"],
                        }
                    ],
                }
            )

        pending = [
            clarification
            for loop in user_payload["open_loops"]
            for clarification in loop["pending_clarifications"]
        ]
        assert len(pending) == 1
        clarification_id = pending[0]["id"]
        loop_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "capture",
                "reply": "Got it. I updated the pickup location.",
                "updates": [
                    {
                        "loop_id": loop_id,
                        "life_state": "active",
                        "fields": {
                            "summary": "Pick up medicine at Costco.",
                            "next_action": "Pick up medicine at Costco.",
                        },
                        "rationale": "The user answered the pending pharmacy clarification.",
                    }
                ],
                "clarification_answers": [
                    {
                        "clarification_id": clarification_id,
                        "loop_id": loop_id,
                        "answer": "Costco",
                        "rationale": "This answers the pending pharmacy question.",
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)

    first_payload = _post_life(client, "Need to pick up medicine.")
    loop_id = first_payload["captured"][0]["loop"]["id"]
    clarification_id = first_payload["clarifications"][0]["clarification_id"]

    second_payload = _post_life(client, "Actually Costco.")

    answers = second_payload["answered_clarifications"]
    assert answers == [
        {
            "clarification_id": clarification_id,
            "loop_id": loop_id,
            "question": "Is this CostMedica, or a different pharmacy?",
            "answer": "Costco",
            "rationale": "This answers the pending pharmacy question.",
        }
    ]
    updated_loop = second_payload["updated"][0]["loop"]
    assert updated_loop["summary"] == "Pick up medicine at Costco."
    stored = client.get(f"/loops/{loop_id}/clarifications").json()["clarifications"]
    assert stored[0]["answer"] == "Costco"


def test_life_agent_can_move_and_compress_existing_memory(make_test_client, monkeypatch) -> None:
    client = make_test_client()
    created = client.post(
        "/memory",
        json={
            "key": "life.context.old_research",
            "content": "Supplement research has been mentioned many times but has no deadline.",
            "category": "context",
            "priority": 80,
            "source": "inferred",
            "metadata": {"life_layer": "active"},
        },
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        assert user_payload["memory_entries"][0]["id"] == memory_id
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "I compressed that stale research context and moved it cold.",
                "memory_updates": [
                    {
                        "memory_id": memory_id,
                        "action": "archive_cold",
                        "rationale": "It is stale context, not active mental load.",
                        "apply_now": True,
                        "memory_layer": "cold",
                        "content": "Supplement research is cold context unless it gets a deadline.",
                        "priority": 25,
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)

    payload = _post_life(client, "Clean up stale research context.")

    assert payload["memories"][0]["id"] == memory_id
    assert payload["memories"][0]["content"] == (
        "Supplement research is cold context unless it gets a deadline."
    )
    assert payload["memories"][0]["priority"] == 25
    assert payload["memories"][0]["metadata"]["life_layer"] == "cold"
    assert payload["memories"][0]["metadata"]["updated_by"] == "life_agent"


def test_life_agent_can_surface_prepared_and_stale_states(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured and prepared the supplement loop.",
                    "captures": [
                        {
                            "raw_text": "Research that supplement",
                            "title": "Research supplement",
                            "life_state": "prepared",
                            "next_action": "Spend 10 minutes checking the active ingredient.",
                            "group_names": ["prepared_for_review"],
                        }
                    ],
                    "groups": [
                        {
                            "name": "prepared_for_review",
                            "title": "Ready for your review",
                            "summary": "Agent-prepared loops with a concrete next step.",
                            "loop_ids": [],
                        }
                    ],
                }
            )
        loop_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "resurface",
                "reply": "This research loop is stale. Decide or release it.",
                "updates": [
                    {
                        "loop_id": loop_id,
                        "life_state": "stale",
                        "prepared_next_action": "Turn it into a 10-minute decision brief.",
                        "rationale": "It is vague and has not moved.",
                        "group_names": ["stale_needs_decision"],
                    }
                ],
                "groups": [
                    {
                        "name": "stale_needs_decision",
                        "title": "Agent says decide or release",
                        "summary": "This group title comes from the organizer.",
                        "items": [
                            {
                                "loop_id": loop_id,
                                "life_state": "stale",
                                "rationale": "It is vague and has not moved.",
                            }
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    first = _post_life(client, "Research that supplement")

    assert first["captured"][0]["life_state"] == "prepared"
    assert first["captured"][0]["loop"]["status"] == "actionable"

    second = _post_life(client, "What matters today?")

    assert second["updated"][0]["life_state"] == "stale"
    assert second["updated"][0]["prepared_next_action"] == (
        "Turn it into a 10-minute decision brief."
    )
    assert second["groups"][0]["name"] == "stale_needs_decision"
    assert second["groups"][0]["title"] == "Agent says decide or release"


def test_life_agent_can_return_prepared_action_drafts(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        return _agent_response(
            {
                "mode": "capture",
                "reply": "Drafted it for review.",
                "captures": [
                    {
                        "raw_text": "Send availability to the recruiter",
                        "title": "Send availability to recruiter",
                        "life_state": "prepared",
                        "next_action": "Review the availability draft.",
                        "prepared_actions": [
                            {
                                "kind": "email_draft",
                                "title": "Recruiter availability draft",
                                "body": "Hi, I am available Tuesday or Thursday afternoon.",
                                "risk_level": "consequential",
                                "requires_approval": True,
                            },
                            {
                                "kind": "appointment_prep",
                                "title": "Availability prep",
                                "body": (
                                    "Check personal calendar, then compare against recruiter "
                                    "windows."
                                ),
                                "risk_level": "internal",
                                "requires_approval": False,
                            },
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    payload = _post_life(client, "I need to send availability to the recruiter.")

    item = payload["captured"][0]
    assert item["life_state"] == "prepared"
    assert item["prepared_actions"][0]["kind"] == "email_draft"
    assert item["prepared_actions"][1]["kind"] == "appointment_prep"
    assert item["prepared_actions"][0]["requires_approval"] is True
    assert "Tuesday" in item["prepared_actions"][0]["body"]


def test_life_agent_receives_raw_loop_evidence_without_local_judgment(
    make_test_client,
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the research loop.",
                    "captures": [
                        {
                            "raw_text": "Research supplement",
                            "title": "Research supplement",
                            "life_state": "active",
                            "confidence": 0.9,
                        }
                    ],
                }
            )

        signals = user_payload["open_loops"][0]["life_signals"]
        assert signals["deferral_count"] == 2
        assert signals["days_since_update"] >= 5
        assert signals["has_next_action"] is False
        assert signals["snooze_until_utc"] == "2026-05-09T08:00:00+00:00"
        assert signals["snooze_seconds_remaining"] > 0
        assert signals["last_agent_touch_utc"] is not None
        assert signals["last_user_touch_utc"] is not None
        assert signals["days_since_user_touch"] is not None
        assert signals["last_deferred_utc"] is not None
        assert signals["stored_confidence"] == 0.9
        assert "is_stale_by_age" not in signals
        assert "repeated_deferral" not in signals
        assert "decayed_confidence" not in signals
        return _agent_response(
            {
                "mode": "resurface",
                "reply": "This has been deferred twice and needs a real decision.",
                "groups": [
                    {
                        "name": "stale_needs_decision",
                        "title": "Stale and needs a decision",
                        "summary": (
                            "Repeatedly deferred loops that should not stay active by default."
                        ),
                        "items": [
                            {
                                "loop_id": user_payload["open_loops"][0]["id"],
                                "life_state": "stale",
                                "rationale": "The agent judged this as stale from raw evidence.",
                            }
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    loop_id = _post_life(client, "Research supplement")["captured"][0]["loop"]["id"]
    for snooze_until in ("2026-05-08T08:00:00+00:00", "2026-05-09T08:00:00+00:00"):
        response = client.patch(
            f"/loops/{loop_id}",
            json={"snooze_until_utc": snooze_until},
        )
        assert response.status_code == 200

    with closing(sqlite3.connect(tmp_path / "core.db")) as conn:
        conn.execute(
            "UPDATE loops SET updated_at = ? WHERE id = ?",
            ("2026-05-01T08:00:00+00:00", loop_id),
        )
        conn.commit()

    payload = _post_life(client, "What am I avoiding?")

    assert payload["mode"] == "resurface"
    assert payload["groups"][0]["name"] == "stale_needs_decision"


def test_life_records_user_touch_events_for_life_feed_turns(
    make_test_client,
    monkeypatch,
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        assert user_payload["interaction_source"] == "user"
        return _agent_response(
            {
                "mode": "capture",
                "reply": "Captured the medicine loop.",
                "captures": [
                    {
                        "raw_text": "Pick up medicine",
                        "title": "Pick up medicine",
                        "life_state": "active",
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)

    loop_id = _post_life(client, "Pick up medicine")["captured"][0]["loop"]["id"]

    events = client.get(f"/loops/{loop_id}/events").json()["events"]
    user_touch = [event for event in events if event["event_type"] == "life_user_touched"]
    assert user_touch
    assert user_touch[0]["payload"]["actor"] == "user"
    assert user_touch[0]["payload"]["message_preview"] == "Pick up medicine"


def test_life_agent_receives_authority_contract_instead_of_cleanup_override(
    make_test_client,
    monkeypatch,
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        schema_payload = json.loads(messages[2]["content"])
        assert "act_on_obvious_cleanup" not in user_payload
        assert "notify_user" in schema_payload
        assert "notification_title" in schema_payload
        assert schema_payload["cleanup_actions"][0]["risk_level"] == (
            "safe_internal | reversible_internal | external_low | consequential"
        )
        assert "loop_status" in schema_payload["captures"][0]
        assert "loop_status" in schema_payload["updates"][0]
        assert "target_loop_status" in schema_payload["cleanup_actions"][0]
        assert "cleanup_bucket" in schema_payload["cleanup_actions"][0]
        assert "result_life_state" in schema_payload["cleanup_actions"][0]
        assert "approval_basis" in schema_payload["cleanup_actions"][0]
        assert "approval_basis" in schema_payload["memory_updates"][0]
        assert "memory_layer" in schema_payload["memory_updates"][0]
        assert "items" in schema_payload["groups"][0]
        return _agent_response(
            {
                "mode": "resurface",
                "reply": "No cleanup needed.",
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)

    payload = _post_life(client, "Clean up anything obvious.")

    assert payload["mode"] == "resurface"


def test_life_agent_status_contract_has_no_production_lifecycle_maps() -> None:
    source = Path("src/cloop/life_orchestration.py").read_text(encoding="utf-8")

    assert "_LIFE_TO_LOOP_STATUS" not in source
    assert "_CLEANUP_ACTION_TO_STATUS" not in source
    assert "_memory_update_layer" not in source
    assert "target_status = LoopStatus" not in source
    assert '"archive_cold": "cold"' not in source
    assert "group.loop_ids" not in source


def test_life_resurfacing_returns_plain_language_groups(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the recruiter loop.",
                    "captures": [
                        {
                            "raw_text": "Need to send availability to the recruiter",
                            "title": "Send availability to the recruiter",
                            "life_state": "active",
                            "time_minutes": 3,
                        }
                    ],
                }
            )
        loop_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "resurface",
                "reply": "What matters: send availability to the recruiter.",
                "groups": [
                    {
                        "name": "quick_wins",
                        "title": "Quick wins",
                        "summary": "Small loops that can move today.",
                        "items": [
                            {
                                "loop_id": loop_id,
                                "life_state": "prepared",
                                "rationale": "The agent says this is tiny and already clear.",
                                "prepared_next_action": "Send one availability text.",
                            }
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    loop_id = _post_life(client, "Need to send availability to the recruiter")["captured"][0][
        "loop"
    ]["id"]

    payload = _post_life(client, "What matters today?")

    assert payload["mode"] == "resurface"
    assert "matter" in payload["reply"].lower() or "urgent" in payload["reply"].lower()
    assert any(group["name"] == "quick_wins" for group in payload["groups"])
    quick_win = payload["groups"][0]["items"][0]
    assert quick_win["life_state"] == "prepared"
    assert quick_win["rationale"] == "The agent says this is tiny and already clear."
    assert quick_win["prepared_next_action"] == "Send one availability text."
    events = client.get(f"/loops/{loop_id}/events").json()["events"]
    resurface_events = [event for event in events if event["event_type"] == "life_resurfaced"]
    assert resurface_events
    assert resurface_events[0]["payload"]["group"] == "quick_wins"


def test_life_aggressive_cleanup_archives_stale_ideas_with_undo(
    make_test_client, monkeypatch
) -> None:
    client = make_test_client()
    old = datetime.now(timezone.utc) - timedelta(days=30)

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the pizza oven idea.",
                    "captures": [
                        {
                            "raw_text": "Look into building a backyard pizza oven",
                            "title": "Backyard pizza oven",
                            "summary": "Stale low-risk idea.",
                            "life_state": "captured",
                            "tags": ["life", "idea"],
                            "group_names": ["ideas_not_tasks"],
                        }
                    ],
                }
            )
        loop_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "I found one stale low-risk idea and archived it.",
                "cleanup_actions": [
                    {
                        "loop_id": loop_id,
                        "action": "archive",
                        "rationale": "Stale low-risk idea.",
                        "cleanup_bucket": "archive_candidate",
                        "result_life_state": "archived",
                        "apply_now": True,
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    _post_life(client, "Look into building a backyard pizza oven", captured_at=old.isoformat())

    payload = _post_life(client, "Clean up anything obvious and be aggressive.")

    assert payload["mode"] == "cleanup"
    cleanup = payload["cleanup"]
    assert cleanup["applied_automatic_cleanup"]
    archived = cleanup["applied_automatic_cleanup"][0]
    assert archived["life_state"] == "archived"
    assert cleanup["undo"][0]["loop_id"] == archived["loop"]["id"]
    assert cleanup["undo"][0]["expected_event_id"] == archived["loop"]["latest_reversible_event_id"]


def test_life_cleanup_bucket_is_agent_owned(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the uncertain idea.",
                    "captures": [
                        {
                            "raw_text": "Maybe build a garage shelf",
                            "title": "Garage shelf idea",
                            "life_state": "active",
                        }
                    ],
                }
            )
        loop_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "This looks stale, but I want your call.",
                "cleanup_actions": [
                    {
                        "loop_id": loop_id,
                        "action": "archive",
                        "cleanup_bucket": "review_needed",
                        "result_life_state": "stale",
                        "rationale": "The agent chose review instead of automatic archive.",
                        "apply_now": False,
                        "approval_basis": "review_only",
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    _post_life(client, "Maybe build a garage shelf")

    payload = _post_life(client, "Clean up stale ideas.")

    cleanup = payload["cleanup"]
    assert cleanup["archive_candidates"] == []
    assert cleanup["review_needed"][0]["life_state"] == "stale"
    assert cleanup["review_needed"][0]["rationale"] == (
        "The agent chose review instead of automatic archive."
    )


def test_life_cleanup_rejects_consequential_action_without_delegated_authority(
    make_test_client,
    monkeypatch,
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the application loop.",
                    "captures": [
                        {
                            "raw_text": "Submit job application",
                            "title": "Submit job application",
                            "life_state": "active",
                        }
                    ],
                }
            )
        loop_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "I marked this done.",
                "cleanup_actions": [
                    {
                        "loop_id": loop_id,
                        "action": "complete",
                        "rationale": "This would be consequential without authority.",
                        "apply_now": True,
                        "risk_level": "consequential",
                        "approval_basis": "review_only",
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    _post_life(client, "Submit job application")

    response = client.post(
        "/life/message",
        json={
            "message": "Clean up this application loop.",
            "captured_at": "2026-05-07T08:00:00-06:00",
            "client_tz_offset_min": -360,
        },
    )

    assert response.status_code == 400
    assert "delegated authority" in response.text


def test_life_cleanup_can_reschedule_and_mark_waiting(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if len(user_payload["open_loops"]) < 2:
            title = user_payload["user_message"].removeprefix("Create ").strip()
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": f"Captured {title}.",
                    "captures": [
                        {
                            "raw_text": title,
                            "title": title,
                            "life_state": "active",
                        }
                    ],
                }
            )
        by_title = {item["title"]: item["id"] for item in user_payload["open_loops"]}
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "I rescheduled one loop and marked one waiting.",
                "cleanup_actions": [
                    {
                        "loop_id": by_title["Call pharmacy"],
                        "action": "reschedule",
                        "rationale": "User wants it later.",
                        "apply_now": True,
                        "due_at_utc": "2026-05-10T15:00:00+00:00",
                    },
                    {
                        "loop_id": by_title["Recruiter reply"],
                        "action": "mark_waiting",
                        "rationale": "Waiting on the recruiter.",
                        "apply_now": True,
                        "blocked_reason": "Waiting on recruiter.",
                    },
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    _post_life(client, "Create Call pharmacy")
    _post_life(client, "Create Recruiter reply")

    payload = _post_life(client, "Move pharmacy later and mark recruiter waiting.")

    states = {item["loop"]["title"]: item for item in payload["updated"]}
    assert states["Call pharmacy"]["life_state"] == "scheduled"
    assert states["Call pharmacy"]["loop"]["status"] == "scheduled"
    assert states["Call pharmacy"]["loop"]["due_at_utc"].startswith("2026-05-10T15:00:00")
    assert states["Recruiter reply"]["life_state"] == "waiting"
    assert states["Recruiter reply"]["loop"]["status"] == "blocked"
    assert states["Recruiter reply"]["loop"]["blocked_reason"] == "Waiting on recruiter."
    assert len(payload["cleanup"]["undo"]) == 2


def test_life_cleanup_can_mark_loop_delegated(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the paperwork loop.",
                    "captures": [
                        {
                            "raw_text": "Ask Ryan to handle the school paperwork",
                            "title": "School paperwork",
                            "life_state": "active",
                        }
                    ],
                }
            )
        loop_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "Delegated to Ryan and moved it out of active load.",
                "cleanup_actions": [
                    {
                        "loop_id": loop_id,
                        "action": "delegate",
                        "rationale": "Ryan owns the next move now.",
                        "apply_now": True,
                        "delegated_to": "Ryan",
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    _post_life(client, "Ask Ryan to handle the school paperwork")

    payload = _post_life(client, "Ryan has this now.")

    delegated = payload["updated"][0]
    assert delegated["life_state"] == "waiting"
    assert delegated["loop"]["status"] == "blocked"
    assert delegated["loop"]["blocked_reason"] == "Delegated to Ryan."


def test_life_agent_can_manage_loop_dependencies(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if len(user_payload["open_loops"]) < 2:
            title = user_payload["user_message"].removeprefix("Create ").strip()
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": f"Captured {title}.",
                    "captures": [
                        {
                            "raw_text": title,
                            "title": title,
                            "life_state": "active",
                        }
                    ],
                }
            )
        by_title = {item["title"]: item for item in user_payload["open_loops"]}
        application = by_title["Submit application"]
        transcript = by_title["Get transcript"]
        if "Remove" in user_payload["user_message"]:
            signals = application["life_signals"]
            assert signals["dependency_loop_ids"] == [transcript["id"]]
            assert signals["has_open_dependencies"] is True
            assert transcript["life_signals"]["blocking_loop_ids"] == [application["id"]]
            return _agent_response(
                {
                    "mode": "cleanup",
                    "reply": "Removed the blocker link.",
                    "cleanup_actions": [
                        {
                            "loop_id": application["id"],
                            "target_loop_id": transcript["id"],
                            "action": "remove_dependency",
                            "rationale": "The transcript no longer blocks the application.",
                            "apply_now": True,
                        }
                    ],
                }
            )
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "Marked the application as blocked by the transcript.",
                "cleanup_actions": [
                    {
                        "loop_id": application["id"],
                        "target_loop_id": transcript["id"],
                        "action": "add_dependency",
                        "rationale": "The application cannot move until the transcript is ready.",
                        "apply_now": True,
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    application_id = _post_life(client, "Create Submit application")["captured"][0]["loop"]["id"]
    transcript_id = _post_life(client, "Create Get transcript")["captured"][0]["loop"]["id"]

    added = _post_life(client, "Transcript blocks the application.")

    assert added["updated"][0]["loop"]["id"] == application_id
    assert added["updated"][0]["loop"]["status"] == "blocked"
    deps = client.get(f"/loops/{application_id}/dependencies").json()
    assert deps == [{"id": transcript_id, "title": "Get transcript", "status": "actionable"}]

    removed = _post_life(client, "Remove the transcript blocker.")

    assert removed["updated"][0]["loop"]["id"] == application_id
    assert client.get(f"/loops/{application_id}/dependencies").json() == []


def test_life_cleanup_can_merge_obvious_duplicates(
    make_test_client, monkeypatch, tmp_path: Path
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if len(user_payload["open_loops"]) < 2:
            title = user_payload["user_message"].removeprefix("Create ").strip()
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": f"Captured {title}.",
                    "captures": [
                        {
                            "raw_text": title,
                            "title": title,
                            "life_state": "active",
                        }
                    ],
                }
            )
        by_title = {item["title"]: item["id"] for item in user_payload["open_loops"]}
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "I merged the duplicate medicine loops.",
                "cleanup_actions": [
                    {
                        "loop_id": by_title["Pick up prescription"],
                        "target_loop_id": by_title["Pick up medicine"],
                        "action": "merge",
                        "rationale": "Both loops are the same medication pickup intent.",
                        "apply_now": True,
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    surviving_id = _post_life(client, "Create Pick up medicine")["captured"][0]["loop"]["id"]
    duplicate_id = _post_life(client, "Create Pick up prescription")["captured"][0]["loop"]["id"]

    payload = _post_life(client, "Merge the duplicate medicine pickup loops.")

    assert payload["mode"] == "cleanup"
    assert payload["cleanup"]["applied_automatic_cleanup"][0]["loop"]["id"] == surviving_id
    assert payload["cleanup"]["applied_automatic_cleanup"][0]["rationale"].startswith("Both loops")
    with closing(sqlite3.connect(tmp_path / "core.db")) as conn:
        duplicate = conn.execute(
            "SELECT status, completion_note FROM loops WHERE id = ?",
            (duplicate_id,),
        ).fetchone()
        assert duplicate == ("dropped", f"Merged into loop #{surviving_id}")
        events = conn.execute(
            """
            SELECT loop_id, event_type, payload_json
            FROM loop_events
            WHERE loop_id IN (?, ?)
            ORDER BY id ASC
            """,
            (surviving_id, duplicate_id),
        ).fetchall()
    assert any(
        row[0] == surviving_id
        and row[1] == "update"
        and json.loads(row[2]).get("action") == "merge_absorbed"
        for row in events
    )
    assert any(
        row[0] == duplicate_id
        and row[1] == "close"
        and json.loads(row[2]).get("action") == "merged_into"
        for row in events
    )


def test_life_agent_can_split_large_loop_into_child_steps(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if not user_payload["open_loops"]:
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": "Captured the job search loop.",
                    "captures": [
                        {
                            "raw_text": "Restart job search",
                            "title": "Restart job search",
                            "life_state": "active",
                        }
                    ],
                }
            )
        parent_id = user_payload["open_loops"][0]["id"]
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "I split that into two smaller next steps.",
                "updates": [
                    {
                        "loop_id": parent_id,
                        "fields": {
                            "next_action": "Start with the two child steps.",
                        },
                        "life_state": "active",
                        "rationale": "The original loop was too broad to act on directly.",
                    }
                ],
                "captures": [
                    {
                        "raw_text": "Send availability to recruiter",
                        "title": "Send availability to recruiter",
                        "life_state": "active",
                        "parent_loop_id": parent_id,
                        "time_minutes": 3,
                        "group_names": ["quick_wins"],
                    },
                    {
                        "raw_text": "Pick three jobs to apply to",
                        "title": "Pick three jobs to apply to",
                        "life_state": "active",
                        "parent_loop_id": parent_id,
                        "time_minutes": 10,
                    },
                ],
                "groups": [
                    {
                        "name": "quick_wins",
                        "title": "Three-minute steps",
                        "summary": "Agent-picked tiny child loops.",
                        "loop_ids": [],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    parent_id = _post_life(client, "Restart job search")["captured"][0]["loop"]["id"]

    payload = _post_life(client, "Split the job search loop into small steps.")

    assert payload["mode"] == "cleanup"
    assert len(payload["captured"]) == 2
    assert {item["loop"]["parent_loop_id"] for item in payload["captured"]} == {parent_id}
    assert payload["updated"][0]["loop"]["next_action"] == "Start with the two child steps."
    groups = {group["name"]: group for group in payload["groups"]}
    assert groups["quick_wins"]["items"][0]["loop"]["parent_loop_id"] == parent_id


def test_life_agent_can_apply_distinct_terminal_lifecycle_actions(
    make_test_client, monkeypatch
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if len(user_payload["open_loops"]) < 3:
            title = user_payload["user_message"].removeprefix("Create ").strip()
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": f"Captured {title}.",
                    "captures": [
                        {
                            "raw_text": title,
                            "title": title,
                            "life_state": "active",
                        }
                    ],
                }
            )
        by_title = {item["title"]: item["id"] for item in user_payload["open_loops"]}
        return _agent_response(
            {
                "mode": "cleanup",
                "reply": "Closed, abandoned, and deleted the requested loops.",
                "cleanup_actions": [
                    {
                        "loop_id": by_title["Done loop"],
                        "action": "complete",
                        "rationale": "User explicitly said it is done.",
                        "cleanup_bucket": "close_candidate",
                        "result_life_state": "completed",
                        "apply_now": True,
                        "note": "Done by explicit Life request.",
                    },
                    {
                        "loop_id": by_title["No longer matters"],
                        "action": "abandon",
                        "rationale": "User explicitly stopped caring.",
                        "cleanup_bucket": "archive_candidate",
                        "result_life_state": "abandoned",
                        "apply_now": True,
                        "note": "Intentionally abandoned by explicit Life request.",
                    },
                    {
                        "loop_id": by_title["Delete me"],
                        "action": "delete",
                        "rationale": "User explicitly asked to delete this loop.",
                        "cleanup_bucket": "archive_candidate",
                        "result_life_state": "deleted",
                        "apply_now": True,
                    },
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    _post_life(client, "Create Done loop")
    _post_life(client, "Create No longer matters")
    delete_loop = _post_life(client, "Create Delete me")["captured"][0]["loop"]

    payload = _post_life(
        client,
        "The done loop is done, abandon no longer matters, and delete Delete me.",
    )

    states = {item["loop"]["title"]: item["life_state"] for item in payload["updated"]}
    assert states["Done loop"] == "completed"
    assert states["No longer matters"] == "abandoned"
    assert states["Delete me"] == "deleted"
    assert client.get(f"/loops/{delete_loop['id']}").status_code == 404


def test_life_agent_can_show_history_and_archive(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if len(user_payload["open_loops"]) < 2 and not user_payload["recent_history"]:
            title = user_payload["user_message"].removeprefix("Create ").strip()
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": f"Captured {title}.",
                    "captures": [
                        {
                            "raw_text": title,
                            "title": title,
                            "life_state": "active",
                        }
                    ],
                }
            )
        if "Close" in user_payload["user_message"]:
            by_title = {item["title"]: item["id"] for item in user_payload["open_loops"]}
            return _agent_response(
                {
                    "mode": "cleanup",
                    "reply": "Closed one loop and archived one.",
                    "cleanup_actions": [
                        {
                            "loop_id": by_title["Pay water bill"],
                            "action": "complete",
                            "rationale": "The user says this is done.",
                            "apply_now": True,
                        },
                        {
                            "loop_id": by_title["Old pizza oven idea"],
                            "action": "archive",
                            "rationale": "The user wants this out of active load.",
                            "apply_now": True,
                        },
                    ],
                }
            )
        history_by_title = {item["title"]: item for item in user_payload["recent_history"]}
        assert history_by_title["Pay water bill"]["status"] == "completed"
        assert history_by_title["Old pizza oven idea"]["status"] == "dropped"
        return _agent_response(
            {
                "mode": "resurface",
                "reply": "Here is what moved out of active load.",
                "groups": [
                    {
                        "name": "history",
                        "title": "Handled and archived",
                        "summary": "Recent loops no longer in active mental load.",
                        "items": [
                            {
                                "loop_id": history_by_title["Pay water bill"]["id"],
                                "life_state": "completed",
                                "rationale": "The agent says this was completed.",
                            },
                            {
                                "loop_id": history_by_title["Old pizza oven idea"]["id"],
                                "life_state": "archived",
                                "rationale": "The agent says this was archived.",
                            },
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    _post_life(client, "Create Pay water bill")
    _post_life(client, "Create Old pizza oven idea")
    _post_life(client, "Close the water bill and archive the pizza oven idea.")

    payload = _post_life(client, "Show my history and archive.")

    history = payload["groups"][0]
    assert history["name"] == "history"
    assert history["title"] == "Handled and archived"
    states = {item["loop"]["title"]: item["life_state"] for item in history["items"]}
    assert states == {
        "Pay water bill": "completed",
        "Old pizza oven idea": "archived",
    }


def test_life_agent_handles_what_am_i_missing_prompt(make_test_client, monkeypatch) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if "Create" in user_payload["user_message"]:
            title = user_payload["user_message"].removeprefix("Create ").strip()
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": f"Captured {title}.",
                    "captures": [
                        {
                            "raw_text": title,
                            "title": title,
                            "life_state": "active",
                        }
                    ],
                }
            )

        assert user_payload["user_message"] == "What am I missing?"
        assert len(user_payload["open_loops"]) == 2
        loop_without_next_action = next(
            loop for loop in user_payload["open_loops"] if loop["title"] == "Renew car tabs"
        )
        assert loop_without_next_action["life_signals"]["has_next_action"] is False
        return _agent_response(
            {
                "mode": "resurface",
                "reply": "You are missing the next step for car tabs.",
                "groups": [
                    {
                        "name": "needs_attention_today",
                        "title": "Missing next step",
                        "summary": "Open loops where the agent sees ambiguity worth clearing.",
                        "items": [
                            {
                                "loop_id": loop_without_next_action["id"],
                                "life_state": "needs_clarification",
                                "rationale": (
                                    "This loop is active but still lacks a concrete next move."
                                ),
                                "prepared_next_action": "Find the renewal notice or DMV page.",
                            }
                        ],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    _post_life(client, "Create Renew car tabs")
    _post_life(client, "Create Send school form")

    payload = _post_life(client, "What am I missing?")

    assert payload["mode"] == "resurface"
    assert payload["groups"][0]["name"] == "needs_attention_today"
    item = payload["groups"][0]["items"][0]
    assert item["life_state"] == "needs_clarification"
    assert item["prepared_next_action"] == "Find the renewal notice or DMV page."


def test_life_agent_handles_quiz_me_prompt_with_contextual_question(
    make_test_client,
    monkeypatch,
) -> None:
    client = make_test_client()

    def fake_chat_completion(
        messages: list[dict[str, str]], **_: object
    ) -> tuple[str, dict[str, Any]]:
        user_payload = _user_payload(messages)
        if "Create" in user_payload["user_message"]:
            title = user_payload["user_message"].removeprefix("Create ").strip()
            return _agent_response(
                {
                    "mode": "capture",
                    "reply": f"Captured {title}.",
                    "captures": [
                        {
                            "raw_text": title,
                            "title": title,
                            "life_state": "active",
                        }
                    ],
                }
            )

        assert user_payload["user_message"] == "Quiz me on what is open."
        medicine_loop = next(
            loop for loop in user_payload["open_loops"] if loop["title"] == "Pick up medicine"
        )
        return _agent_response(
            {
                "mode": "resurface",
                "reply": "One quick question: where is the medicine pickup?",
                "clarifications": [
                    {
                        "loop_id": medicine_loop["id"],
                        "question": "Which pharmacy should this be tied to?",
                        "assumption": "Assuming the usual pharmacy unless you say otherwise.",
                        "rationale": "The answer makes the errand actionable.",
                        "improves": ["location", "next_action"],
                    }
                ],
            }
        )

    monkeypatch.setattr("cloop.life_orchestration.chat_completion", fake_chat_completion)
    loop_id = _post_life(client, "Create Pick up medicine")["captured"][0]["loop"]["id"]

    payload = _post_life(client, "Quiz me on what is open.")

    clarification = payload["clarifications"][0]
    assert clarification["loop_id"] == loop_id
    assert clarification["question"] == "Which pharmacy should this be tied to?"
    stored = client.get(f"/loops/{loop_id}/clarifications").json()["clarifications"]
    assert stored[0]["question"] == "Which pharmacy should this be tied to?"
