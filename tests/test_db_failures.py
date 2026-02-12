"""Tests for database failure scenarios.

Purpose: Verify database error handling and response shapes during CRUD operations.
Non-scope: Testing actual SQLite behavior (assume sqlite3 works).
Invariants: All unhandled database errors return 500 with sanitized error response.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloop import db
from cloop.main import app
from cloop.settings import get_settings


def _now_iso() -> str:
    """Return current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _make_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create test client with isolated database."""
    monkeypatch.setenv("CLOOP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOOP_AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("CLOOP_LLM_MODEL", "mock-llm")
    monkeypatch.setenv("CLOOP_EMBED_MODEL", "mock-embed")
    get_settings.cache_clear()
    db.init_databases(get_settings())
    return TestClient(app, raise_server_exceptions=False)


class TestDatabaseOperationalError:
    """Tests for sqlite3.OperationalError scenarios."""

    def test_create_loop_database_locked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that database locked error returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_capture_loop(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr("cloop.loops.service.capture_loop", mock_capture_loop)

        response = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test task",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        )
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["type"] == "server_error"
        assert data["error"]["message"] == "Unexpected server error"

    def test_update_loop_disk_io_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that disk I/O error returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        create_response = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test task",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        )
        assert create_response.status_code == 200
        loop_id = create_response.json()["id"]

        def mock_update_loop(*args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr("cloop.loops.service.update_loop", mock_update_loop)

        response = client.patch(f"/loops/{loop_id}", json={"title": "Updated"})
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["type"] == "server_error"


class TestDatabaseIntegrityError:
    """Tests for sqlite3.IntegrityError scenarios."""

    def test_create_loop_unique_constraint_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that UNIQUE constraint violation returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        def mock_capture_loop(*args, **kwargs):
            raise sqlite3.IntegrityError("UNIQUE constraint failed: loops.title")

        monkeypatch.setattr("cloop.loops.service.capture_loop", mock_capture_loop)

        response = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test task",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        )
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["type"] == "server_error"

    def test_update_loop_foreign_key_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that FK constraint violation returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        create_response = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test task",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        )
        assert create_response.status_code == 200
        loop_id = create_response.json()["id"]

        def mock_update_loop(*args, **kwargs):
            raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

        monkeypatch.setattr("cloop.loops.service.update_loop", mock_update_loop)

        response = client.patch(f"/loops/{loop_id}", json={"tags": ["test"]})
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["type"] == "server_error"


class TestDatabaseDiskFullError:
    """Tests for disk full scenarios."""

    def test_ingest_disk_full_during_chunk_insert(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that disk full during RAG ingestion returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        doc = tmp_path / "test.txt"
        doc.write_text("Test document content", encoding="utf-8")

        def mock_ingest_paths(*args, **kwargs):
            raise sqlite3.DatabaseError("database or disk is full")

        monkeypatch.setattr("cloop.rag.ingest_paths", mock_ingest_paths)

        response = client.post("/ingest", json={"paths": [str(doc)]})
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["type"] == "server_error"


class TestDatabaseGenericError:
    """Tests for generic database errors."""

    def test_get_loop_database_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that database errors during get returns 500."""
        client = _make_client(tmp_path, monkeypatch)

        create_response = client.post(
            "/loops/capture",
            json={
                "raw_text": "Test task",
                "captured_at": _now_iso(),
                "client_tz_offset_min": 0,
            },
        )
        assert create_response.status_code == 200
        loop_id = create_response.json()["id"]

        def mock_get_loop(*args, **kwargs):
            raise sqlite3.DatabaseError("database disk image is malformed")

        monkeypatch.setattr("cloop.loops.service.get_loop", mock_get_loop)

        response = client.get(f"/loops/{loop_id}")
        assert response.status_code == 500
        data = response.json()
        assert data["error"]["type"] == "server_error"
