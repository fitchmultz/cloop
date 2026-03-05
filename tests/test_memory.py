"""Tests for assistant memory store.

Coverage:
- Schema migration creates memory_entries table
- CRUD round-trips via API
- Search functionality
- Pagination with cursor
- Tool executors
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.settings import get_settings


class TestMemoryMigration:
    """Test schema migration for memory_entries table."""

    def test_memory_table_created_on_init(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Memory table exists after init_databases."""
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        get_settings.cache_clear()
        db.init_databases(get_settings())

        with closing(sqlite3.connect(tmp_path / "core.db")) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_entries'"
            ).fetchone()
        assert row is not None

    def test_memory_indexes_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Performance indexes exist on memory_entries."""
        monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
        get_settings.cache_clear()
        db.init_databases(get_settings())

        with closing(sqlite3.connect(tmp_path / "core.db")) as conn:
            indexes = conn.execute(
                "SELECT name FROM pragma_index_list('memory_entries')"
            ).fetchall()
        index_names = {row[0] for row in indexes}
        assert "idx_memory_entries_category" in index_names
        assert "idx_memory_entries_priority" in index_names


class TestMemoryCRUD:
    """Test memory CRUD via API."""

    def test_create_memory(self, test_client: TestClient) -> None:
        """Create a new memory entry."""
        response = test_client.post(
            "/memory",
            json={
                "key": "preferred_editor",
                "content": "User prefers VSCode with Vim keybindings",
                "category": "preference",
                "priority": 50,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["key"] == "preferred_editor"
        assert data["content"] == "User prefers VSCode with Vim keybindings"
        assert data["category"] == "preference"
        assert data["priority"] == 50
        assert data["source"] == "user_stated"

    def test_get_memory(self, test_client: TestClient) -> None:
        """Get a memory entry by ID."""
        create_resp = test_client.post(
            "/memory",
            json={"content": "Test memory", "category": "fact"},
        )
        entry_id = create_resp.json()["id"]

        response = test_client.get(f"/memory/{entry_id}")
        assert response.status_code == 200
        assert response.json()["content"] == "Test memory"

    def test_update_memory(self, test_client: TestClient) -> None:
        """Update a memory entry."""
        create_resp = test_client.post(
            "/memory",
            json={"content": "Original content"},
        )
        entry_id = create_resp.json()["id"]

        update_resp = test_client.put(
            f"/memory/{entry_id}",
            json={"content": "Updated content", "priority": 75},
        )
        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["content"] == "Updated content"
        assert data["priority"] == 75

    def test_delete_memory(self, test_client: TestClient) -> None:
        """Delete a memory entry."""
        create_resp = test_client.post(
            "/memory",
            json={"content": "To be deleted"},
        )
        entry_id = create_resp.json()["id"]

        delete_resp = test_client.delete(f"/memory/{entry_id}")
        assert delete_resp.status_code == 204

        get_resp = test_client.get(f"/memory/{entry_id}")
        assert get_resp.status_code == 404

    def test_get_nonexistent_memory(self, test_client: TestClient) -> None:
        """Getting nonexistent memory returns 404."""
        response = test_client.get("/memory/99999")
        assert response.status_code == 404


class TestMemoryListAndSearch:
    """Test memory listing and search."""

    def test_list_memories(self, test_client: TestClient) -> None:
        """List all memories."""
        for i in range(3):
            test_client.post(
                "/memory",
                json={"content": f"Memory {i}", "category": "fact"},
            )

        response = test_client.get("/memory")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 3

    def test_list_memories_with_category_filter(self, test_client: TestClient) -> None:
        """Filter memories by category."""
        test_client.post("/memory", json={"content": "Pref 1", "category": "preference"})
        test_client.post("/memory", json={"content": "Fact 1", "category": "fact"})

        response = test_client.get("/memory?category=preference")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["category"] == "preference"

    def test_search_memories(self, test_client: TestClient) -> None:
        """Search memories by text."""
        test_client.post("/memory", json={"content": "User likes coffee"})
        test_client.post("/memory", json={"content": "User works remotely"})
        test_client.post("/memory", json={"content": "Team meeting on Mondays"})

        response = test_client.get("/memory/search?q=coffee")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert "coffee" in items[0]["content"].lower()

    def test_search_by_key(self, test_client: TestClient) -> None:
        """Search finds memories by key field."""
        test_client.post(
            "/memory",
            json={"key": "timezone", "content": "America/New_York"},
        )

        response = test_client.get("/memory/search?q=timezone")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["key"] == "timezone"


class TestMemoryTools:
    """Test memory tool executors."""

    def test_memory_create_tool(self, test_client: TestClient) -> None:
        """memory_create tool creates entry."""
        response = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Remember this"}],
                "tool_call": {
                    "name": "memory_create",
                    "arguments": {
                        "content": "User prefers dark mode",
                        "category": "preference",
                        "priority": 30,
                    },
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tool_result"]["action"] == "memory_create"
        assert data["tool_result"]["memory"]["content"] == "User prefers dark mode"

    def test_memory_search_tool(self, test_client: TestClient) -> None:
        """memory_search tool finds entries."""
        test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Store"}],
                "tool_call": {
                    "name": "memory_create",
                    "arguments": {"content": "API key is abc123"},
                },
            },
        )

        response = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Find"}],
                "tool_call": {
                    "name": "memory_search",
                    "arguments": {"query": "API key"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tool_result"]["action"] == "memory_search"
        assert len(data["tool_result"]["memories"]) >= 1

    def test_memory_update_tool(self, test_client: TestClient) -> None:
        """memory_update tool updates entry."""
        create_resp = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Store"}],
                "tool_call": {
                    "name": "memory_create",
                    "arguments": {"content": "Original content"},
                },
            },
        )
        entry_id = create_resp.json()["tool_result"]["memory"]["id"]

        response = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Update"}],
                "tool_call": {
                    "name": "memory_update",
                    "arguments": {"entry_id": entry_id, "content": "Updated content"},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tool_result"]["action"] == "memory_update"
        assert data["tool_result"]["memory"]["content"] == "Updated content"

    def test_memory_delete_tool(self, test_client: TestClient) -> None:
        """memory_delete tool removes entry."""
        create_resp = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Store"}],
                "tool_call": {
                    "name": "memory_create",
                    "arguments": {"content": "To delete"},
                },
            },
        )
        entry_id = create_resp.json()["tool_result"]["memory"]["id"]

        response = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Delete"}],
                "tool_call": {
                    "name": "memory_delete",
                    "arguments": {"entry_id": entry_id},
                },
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["tool_result"]["action"] == "memory_delete"
        assert data["tool_result"]["deleted"] is True

    def test_memory_update_nonexistent_tool(self, test_client: TestClient) -> None:
        """memory_update tool raises error for non-existent entry."""
        response = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Update"}],
                "tool_call": {
                    "name": "memory_update",
                    "arguments": {"entry_id": 99999, "content": "Updated"},
                },
            },
        )
        assert response.status_code == 404

    def test_memory_delete_nonexistent_tool(self, test_client: TestClient) -> None:
        """memory_delete tool raises error for non-existent entry."""
        response = test_client.post(
            "/chat",
            json={
                "messages": [{"role": "user", "content": "Delete"}],
                "tool_call": {
                    "name": "memory_delete",
                    "arguments": {"entry_id": 99999},
                },
            },
        )
        assert response.status_code == 404


class TestMemoryValidation:
    """Test memory validation constraints."""

    def test_create_with_invalid_category(self, test_client: TestClient) -> None:
        """Invalid category is rejected by Pydantic validation."""
        response = test_client.post(
            "/memory",
            json={"content": "Test", "category": "invalid_category"},
        )
        assert response.status_code == 422  # Pydantic validation error

    def test_create_with_invalid_source(self, test_client: TestClient) -> None:
        """Invalid source is rejected by Pydantic validation."""
        response = test_client.post(
            "/memory",
            json={"content": "Test", "source": "invalid_source"},
        )
        assert response.status_code == 422  # Pydantic validation error

    def test_create_with_priority_out_of_range(self, test_client: TestClient) -> None:
        """Priority out of range is rejected by Pydantic."""
        response = test_client.post(
            "/memory",
            json={"content": "Test", "priority": 150},
        )
        assert response.status_code == 422  # Validation error
